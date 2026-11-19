"""Produtos e histórico de compras no Cassandra (DataStax Astra DB).

No Cassandra a modelagem nasce da consulta: cada consulta tem a sua tabela, e a
mesma informação pode ser gravada em mais de uma (denormalização).

| Tabela                  | Chave                                   | Consulta atendida                 |
|-------------------------|-----------------------------------------|-----------------------------------|
| usuario                 | cpf                                     | dados do usuário                  |
| vendedor                | cnpj                                    | dados do vendedor                 |
| produto                 | id_produto                              | dados de um produto               |
| produto_por_categoria   | ((id_categoria), titulo, id_produto)    | produtos da categoria, por título |
| compra                  | id_compra                               | dados de uma compra               |
| compra_por_usuario      | ((cpf), data_compra DESC, id_compra)    | compras do usuário, mais novas 1º |

A primeira metade do módulo é a camada de dados (devolve dados, não imprime);
a segunda é a interface interativa.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from functools import cache
from typing import Any, Sequence

from cassandra import InvalidRequest
from cassandra.query import BatchStatement

from . import dados_demo, ui
from .conexoes import cassandra_sessao, fechar_conexoes
from .validadores import (
    converter_decimal,
    converter_inteiro,
    formatar_cnpj,
    formatar_cpf,
    formatar_data,
    formatar_moeda,
    normalizar,
    validar_cnpj,
    validar_cpf,
    validar_email,
)

LIMITE_LISTAGEM = 200

RESUMO = [
    "Guarda linhas em TABELAS, mas cada tabela é desenhada para UMA consulta (sem JOIN).",
    "Aqui: histórico de compras. 'compra_por_usuario' já guarda as compras de cada pessoa em ordem de data.",
    "A mesma compra é gravada em 2 tabelas (denormalização): escrever é barato, consultar é rápido.",
    "Consultar por um campo que não é chave é recusado (teste no menu Produtos).",
]

DDL = [
    # Usuário: busca pelo CPF (partition key)
    """CREATE TABLE IF NOT EXISTS usuario (
        cpf text PRIMARY KEY, nome text, sobrenome text, email text,
        criado_em timestamp, atualizado_em timestamp)""",
    # Vendedor: busca pelo CNPJ (partition key)
    """CREATE TABLE IF NOT EXISTS vendedor (
        cnpj text PRIMARY KEY, nome_loja text, avaliacao decimal, status text, criado_em timestamp)""",
    # Produto, consulta 1: dados de um produto pelo id
    """CREATE TABLE IF NOT EXISTS produto (
        id_produto uuid PRIMARY KEY, titulo text, descricao text, preco decimal,
        quantidade_disponivel int, id_categoria text, cnpj_vendedor text, criado_em timestamp)""",
    # Produto, consulta 2: produtos de uma categoria em ordem alfabética.
    # partition key (id_categoria): a categoria inteira fica no mesmo nó;
    # clustering key (titulo, id_produto): já gravado em ordem e permite busca por prefixo.
    """CREATE TABLE IF NOT EXISTS produto_por_categoria (
        id_categoria text, titulo text, id_produto uuid, preco decimal, cnpj_vendedor text,
        PRIMARY KEY ((id_categoria), titulo, id_produto))""",
    # Compra, consulta 1: dados de uma compra pelo id (também usada para localizar a compra no DELETE)
    """CREATE TABLE IF NOT EXISTS compra (
        id_compra uuid PRIMARY KEY, cpf text, data_compra timestamp, id_produto uuid,
        titulo text, quantidade int, valor_total decimal, status text)""",
    # Compra, consulta 2: compras de um usuário, da mais nova para a mais antiga
    """CREATE TABLE IF NOT EXISTS compra_por_usuario (
        cpf text, data_compra timestamp, id_compra uuid, id_produto uuid,
        titulo text, quantidade int, valor_total decimal, status text,
        PRIMARY KEY ((cpf), data_compra, id_compra)
    ) WITH CLUSTERING ORDER BY (data_compra DESC, id_compra ASC)""",
]


# ============================================================================
# Camada de dados
# ============================================================================
def agora() -> datetime:
    return datetime.now(timezone.utc)


@cache
def _preparar(cql: str):
    """Prepared statements são preparados uma única vez e reaproveitados."""
    return cassandra_sessao().prepare(cql)


def _executar(cql: str, parametros: Sequence[Any] = ()):
    return cassandra_sessao().execute(_preparar(cql), parametros)


def criar_tabelas() -> None:
    for cql in DDL:
        cassandra_sessao().execute(cql)


def inserir_usuario(cpf: str, nome: str, sobrenome: str, email: str) -> bool:
    """``IF NOT EXISTS``: no Cassandra o INSERT é upsert; sem isso um CPF repetido sobrescreveria o usuário."""
    res = _executar(
        "INSERT INTO usuario (cpf, nome, sobrenome, email, criado_em, atualizado_em) VALUES (?, ?, ?, ?, ?, ?) IF NOT EXISTS",
        (cpf, nome, sobrenome, email, agora(), agora()),
    )
    return res.was_applied


def inserir_vendedor(cnpj: str, nome_loja: str) -> bool:
    res = _executar(
        "INSERT INTO vendedor (cnpj, nome_loja, avaliacao, status, criado_em) VALUES (?, ?, ?, ?, ?) IF NOT EXISTS",
        (cnpj, nome_loja, Decimal("0.00"), "ativo", agora()),
    )
    return res.was_applied


def inserir_produto(
    cnpj_vendedor: str, titulo: str, descricao: str, preco: Decimal, estoque: int, id_categoria: str,
    id_produto: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Grava o produto nas duas tabelas (por id e por categoria) no mesmo batch."""
    vendedor = _executar("SELECT status FROM vendedor WHERE cnpj = ?", (cnpj_vendedor,)).one()
    if vendedor is None or vendedor.status != "ativo":
        return None
    id_produto = id_produto or uuid.uuid4()
    batch = BatchStatement()
    batch.add(
        _preparar(
            "INSERT INTO produto (id_produto, titulo, descricao, preco, quantidade_disponivel, id_categoria, cnpj_vendedor, criado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        ),
        (id_produto, titulo, descricao, preco, estoque, id_categoria, cnpj_vendedor, agora()),
    )
    batch.add(
        _preparar("INSERT INTO produto_por_categoria (id_categoria, titulo, id_produto, preco, cnpj_vendedor) VALUES (?, ?, ?, ?, ?)"),
        (id_categoria, titulo, id_produto, preco, cnpj_vendedor),
    )
    cassandra_sessao().execute(batch)
    return id_produto


def inserir_compra(cpf: str, id_produto: uuid.UUID, quantidade: int) -> uuid.UUID | None:
    """Busca título e preço no produto, calcula o total e grava a compra nas duas tabelas."""
    if _executar("SELECT cpf FROM usuario WHERE cpf = ?", (cpf,)).one() is None:
        return None
    produto = _executar("SELECT titulo, preco FROM produto WHERE id_produto = ?", (id_produto,)).one()
    if produto is None:
        return None
    id_compra, data_compra = uuid.uuid4(), agora()
    total = (produto.preco * quantidade).quantize(Decimal("0.01"))
    valores = (id_produto, produto.titulo, quantidade, total, "pago")
    batch = BatchStatement()
    batch.add(
        _preparar("INSERT INTO compra (id_compra, cpf, data_compra, id_produto, titulo, quantidade, valor_total, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
        (id_compra, cpf, data_compra, *valores),
    )
    batch.add(
        _preparar("INSERT INTO compra_por_usuario (cpf, data_compra, id_compra, id_produto, titulo, quantidade, valor_total, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
        (cpf, data_compra, id_compra, *valores),
    )
    cassandra_sessao().execute(batch)
    return id_compra


def buscar_usuario(cpf: str):
    return _executar("SELECT cpf, nome, sobrenome, email, atualizado_em FROM usuario WHERE cpf = ?", (cpf,)).one()


def listar_usuarios():
    # Varredura limitada: aceitável para um cadastro pequeno/administrativo, não para uso em escala.
    return list(_executar(f"SELECT cpf, nome, sobrenome, email FROM usuario LIMIT {LIMITE_LISTAGEM}"))


def listar_vendedores():
    return list(_executar(f"SELECT cnpj, nome_loja, status FROM vendedor LIMIT {LIMITE_LISTAGEM}"))


def atualizar_usuario(cpf: str, nome: str | None = None, sobrenome: str | None = None, email: str | None = None) -> bool | None:
    """Altera só os campos informados. ``IF EXISTS``: UPDATE também é upsert, e um CPF errado criaria um usuário novo.

    Devolve ``None`` quando não há nada a alterar.
    """
    campos = {k: v for k, v in {"nome": nome, "sobrenome": sobrenome, "email": email}.items() if v is not None}
    if not campos:
        return None
    campos["atualizado_em"] = agora()
    sets = ", ".join(f"{coluna} = ?" for coluna in campos)  # nomes de coluna fixos acima; valores vão em "?"
    return _executar(f"UPDATE usuario SET {sets} WHERE cpf = ? IF EXISTS", (*campos.values(), cpf)).was_applied


def buscar_produto(id_produto: uuid.UUID):
    return _executar(
        "SELECT id_produto, titulo, descricao, preco, quantidade_disponivel, id_categoria, cnpj_vendedor FROM produto WHERE id_produto = ?",
        (id_produto,),
    ).one()


def listar_categorias() -> list[str]:
    return sorted(row.id_categoria for row in _executar("SELECT DISTINCT id_categoria FROM produto_por_categoria"))


def listar_produtos_categoria(id_categoria: str, prefixo: str | None = None):
    """Já vem ordenado por título (clustering key). Com prefixo usa faixa na clustering key:
    ``titulo >= 'Te' AND titulo < 'Tf'`` traz tudo que começa com 'Te' (diferencia maiúsculas)."""
    if prefixo:
        fim = prefixo[:-1] + chr(ord(prefixo[-1]) + 1)
        linhas = _executar(
            "SELECT id_produto, titulo, preco FROM produto_por_categoria WHERE id_categoria = ? AND titulo >= ? AND titulo < ?",
            (id_categoria, prefixo, fim),
        )
    else:
        linhas = _executar("SELECT id_produto, titulo, preco FROM produto_por_categoria WHERE id_categoria = ?", (id_categoria,))
    return list(linhas)


def consulta_sem_chave(titulo: str) -> str:
    """``titulo`` não é chave de partição: o Cassandra recusa a consulta, pois varreria o cluster inteiro."""
    try:
        _executar("SELECT * FROM produto WHERE titulo = ?", (titulo,))
    except InvalidRequest as exc:
        return str(exc)
    return "A consulta foi aceita (o servidor permitiu varredura)."


def listar_compras(cpf: str):
    """Ordenado pela clustering key: da mais nova para a mais antiga."""
    return list(
        _executar(
            "SELECT id_compra, data_compra, titulo, quantidade, valor_total, status FROM compra_por_usuario WHERE cpf = ?",
            (cpf,),
        )
    )


def excluir_compra(id_compra: uuid.UUID) -> bool:
    """DELETE precisa da chave completa: pela tabela ``compra`` acha-se cpf e data_compra,
    e a compra é apagada das duas tabelas no mesmo batch."""
    linha = _executar("SELECT cpf, data_compra FROM compra WHERE id_compra = ?", (id_compra,)).one()
    if linha is None:
        return False
    batch = BatchStatement()
    batch.add(_preparar("DELETE FROM compra_por_usuario WHERE cpf = ? AND data_compra = ? AND id_compra = ?"), (linha.cpf, linha.data_compra, id_compra))
    batch.add(_preparar("DELETE FROM compra WHERE id_compra = ?"), (id_compra,))
    cassandra_sessao().execute(batch)
    return True


def carregar_demonstracao() -> None:
    """Carrega o conjunto de exemplo (``dados_demo``). Idempotente: ids fixos evitam duplicar produtos."""
    criar_tabelas()
    for dados in dados_demo.USUARIOS:
        inserir_usuario(*dados)
    for cnpj, loja in dados_demo.LOJAS:
        inserir_vendedor(cnpj, loja)
    for p in dados_demo.PRODUTOS:
        inserir_produto(p.cnpj, p.titulo, p.descricao, p.preco, p.estoque, p.categoria, dados_demo.id_produto(p.chave))
    cpf_teste = dados_demo.USUARIOS[0][0]
    if not listar_compras(cpf_teste):  # compras de demonstração só na primeira carga
        for i_usuario, chave, qtd in dados_demo.COMPRAS:
            inserir_compra(dados_demo.USUARIOS[i_usuario][0], dados_demo.id_produto(chave), qtd)


# ============================================================================
# Interface
# ============================================================================
def _escolher_usuario():
    usuarios = listar_usuarios()
    if not usuarios:
        ui.aviso("Nenhum usuário cadastrado.")
        return None
    return ui.selecionar(
        "Selecione o usuário",
        [(f"{u.nome} {u.sobrenome}  |  CPF {formatar_cpf(u.cpf)}  |  {u.email}", u) for u in usuarios],
        filtro=True,
    )


def _escolher_vendedor():
    vendedores = [v for v in listar_vendedores() if v.status == "ativo"]
    if not vendedores:
        ui.aviso("Nenhum vendedor ativo cadastrado.")
        return None
    return ui.selecionar(
        "Selecione o vendedor",
        [(f"{v.nome_loja}  |  CNPJ {formatar_cnpj(v.cnpj)}", v) for v in vendedores],
        filtro=True,
    )


def _escolher_categoria() -> str | None:
    categorias = listar_categorias()
    if not categorias:
        ui.aviso("Nenhuma categoria cadastrada.")
        return None
    return ui.selecionar("Categoria", [(c, c) for c in categorias], filtro=True)


def _escolher_produto():
    if not (categoria := _escolher_categoria()):
        return None
    prefixo = ui.perguntar("Começa com (Enter para listar todos):", obrigatorio=False)
    produtos = listar_produtos_categoria(categoria, prefixo)
    if not produtos:
        ui.aviso("Nenhum produto encontrado.")
        return None
    return ui.selecionar(
        "Selecione o produto",
        [(f"{p.titulo}  |  {formatar_moeda(p.preco)}", p) for p in produtos],
        filtro=True,
    )


def acao_cadastrar_usuario() -> None:
    cpf = ui.perguntar("CPF:", validar_cpf)
    nome = normalizar(ui.perguntar("Nome:"))
    sobrenome = normalizar(ui.perguntar("Sobrenome:"))
    email = ui.perguntar("E-mail:", validar_email)
    if inserir_usuario(cpf, nome, sobrenome, email):
        ui.sucesso(f"Usuário {nome} {sobrenome} cadastrado.")
    else:
        ui.erro("Já existe um usuário com esse CPF.")


def acao_listar_usuarios() -> None:
    linhas = [(f"{u.nome} {u.sobrenome}", formatar_cpf(u.cpf), u.email) for u in listar_usuarios()]
    ui.tabela("Usuários", ["Nome", "CPF", "E-mail"], linhas, "Nenhum usuário cadastrado.")


def acao_atualizar_usuario() -> None:
    if not (usuario := _escolher_usuario()):
        return
    novos = {
        "nome": normalizar(ui.perguntar("Nome:", padrao=usuario.nome)),
        "sobrenome": normalizar(ui.perguntar("Sobrenome:", padrao=usuario.sobrenome)),
        "email": ui.perguntar("E-mail:", validar_email, padrao=usuario.email),
    }
    alteracoes = {k: v for k, v in novos.items() if v != getattr(usuario, k)}
    resultado = atualizar_usuario(usuario.cpf, **alteracoes)
    if resultado is None:
        ui.info("Nenhuma alteração informada.")
    elif resultado:
        ui.sucesso("Usuário atualizado.")
    else:
        ui.erro("Usuário não encontrado.")


def acao_cadastrar_vendedor() -> None:
    loja = normalizar(ui.perguntar("Nome da loja:"))
    cnpj = ui.perguntar("CNPJ:", validar_cnpj)
    if inserir_vendedor(cnpj, loja):
        ui.sucesso(f"Loja {loja} cadastrada.")
    else:
        ui.erro("Já existe um vendedor com esse CNPJ.")


def acao_cadastrar_produto() -> None:
    if not (vendedor := _escolher_vendedor()):
        return
    titulo = normalizar(ui.perguntar("Título:"))
    descricao = ui.perguntar("Descrição:")
    preco = ui.perguntar("Preço (R$):", converter_decimal)
    estoque = ui.perguntar("Quantidade em estoque:", converter_inteiro)
    categoria = ui.perguntar("Categoria (ex.: MLB1648):", sugestoes=listar_categorias()).upper()
    id_produto = inserir_produto(vendedor.cnpj, titulo, descricao, preco, estoque, categoria)
    if id_produto:
        ui.sucesso(f"Produto '{titulo}' cadastrado ({id_produto}).")
    else:
        ui.erro("Vendedor inexistente ou inativo. Produto não cadastrado.")


def acao_buscar_produtos() -> None:
    if not (categoria := _escolher_categoria()):
        return
    prefixo = ui.perguntar("Título começa com (Enter para todos):", obrigatorio=False)
    linhas = [(p.titulo, formatar_moeda(p.preco), str(p.id_produto)) for p in listar_produtos_categoria(categoria, prefixo)]
    ui.tabela(f"Produtos da categoria {categoria}", ["Título", ("Preço", "right"), "ID"], linhas)


def acao_detalhar_produto() -> None:
    if not (resumo := _escolher_produto()):
        return
    p = buscar_produto(resumo.id_produto)
    if p is None:
        ui.erro("Produto não encontrado.")
        return
    ui.console.print(
        ui.painel(
            p.titulo,
            f"{p.descricao}\n\nPreço: [bold]{formatar_moeda(p.preco)}[/]\nEstoque: {p.quantidade_disponivel}\n"
            f"Categoria: {p.id_categoria}\nVendedor: {formatar_cnpj(p.cnpj_vendedor)}\nID: {p.id_produto}",
        )
    )


def acao_registrar_compra() -> None:
    if not (usuario := _escolher_usuario()) or not (produto := _escolher_produto()):
        return
    quantidade = ui.perguntar("Quantidade:", lambda v: converter_inteiro(v, minimo=1))
    id_compra = inserir_compra(usuario.cpf, produto.id_produto, quantidade)
    if id_compra:
        ui.sucesso(f"Compra registrada: {produto.titulo} x{quantidade} = {formatar_moeda(produto.preco * quantidade)}")
    else:
        ui.erro("Usuário ou produto inexistente. Compra não registrada.")


def _tabela_compras(usuario) -> list:
    compras = listar_compras(usuario.cpf)
    linhas = [
        (formatar_data(c.data_compra), c.titulo, str(c.quantidade), formatar_moeda(c.valor_total), ui.status_texto(c.status))
        for c in compras
    ]
    ui.tabela(f"Compras de {usuario.nome}", ["Data", "Produto", ("Qtd", "right"), ("Total", "right"), "Status"], linhas, "Nenhuma compra encontrada.")
    return compras


def acao_listar_compras() -> None:
    if usuario := _escolher_usuario():
        _tabela_compras(usuario)


def acao_excluir_compra() -> None:
    if not (usuario := _escolher_usuario()):
        return
    compras = listar_compras(usuario.cpf)
    if not compras:
        ui.aviso("Nenhuma compra encontrada.")
        return
    compra = ui.selecionar(
        "Qual compra excluir?",
        [(f"{formatar_data(c.data_compra)}  |  {c.titulo} x{c.quantidade}  |  {formatar_moeda(c.valor_total)}", c) for c in compras],
    )
    if compra and ui.confirmar(f"Excluir a compra de '{compra.titulo}'?"):
        ui.sucesso("Compra excluída.") if excluir_compra(compra.id_compra) else ui.erro("Compra não encontrada.")


def acao_criar_tabelas() -> None:
    with ui.processando("Criando tabelas..."):
        criar_tabelas()
    ui.sucesso("Tabelas verificadas/criadas no keyspace.")


def acao_consulta_sem_chave() -> None:
    titulo = ui.perguntar("Título a buscar:", padrao="Teclado Mecanico")
    ui.info("Consultando a tabela produto filtrando por título (não é chave de partição)...")
    ui.console.print(ui.painel("Resposta do Cassandra", consulta_sem_chave(titulo), cor="red"))


def acao_dados_demonstracao() -> None:
    with ui.processando("Carregando dados de demonstração..."):
        carregar_demonstracao()
    ui.sucesso("Dados de demonstração carregados (2 usuários, 2 lojas, 4 produtos, 4 compras).")


# ============================================================================
# Menu
# ============================================================================
def main() -> None:
    try:
        with ui.processando("Conectando ao Cassandra (Astra DB)..."):
            sessao = cassandra_sessao()
    except Exception as exc:
        ui.erro(f"Falha ao conectar ao Cassandra: {exc}")
        return
    ui.sucesso(f"Conectado ao keyspace '{sessao.keyspace}'.")
    ui.apresentar("Cassandra", "banco de colunas largas", RESUMO)

    ui.menu(
        "HISTÓRICO DE COMPRAS (Cassandra)",
        [
            ("Preparar o keyspace (criar tabelas e dados de demonstração)", lambda: ui.menu("PREPARAÇÃO", [
                ("Criar tabelas", acao_criar_tabelas), ("Carregar dados de demonstração", acao_dados_demonstracao),
            ])),
            ("Usuários", lambda: ui.menu("USUÁRIOS", [
                ("Cadastrar", acao_cadastrar_usuario), ("Listar", acao_listar_usuarios), ("Atualizar", acao_atualizar_usuario),
            ])),
            ("Vendedores", lambda: ui.menu("VENDEDORES", [("Cadastrar", acao_cadastrar_vendedor)])),
            ("Produtos", lambda: ui.menu("PRODUTOS", [
                ("Cadastrar", acao_cadastrar_produto), ("Buscar por categoria", acao_buscar_produtos),
                ("Ver detalhes de um produto", acao_detalhar_produto),
                ("Testar consulta sem chave de partição", acao_consulta_sem_chave),
            ])),
            ("Compras", lambda: ui.menu("COMPRAS", [
                ("Registrar", acao_registrar_compra), ("Listar por usuário", acao_listar_compras), ("Excluir", acao_excluir_compra),
            ])),
        ],
        raiz=True,
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        fechar_conexoes()
