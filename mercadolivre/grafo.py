"""Usuários, vendedores, produtos e compras no Neo4j (AuraDB).

No Neo4j os relacionamentos são dados de primeira classe: em vez de guardar
``id_vendedor`` ou ``cpf`` dentro de outro registro, o grafo liga os nós por
arestas e as consultas percorrem essas ligações.

Nós (rótulo: chave única)::

    (:Usuario  {cpf, nome, sobrenome, email})
    (:Vendedor {cnpj, nome_loja, avaliacao, status})
    (:Categoria {id_categoria})
    (:Produto  {id_produto, titulo, descricao, preco, quantidade_disponivel})
    (:Compra   {id_compra, data_compra, titulo, quantidade, valor_total, status})

Relacionamentos::

    (Vendedor)-[:VENDE]->(Produto)-[:PERTENCE_A]->(Categoria)
    (Usuario)-[:REALIZOU]->(Compra)-[:DE_PRODUTO]->(Produto)

A primeira metade do módulo é a camada de dados (devolve dados, não imprime);
a segunda é a interface interativa.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from neo4j.exceptions import ConstraintError
from rich.markup import escape
from rich.tree import Tree

from . import dados_demo, ui
from .conexoes import fechar_conexoes, neo4j_banco, neo4j_driver
from .validadores import (
    converter_decimal,
    converter_inteiro,
    digitos,
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
    "Guarda NÓS (usuário, produto, compra...) e RELACIONAMENTOS entre eles (REALIZOU, DE_PRODUTO...).",
    "Aqui: quem comprou o quê e de qual loja. A ligação é um dado de verdade, não um id repetido.",
    "Consultar é 'caminhar' pelo grafo: Usuário -> Compra -> Produto -> Loja (veja 'Explorar o grafo').",
    "A linguagem de consulta é o Cypher: MATCH (u)-[:REALIZOU]->(c) RETURN c.",
]

# Restrições de unicidade (criam índice automaticamente) e índices de busca.
SCHEMA = [
    "CREATE CONSTRAINT usuario_cpf IF NOT EXISTS FOR (u:Usuario) REQUIRE u.cpf IS UNIQUE",
    "CREATE CONSTRAINT vendedor_cnpj IF NOT EXISTS FOR (v:Vendedor) REQUIRE v.cnpj IS UNIQUE",
    "CREATE CONSTRAINT vendedor_loja IF NOT EXISTS FOR (v:Vendedor) REQUIRE v.nome_loja IS UNIQUE",
    "CREATE CONSTRAINT categoria_id IF NOT EXISTS FOR (c:Categoria) REQUIRE c.id_categoria IS UNIQUE",
    "CREATE CONSTRAINT produto_id IF NOT EXISTS FOR (p:Produto) REQUIRE p.id_produto IS UNIQUE",
    "CREATE CONSTRAINT compra_id IF NOT EXISTS FOR (c:Compra) REQUIRE c.id_compra IS UNIQUE",
    "CREATE INDEX usuario_nome IF NOT EXISTS FOR (u:Usuario) ON (u.nome)",
    "CREATE INDEX produto_titulo IF NOT EXISTS FOR (p:Produto) ON (p.titulo)",
]

# A cláusula ORDER BY não aceita parâmetro: só entram aqui expressões fixas do código.
ORDENACOES = {
    "titulo": ("Título (A-Z)", "p.titulo ASC"),
    "menor_preco": ("Menor preço", "p.preco ASC, p.titulo ASC"),
    "maior_preco": ("Maior preço", "p.preco DESC, p.titulo ASC"),
    "maior_estoque": ("Maior estoque", "p.quantidade_disponivel DESC, p.titulo ASC"),
}


# ============================================================================
# Camada de dados
# ============================================================================
def agora() -> datetime:
    return datetime.now(timezone.utc)


def _executar(cypher: str, parametros: dict[str, Any] | None = None):
    """Executa uma consulta parametrizada em transação gerenciada pelo driver (com retentativas)."""
    return neo4j_driver().execute_query(cypher, parametros or {}, database_=neo4j_banco())


def _decimal(valor: Any) -> Decimal:
    """O Neo4j guarda ``float``; na saída voltamos a ``Decimal`` com duas casas."""
    return Decimal(str(valor)).quantize(Decimal("0.01"))


def _nativo(valor: Any) -> Any:
    """Converte tipos do driver (``neo4j.time.DateTime``) em ``datetime`` e preços em ``Decimal``."""
    if hasattr(valor, "to_native"):
        return valor.to_native()
    if isinstance(valor, dict):
        return {
            k: _decimal(v) if k in ("preco", "valor_total") and v is not None else _nativo(v)
            for k, v in valor.items()
        }
    return valor


def _linhas(cypher: str, parametros: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [_nativo(registro.data()) for registro in _executar(cypher, parametros).records]


def _uma(cypher: str, parametros: dict[str, Any] | None = None) -> dict[str, Any] | None:
    linhas = _linhas(cypher, parametros)
    return linhas[0] if linhas else None


def _criou_no(resultado) -> bool:
    return resultado.summary.counters.nodes_created > 0


def _termo(texto: str | None) -> str | None:
    texto = normalizar(texto or "")
    return texto.lower() or None


def criar_schema() -> None:
    """Cria restrições e índices (idempotente)."""
    for cypher in SCHEMA:
        _executar(cypher)


# ----------------------------------------------------------------------------
# Insert
# ----------------------------------------------------------------------------
def inserir_usuario(cpf: str, nome: str, sobrenome: str, email: str) -> bool:
    """``MERGE`` pela chave: CPF repetido não duplica nem sobrescreve. Devolve ``False`` se já existia."""
    res = _executar(
        "MERGE (u:Usuario {cpf: $cpf}) "
        "ON CREATE SET u.nome = $nome, u.sobrenome = $sobrenome, u.email = $email, "
        "u.criado_em = $agora, u.atualizado_em = $agora",
        {"cpf": cpf, "nome": nome, "sobrenome": sobrenome, "email": email, "agora": agora()},
    )
    return _criou_no(res)


def inserir_vendedor(cnpj: str, nome_loja: str) -> bool:
    """Devolve ``False`` se o CNPJ ou o nome da loja já estiverem em uso."""
    try:
        res = _executar(
            "MERGE (v:Vendedor {cnpj: $cnpj}) "
            "ON CREATE SET v.nome_loja = $nome_loja, v.avaliacao = 0.0, v.status = 'ativo', v.criado_em = $agora",
            {"cnpj": cnpj, "nome_loja": nome_loja, "agora": agora()},
        )
    except ConstraintError:  # nome da loja já pertence a outro CNPJ
        return False
    return _criou_no(res)


def inserir_produto(
    cnpj_vendedor: str, titulo: str, descricao: str, preco: Decimal, estoque: int, id_categoria: str,
    id_produto: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Cria o produto e liga ao vendedor (``VENDE``) e à categoria (``PERTENCE_A``) na mesma transação.

    Devolve ``None`` se o vendedor não existir ou não estiver ativo.
    """
    id_produto = id_produto or uuid.uuid4()
    linha = _uma(
        "MATCH (v:Vendedor {cnpj: $cnpj, status: 'ativo'}) "
        "MERGE (c:Categoria {id_categoria: $categoria}) "
        "MERGE (p:Produto {id_produto: $id_produto}) "
        "ON CREATE SET p.titulo = $titulo, p.descricao = $descricao, p.preco = $preco, "
        "p.quantidade_disponivel = $estoque, p.criado_em = $agora "
        "MERGE (v)-[:VENDE]->(p) "
        "MERGE (p)-[:PERTENCE_A]->(c) "
        "RETURN p.id_produto AS id_produto",
        {
            "cnpj": cnpj_vendedor, "categoria": id_categoria, "id_produto": str(id_produto), "titulo": titulo,
            "descricao": descricao, "preco": float(preco), "estoque": estoque, "agora": agora(),
        },
    )
    return uuid.UUID(linha["id_produto"]) if linha else None


def inserir_compra(cpf: str, id_produto: uuid.UUID, quantidade: int) -> uuid.UUID | None:
    """Registra a compra: ``(Usuario)-[:REALIZOU]->(Compra)-[:DE_PRODUTO]->(Produto)``.

    Título e preço são copiados do produto no momento da compra (histórico imutável) e o
    estoque é baixado na mesma transação. Devolve ``None`` se usuário ou produto não
    existirem e levanta ``ValueError`` se o estoque for insuficiente.
    """
    if buscar_usuario(cpf) is None:
        return None
    produto = buscar_produto(id_produto)
    if produto is None:
        return None
    id_compra = uuid.uuid4()
    total = (produto["preco"] * quantidade).quantize(Decimal("0.01"))
    linha = _uma(
        # O SET inicial toma o bloqueio de escrita do produto antes de conferir o saldo,
        # então duas compras simultâneas do mesmo produto não leem o mesmo estoque.
        "MATCH (p:Produto {id_produto: $id_produto}) "
        "SET p.quantidade_disponivel = p.quantidade_disponivel "
        "WITH p "
        "MATCH (u:Usuario {cpf: $cpf}) "
        "WHERE p.quantidade_disponivel >= $quantidade "
        "SET p.quantidade_disponivel = p.quantidade_disponivel - $quantidade "
        "CREATE (c:Compra {id_compra: $id_compra, data_compra: $agora, titulo: p.titulo, "
        "quantidade: $quantidade, valor_total: $total, status: 'pago'}) "
        "CREATE (u)-[:REALIZOU]->(c) "
        "CREATE (c)-[:DE_PRODUTO]->(p) "
        "RETURN c.id_compra AS id_compra",
        {
            "id_produto": str(id_produto), "cpf": cpf, "quantidade": quantidade,
            "id_compra": str(id_compra), "agora": agora(), "total": float(total),
        },
    )
    if linha is None:
        raise ValueError("Estoque insuficiente para essa quantidade.")
    return id_compra


# ----------------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------------
def buscar_usuario(cpf: str) -> dict[str, Any] | None:
    return _uma(
        "MATCH (u:Usuario {cpf: $cpf}) "
        "RETURN u.cpf AS cpf, u.nome AS nome, u.sobrenome AS sobrenome, u.email AS email, "
        "u.criado_em AS criado_em, u.atualizado_em AS atualizado_em",
        {"cpf": cpf},
    )


def buscar_usuarios(termo: str | None = None, limite: int = LIMITE_LISTAGEM) -> list[dict[str, Any]]:
    """Busca por trecho do nome completo, do e-mail ou do CPF. Sem termo, lista todos."""
    return _linhas(
        "MATCH (u:Usuario) "
        "WHERE $termo IS NULL OR toLower(u.nome + ' ' + u.sobrenome) CONTAINS $termo "
        "OR toLower(u.email) CONTAINS $termo OR ($digitos <> '' AND u.cpf CONTAINS $digitos) "
        "RETURN u.cpf AS cpf, u.nome AS nome, u.sobrenome AS sobrenome, u.email AS email "
        "ORDER BY u.nome, u.sobrenome LIMIT $limite",
        {"termo": _termo(termo), "digitos": digitos(termo or ""), "limite": limite},
    )


def buscar_vendedor(cnpj: str) -> dict[str, Any] | None:
    return _uma(
        "MATCH (v:Vendedor {cnpj: $cnpj}) "
        "OPTIONAL MATCH (v)-[:VENDE]->(p:Produto) "
        "RETURN v.cnpj AS cnpj, v.nome_loja AS nome_loja, v.avaliacao AS avaliacao, v.status AS status, "
        "v.criado_em AS criado_em, count(p) AS total_produtos",
        {"cnpj": cnpj},
    )


def buscar_vendedores(termo: str | None = None, limite: int = LIMITE_LISTAGEM) -> list[dict[str, Any]]:
    """Busca por trecho do nome da loja ou do CNPJ. Sem termo, lista todos."""
    return _linhas(
        "MATCH (v:Vendedor) "
        "WHERE $termo IS NULL OR toLower(v.nome_loja) CONTAINS $termo "
        "OR ($digitos <> '' AND v.cnpj CONTAINS $digitos) "
        "OPTIONAL MATCH (v)-[:VENDE]->(p:Produto) "
        "RETURN v.cnpj AS cnpj, v.nome_loja AS nome_loja, v.status AS status, count(p) AS total_produtos "
        "ORDER BY v.nome_loja LIMIT $limite",
        {"termo": _termo(termo), "digitos": digitos(termo or ""), "limite": limite},
    )


def buscar_produto(id_produto: uuid.UUID | str) -> dict[str, Any] | None:
    return _uma(
        "MATCH (p:Produto {id_produto: $id_produto}) "
        "OPTIONAL MATCH (v:Vendedor)-[:VENDE]->(p) "
        "OPTIONAL MATCH (p)-[:PERTENCE_A]->(c:Categoria) "
        "RETURN p.id_produto AS id_produto, p.titulo AS titulo, p.descricao AS descricao, p.preco AS preco, "
        "p.quantidade_disponivel AS quantidade_disponivel, c.id_categoria AS id_categoria, "
        "v.cnpj AS cnpj_vendedor, v.nome_loja AS nome_loja",
        {"id_produto": str(id_produto)},
    )


def listar_categorias() -> list[str]:
    return [linha["id_categoria"] for linha in _linhas("MATCH (c:Categoria) RETURN c.id_categoria AS id_categoria ORDER BY id_categoria")]


def buscar_produtos(
    termo: str | None = None, id_categoria: str | None = None, cnpj_vendedor: str | None = None,
    ordenar: str = "titulo", limite: int = LIMITE_LISTAGEM,
) -> list[dict[str, Any]]:
    """Filtros opcionais e combináveis: trecho do título, categoria e vendedor."""
    ordem = ORDENACOES.get(ordenar, ORDENACOES["titulo"])[1]
    return _linhas(
        "MATCH (v:Vendedor)-[:VENDE]->(p:Produto)-[:PERTENCE_A]->(c:Categoria) "
        "WHERE ($termo IS NULL OR toLower(p.titulo) CONTAINS $termo) "
        "AND ($categoria IS NULL OR c.id_categoria = $categoria) "
        "AND ($cnpj IS NULL OR v.cnpj = $cnpj) "
        "RETURN p.id_produto AS id_produto, p.titulo AS titulo, p.preco AS preco, "
        "p.quantidade_disponivel AS quantidade_disponivel, c.id_categoria AS id_categoria, "
        f"v.cnpj AS cnpj_vendedor, v.nome_loja AS nome_loja ORDER BY {ordem} LIMIT $limite",
        {"termo": _termo(termo), "categoria": id_categoria, "cnpj": cnpj_vendedor, "limite": limite},
    )


def buscar_compra(id_compra: uuid.UUID | str) -> dict[str, Any] | None:
    """Percorre o grafo nos dois sentidos: quem comprou, o quê e de qual loja."""
    return _uma(
        "MATCH (u:Usuario)-[:REALIZOU]->(c:Compra {id_compra: $id_compra})-[:DE_PRODUTO]->(p:Produto) "
        "OPTIONAL MATCH (v:Vendedor)-[:VENDE]->(p) "
        "RETURN c.id_compra AS id_compra, c.data_compra AS data_compra, c.titulo AS titulo, "
        "c.quantidade AS quantidade, c.valor_total AS valor_total, c.status AS status, "
        "u.cpf AS cpf, u.nome AS nome_usuario, p.id_produto AS id_produto, v.nome_loja AS nome_loja",
        {"id_compra": str(id_compra)},
    )


def buscar_compras(cpf: str | None = None, id_produto: uuid.UUID | str | None = None, limite: int = LIMITE_LISTAGEM) -> list[dict[str, Any]]:
    """Compras de um usuário, de um produto ou todas, da mais nova para a mais antiga."""
    return _linhas(
        "MATCH (u:Usuario)-[:REALIZOU]->(c:Compra)-[:DE_PRODUTO]->(p:Produto) "
        "WHERE ($cpf IS NULL OR u.cpf = $cpf) AND ($id_produto IS NULL OR p.id_produto = $id_produto) "
        "OPTIONAL MATCH (v:Vendedor)-[:VENDE]->(p) "
        "RETURN c.id_compra AS id_compra, c.data_compra AS data_compra, c.titulo AS titulo, "
        "c.quantidade AS quantidade, c.valor_total AS valor_total, c.status AS status, "
        "u.cpf AS cpf, u.nome AS nome_usuario, v.nome_loja AS nome_loja "
        "ORDER BY c.data_compra DESC LIMIT $limite",
        {"cpf": cpf, "id_produto": str(id_produto) if id_produto else None, "limite": limite},
    )


def resumo_do_grafo() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Quantidade de nós por rótulo e de relacionamentos por tipo."""
    nos = _linhas("MATCH (n) RETURN labels(n)[0] AS nome, count(*) AS total ORDER BY nome")
    relacoes = _linhas("MATCH ()-[r]->() RETURN type(r) AS nome, count(*) AS total ORDER BY nome")
    return nos, relacoes


def subgrafo(cpf: str | None = None, com_pessoas: bool = True, limite: int = 150) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Nós e arestas reais do grafo, prontos para desenhar (somente leitura).

    ``cpf`` limita o desenho às compras daquele usuário. Com ``com_pessoas=False`` o
    resultado exclui ``Usuario`` e ``Compra`` (apenas Loja -> Produto -> Categoria), para
    exibição pública sem dados pessoais. Cada nó traz ``id`` (interno), ``rotulo`` (tipo),
    ``nome`` (texto curto) e ``propriedades`` (sem CPF/e-mail quando ``com_pessoas=False``).
    """
    if com_pessoas:
        consulta = (
            "MATCH (a)-[r]->(b) "
            "WHERE ($cpf IS NULL OR (a:Usuario AND a.cpf = $cpf) "
            "OR (a:Compra AND EXISTS { (:Usuario {cpf: $cpf})-[:REALIZOU]->(a) }) "
            "OR (a:Produto AND EXISTS { (:Usuario {cpf: $cpf})-[:REALIZOU]->(:Compra)-[:DE_PRODUTO]->(a) }) "
            "OR (a:Vendedor AND EXISTS { (a)-[:VENDE]->(:Produto)<-[:DE_PRODUTO]-(:Compra)<-[:REALIZOU]-(:Usuario {cpf: $cpf}) })) "
            "RETURN elementId(a) AS ida, labels(a)[0] AS rotulo_a, properties(a) AS prop_a, "
            "type(r) AS relacao, elementId(b) AS idb, labels(b)[0] AS rotulo_b, properties(b) AS prop_b LIMIT $limite"
        )
    else:
        consulta = (
            "MATCH (a)-[r]->(b) WHERE type(r) IN ['VENDE', 'PERTENCE_A'] "
            "RETURN elementId(a) AS ida, labels(a)[0] AS rotulo_a, properties(a) AS prop_a, "
            "type(r) AS relacao, elementId(b) AS idb, labels(b)[0] AS rotulo_b, properties(b) AS prop_b LIMIT $limite"
        )
    linhas = _linhas(consulta, {"cpf": cpf, "limite": limite})
    nos: dict[str, dict[str, Any]] = {}
    arestas: list[dict[str, Any]] = []
    for l in linhas:
        for chave in ("a", "b"):
            id_no = l[f"id{chave}"]
            if id_no not in nos:
                nos[id_no] = _descrever_no(id_no, l[f"rotulo_{chave}"], l[f"prop_{chave}"], com_pessoas)
        arestas.append({"origem": l["ida"], "destino": l["idb"], "tipo": l["relacao"]})
    return list(nos.values()), arestas


def _descrever_no(id_no: str, rotulo: str, prop: dict[str, Any], com_pessoas: bool) -> dict[str, Any]:
    nome = {
        "Usuario": f"{prop.get('nome', '')} {prop.get('sobrenome', '')}".strip(),
        "Vendedor": prop.get("nome_loja"),
        "Produto": prop.get("titulo"),
        "Categoria": prop.get("id_categoria"),
        "Compra": f"{prop.get('quantidade', '?')}x {prop.get('titulo', '')}".strip(),
    }.get(rotulo) or rotulo
    ocultas = {"cpf", "email"} if not com_pessoas else set()
    propriedades = {k: v for k, v in prop.items() if k not in ocultas and v is not None}
    return {"id": id_no, "rotulo": rotulo, "nome": nome, "propriedades": propriedades}


def carregar_demonstracao() -> None:
    """Carrega o conjunto de exemplo (``dados_demo``). Idempotente: MERGE + ids fixos evitam duplicar nós."""
    criar_schema()
    for dados in dados_demo.USUARIOS:
        inserir_usuario(*dados)
    for cnpj, loja in dados_demo.LOJAS:
        inserir_vendedor(cnpj, loja)
    for p in dados_demo.PRODUTOS:
        inserir_produto(p.cnpj, p.titulo, p.descricao, p.preco, p.estoque, p.categoria, dados_demo.id_produto(p.chave))
    if not buscar_compras(cpf=dados_demo.USUARIOS[0][0]):  # compras de demonstração só na primeira carga
        for i_usuario, chave, qtd in dados_demo.COMPRAS:
            inserir_compra(dados_demo.USUARIOS[i_usuario][0], dados_demo.id_produto(chave), qtd)


# ============================================================================
# Interface
# ============================================================================
def _escolher_usuario() -> dict[str, Any] | None:
    usuarios = buscar_usuarios()
    if not usuarios:
        ui.aviso("Nenhum usuário cadastrado.")
        return None
    return ui.selecionar(
        "Selecione o usuário",
        [(f"{u['nome']} {u['sobrenome']}  |  CPF {formatar_cpf(u['cpf'])}  |  {u['email']}", u) for u in usuarios],
        filtro=True,
    )


def _escolher_vendedor(somente_ativos: bool = False) -> dict[str, Any] | None:
    vendedores = [v for v in buscar_vendedores() if not somente_ativos or v["status"] == "ativo"]
    if not vendedores:
        ui.aviso("Nenhum vendedor disponível.")
        return None
    return ui.selecionar(
        "Selecione o vendedor",
        [(f"{v['nome_loja']}  |  CNPJ {formatar_cnpj(v['cnpj'])}  |  {v['total_produtos']} produto(s)", v) for v in vendedores],
        filtro=True,
    )


def _escolher_produto(**filtros: Any) -> dict[str, Any] | None:
    produtos = buscar_produtos(**filtros)
    if not produtos:
        ui.aviso("Nenhum produto encontrado.")
        return None
    return ui.selecionar(
        "Selecione o produto",
        [(f"{p['titulo']}  |  {formatar_moeda(p['preco'])}  |  estoque {p['quantidade_disponivel']}  |  {p['nome_loja']}", p) for p in produtos],
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


def acao_buscar_usuarios() -> None:
    termo = ui.perguntar("Nome, e-mail ou CPF contém (Enter para todos):", obrigatorio=False)
    linhas = [(f"{u['nome']} {u['sobrenome']}", formatar_cpf(u["cpf"]), u["email"]) for u in buscar_usuarios(termo)]
    ui.tabela("Usuários", ["Nome", "CPF", "E-mail"], linhas)


def acao_cadastrar_vendedor() -> None:
    loja = normalizar(ui.perguntar("Nome da loja:"))
    cnpj = ui.perguntar("CNPJ:", validar_cnpj)
    if inserir_vendedor(cnpj, loja):
        ui.sucesso(f"Loja {loja} cadastrada.")
    else:
        ui.erro("Já existe um vendedor com esse CNPJ ou nome de loja.")


def acao_buscar_vendedores() -> None:
    termo = ui.perguntar("Nome da loja ou CNPJ contém (Enter para todos):", obrigatorio=False)
    linhas = [
        (v["nome_loja"], formatar_cnpj(v["cnpj"]), ui.status_texto(v["status"]), str(v["total_produtos"]))
        for v in buscar_vendedores(termo)
    ]
    ui.tabela("Vendedores", ["Loja", "CNPJ", "Status", ("Produtos", "right")], linhas)


def acao_cadastrar_produto() -> None:
    if not (vendedor := _escolher_vendedor(somente_ativos=True)):
        return
    titulo = normalizar(ui.perguntar("Título:"))
    descricao = ui.perguntar("Descrição:")
    preco = ui.perguntar("Preço (R$):", converter_decimal)
    estoque = ui.perguntar("Quantidade em estoque:", converter_inteiro)
    categoria = ui.perguntar("Categoria (ex.: MLB1648):", sugestoes=listar_categorias()).upper()
    id_produto = inserir_produto(vendedor["cnpj"], titulo, descricao, preco, estoque, categoria)
    if id_produto:
        ui.sucesso(f"Produto '{titulo}' cadastrado ({id_produto}).")
    else:
        ui.erro("Vendedor inexistente ou inativo. Produto não cadastrado.")


def acao_buscar_produtos() -> None:
    termo = ui.perguntar("Título contém (Enter para todos):", obrigatorio=False)
    categorias = listar_categorias()
    categoria = ui.selecionar("Filtrar por categoria?", [(c, c) for c in categorias], voltar="Todas as categorias", filtro=True) if categorias else None
    ordenar = ui.selecionar("Ordenar por", [(nome, chave) for chave, (nome, _) in ORDENACOES.items()], voltar=None)
    produtos = buscar_produtos(termo, categoria, ordenar=ordenar)
    linhas = [
        (p["titulo"], formatar_moeda(p["preco"]), str(p["quantidade_disponivel"]), p["id_categoria"], p["nome_loja"])
        for p in produtos
    ]
    ui.tabela("Produtos", ["Título", ("Preço", "right"), ("Estoque", "right"), "Categoria", "Loja"], linhas)


def acao_detalhar_produto() -> None:
    if not (resumo := _escolher_produto()):
        return
    p = buscar_produto(resumo["id_produto"])
    if p is None:
        ui.erro("Produto não encontrado.")
        return
    ui.console.print(
        ui.painel(
            p["titulo"],
            f"{escape(p['descricao'] or '')}\n\nPreço: [bold]{formatar_moeda(p['preco'])}[/]\n"
            f"Estoque: {p['quantidade_disponivel']}\nCategoria: {escape(p['id_categoria'] or '-')}\n"
            f"Loja: {escape(p['nome_loja'] or '-')} ({formatar_cnpj(p['cnpj_vendedor'] or '')})\nID: {p['id_produto']}",
        )
    )


def acao_registrar_compra() -> None:
    if not (usuario := _escolher_usuario()) or not (produto := _escolher_produto()):
        return
    quantidade = ui.perguntar("Quantidade:", lambda v: converter_inteiro(v, minimo=1))
    try:
        id_compra = inserir_compra(usuario["cpf"], uuid.UUID(produto["id_produto"]), quantidade)
    except ValueError as exc:
        ui.erro(str(exc))
        return
    if id_compra:
        ui.sucesso(f"Compra registrada: {produto['titulo']} x{quantidade} = {formatar_moeda(produto['preco'] * quantidade)}")
    else:
        ui.erro("Usuário ou produto inexistente. Compra não registrada.")


def _tabela_compras(titulo_tabela: str, compras: list[dict[str, Any]]) -> None:
    linhas = [
        (formatar_data(c["data_compra"]), c["nome_usuario"], c["titulo"], str(c["quantidade"]),
         formatar_moeda(c["valor_total"]), c["nome_loja"] or "-", ui.status_texto(c["status"]))
        for c in compras
    ]
    ui.tabela(titulo_tabela, ["Data", "Comprador", "Produto", ("Qtd", "right"), ("Total", "right"), "Loja", "Status"], linhas, "Nenhuma compra encontrada.")


def acao_buscar_compras() -> None:
    origem = ui.selecionar(
        "Buscar compras de...",
        [("Todas", "todas"), ("Um usuário", "usuario"), ("Um produto", "produto")],
        voltar=None,
    )
    if origem == "usuario":
        if not (usuario := _escolher_usuario()):
            return
        _tabela_compras(f"Compras de {usuario['nome']}", buscar_compras(cpf=usuario["cpf"]))
    elif origem == "produto":
        if not (produto := _escolher_produto()):
            return
        _tabela_compras(f"Compras de {produto['titulo']}", buscar_compras(id_produto=produto["id_produto"]))
    else:
        _tabela_compras("Todas as compras", buscar_compras())


def acao_detalhar_compra() -> None:
    if not (usuario := _escolher_usuario()):
        return
    compras = buscar_compras(cpf=usuario["cpf"])
    if not compras:
        ui.aviso("Nenhuma compra encontrada.")
        return
    escolhida = ui.selecionar(
        "Qual compra?",
        [(f"{formatar_data(c['data_compra'])}  |  {c['titulo']} x{c['quantidade']}  |  {formatar_moeda(c['valor_total'])}", c) for c in compras],
    )
    if not escolhida:
        return
    c = buscar_compra(escolhida["id_compra"])
    if c is None:
        ui.erro("Compra não encontrada.")
        return
    ui.console.print(
        ui.painel(
            f"Compra {c['id_compra']}",
            f"Comprador: {escape(c['nome_usuario'])} ({formatar_cpf(c['cpf'])})\nProduto: {escape(c['titulo'])}\n"
            f"Loja: {escape(c['nome_loja'] or '-')}\nQuantidade: {c['quantidade']}\n"
            f"Total: [bold]{formatar_moeda(c['valor_total'])}[/]\nData: {formatar_data(c['data_compra'])}\nStatus: {escape(c['status'])}",
        )
    )


def acao_arvore_usuario() -> None:
    """Desenha o caminho Usuário -> Compra -> Produto -> Loja como árvore."""
    if not (usuario := _escolher_usuario()):
        return
    arvore = Tree(f"[bold yellow]{escape(usuario['nome'])} {escape(usuario['sobrenome'])}[/]  [dim]{formatar_cpf(usuario['cpf'])}[/]")
    compras = buscar_compras(cpf=usuario["cpf"])
    if not compras:
        arvore.add("[dim]nenhuma compra[/]")
    for c in compras:
        no = arvore.add(f"[cyan]REALIZOU[/] compra de {formatar_data(c['data_compra'])}  [green]{formatar_moeda(c['valor_total'])}[/]")
        produto = no.add(f"[cyan]DE_PRODUTO[/] {escape(c['titulo'])} x{c['quantidade']}")
        produto.add(f"[cyan]VENDIDO POR[/] {escape(c['nome_loja'] or '-')}")
    ui.console.print(arvore)


def acao_compradores_produto() -> None:
    if not (produto := _escolher_produto()):
        return
    compras = buscar_compras(id_produto=produto["id_produto"])
    por_comprador: dict[str, list[dict[str, Any]]] = {}
    for c in compras:
        por_comprador.setdefault(f"{c['nome_usuario']} ({formatar_cpf(c['cpf'])})", []).append(c)
    arvore = Tree(f"[bold yellow]{escape(produto['titulo'])}[/]  [dim]{escape(produto['nome_loja'])}[/]")
    if not por_comprador:
        arvore.add("[dim]ninguém comprou ainda[/]")
    for comprador, itens in por_comprador.items():
        no = arvore.add(f"[cyan]COMPRADO POR[/] {escape(comprador)}")
        for c in itens:
            no.add(f"{formatar_data(c['data_compra'])}  x{c['quantidade']}  {formatar_moeda(c['valor_total'])}")
    ui.console.print(arvore)


def acao_resumo() -> None:
    with ui.processando("Contando nós e relacionamentos..."):
        nos, relacoes = resumo_do_grafo()
    maior = max([n["total"] for n in nos + relacoes] or [1])
    for titulo_tabela, itens in (("Nós por rótulo", nos), ("Relacionamentos por tipo", relacoes)):
        ui.tabela(titulo_tabela, ["Nome", ("Total", "right"), "Proporção"], [(i["nome"], str(i["total"]), ui.barra(i["total"], maior)) for i in itens], "Grafo vazio.")


def acao_criar_schema() -> None:
    with ui.processando("Criando restrições e índices..."):
        criar_schema()
    ui.sucesso("Restrições e índices verificados/criados.")


def acao_dados_demonstracao() -> None:
    with ui.processando("Carregando dados de demonstração..."):
        carregar_demonstracao()
    ui.sucesso("Dados de demonstração carregados (2 usuários, 2 lojas, 4 produtos, 4 compras).")


# ============================================================================
# Menu
# ============================================================================
def main() -> None:
    try:
        with ui.processando("Conectando ao Neo4j (AuraDB)..."):
            neo4j_driver().verify_connectivity()
    except Exception as exc:
        ui.erro(f"Falha ao conectar ao Neo4j: {exc}")
        return
    ui.sucesso(f"Conectado ao banco '{neo4j_banco()}'.")
    ui.apresentar("Neo4j", "banco de grafos", RESUMO)

    ui.menu(
        "GRAFO DE COMPRAS (Neo4j)",
        [
            ("Preparar o banco (restrições, índices e dados de demonstração)", lambda: ui.menu("PREPARAÇÃO", [
                ("Criar restrições e índices", acao_criar_schema), ("Carregar dados de demonstração", acao_dados_demonstracao),
            ])),
            ("Usuários", lambda: ui.menu("USUÁRIOS", [
                ("Cadastrar", acao_cadastrar_usuario), ("Buscar", acao_buscar_usuarios),
            ])),
            ("Vendedores", lambda: ui.menu("VENDEDORES", [
                ("Cadastrar", acao_cadastrar_vendedor), ("Buscar", acao_buscar_vendedores),
            ])),
            ("Produtos", lambda: ui.menu("PRODUTOS", [
                ("Cadastrar", acao_cadastrar_produto), ("Buscar", acao_buscar_produtos),
                ("Ver detalhes de um produto", acao_detalhar_produto),
            ])),
            ("Compras", lambda: ui.menu("COMPRAS", [
                ("Registrar", acao_registrar_compra), ("Buscar", acao_buscar_compras),
                ("Ver detalhes de uma compra", acao_detalhar_compra),
            ])),
            ("Explorar o grafo", lambda: ui.menu("EXPLORAR O GRAFO", [
                ("Compras de um usuário (árvore)", acao_arvore_usuario),
                ("Quem comprou um produto (árvore)", acao_compradores_produto),
                ("Resumo: nós e relacionamentos", acao_resumo),
            ])),
        ],
        raiz=True,
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        fechar_conexoes()
