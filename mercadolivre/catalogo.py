"""Catálogo, vendedores, favoritos e pedidos no MongoDB (menu interativo).

Coleções: ``usuarios``, ``vendedores``, ``produtos`` e ``pedidos``. Endereços e favoritos moram
DENTRO do documento do usuário. Relacionamentos por referência (``id_vendedor``, ``id_comprador``, ``id_produto``),
consultados com ``$lookup``. Valores monetários usam ``Decimal128``.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import requests
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError
from rich.columns import Columns
from rich.table import Table

from . import ui
from .catalogo_dados import (  # noqa: F401 - reexportados: a CLI e os testes usam estes nomes
    LIMITE_ESTOQUE_BAIXO,
    ORDENACOES,
    ErroNegocio,
    agora_utc,
    carregar_demonstracao as _carregar_demonstracao,
    colecao,
    configurar_banco_dados,
    produtos_com_vendedor as _produtos_com_vendedor,
    valor_em_estoque,
)
from . import catalogo_dados as dados
from .conexoes import fechar_conexoes, mongo_db
from .validadores import (
    converter_decimal,
    converter_inteiro,
    formatar_cep,
    formatar_cnpj,
    formatar_cpf,
    formatar_data,
    formatar_moeda,
    validar_cep,
    validar_cnpj,
    validar_cpf,
    validar_email,
)

RESUMO = [
    "Guarda DOCUMENTOS (parecidos com JSON) dentro de coleções, sem esquema fixo.",
    "Aqui: catálogo e pedidos. Um usuário guarda seus endereços e favoritos DENTRO do próprio documento.",
    "Relacionamentos por referência (id_vendedor) e consulta com $lookup, o 'JOIN' do MongoDB.",
    "A baixa de estoque é atômica: update_one só decrementa se ainda houver saldo.",
]

PASTA_EXPORTACOES = Path("exportacoes")



# ============================================================================
# Acesso ao banco
# ============================================================================
def carregar_demonstracao() -> None:
    with ui.processando("Carregando dados de demonstração..."):
        _carregar_demonstracao()
    ui.sucesso("Dados de demonstração carregados (2 usuários, 2 lojas, 4 produtos).")


# ============================================================================
# Seleção interativa (evita digitar CPF/ObjectId na mão)
# ============================================================================
def selecionar_usuario() -> dict[str, Any] | None:
    usuarios = list(colecao("usuarios").find().sort("nome", ASCENDING))
    if not usuarios:
        ui.aviso("Nenhum usuário cadastrado.")
        return None
    opcoes = [(f"{u['nome']} {u['sobrenome']}  |  CPF {formatar_cpf(u['cpf'])}  |  {u['email']}", u) for u in usuarios]
    return ui.selecionar("Selecione o usuário", opcoes, filtro=True)


def selecionar_vendedor(somente_ativos: bool = False) -> dict[str, Any] | None:
    filtro = {"status": "ativo"} if somente_ativos else {}
    vendedores = list(colecao("vendedores").find(filtro).sort("nome_loja", ASCENDING))
    if not vendedores:
        ui.aviso("Nenhum vendedor disponível.")
        return None
    opcoes = [(f"{v['nome_loja']}  |  CNPJ {formatar_cnpj(v['cnpj'])}  |  {v['status']}", v) for v in vendedores]
    return ui.selecionar("Selecione o vendedor", opcoes, filtro=True)


def selecionar_produto(filtro: dict[str, Any] | None = None) -> dict[str, Any] | None:
    produtos = list(colecao("produtos").find(filtro or {}).sort("titulo", ASCENDING))
    if not produtos:
        ui.aviso("Nenhum produto disponível.")
        return None
    opcoes = [
        (f"{p['titulo']}  |  {formatar_moeda(p['preco'])}  |  estoque {p['quantidade_disponivel']}", p) for p in produtos
    ]
    return ui.selecionar("Selecione o produto", opcoes, filtro=True)


# ============================================================================
# Painel (dashboard)
# ============================================================================
def painel() -> None:
    ui.titulo("Painel geral")
    contagens = dados.contagens()
    receita = dados.receita_total()
    valor_estoque = valor_em_estoque()

    resumo = Table.grid(padding=(0, 3))
    resumo.add_column(style="dim")
    resumo.add_column(justify="right", style="bold")
    for nome, qtd in contagens.items():
        resumo.add_row(nome.capitalize(), str(qtd))
    resumo.add_row("", "")
    resumo.add_row("Receita (pedidos)", formatar_moeda(receita))
    resumo.add_row("Valor em estoque", formatar_moeda(valor_estoque))

    top = dados.mais_vendidos()
    grafico = Table.grid(padding=(0, 1))
    if top:
        maximo = max(p["quantidade_vendida"] for p in top)
        for p in top:
            grafico.add_row(p["titulo"][:22], ui.barra(p["quantidade_vendida"], maximo), str(p["quantidade_vendida"]))
    else:
        grafico.add_row("[dim]Ainda não há vendas.[/]")

    baixo = dados.estoque_baixo()
    alerta = Table.grid(padding=(0, 2))
    if baixo:
        for p in baixo:
            alerta.add_row(p["titulo"][:22], f"[bold red]{p['quantidade_disponivel']}[/] un.")
    else:
        alerta.add_row("[dim]Estoque saudável.[/]")

    ui.console.print(
        Columns(
            [
                ui.painel("Resumo", resumo),
                ui.painel("Mais vendidos", grafico, cor="green"),
                ui.painel(f"Estoque baixo (<= {LIMITE_ESTOQUE_BAIXO})", alerta, cor="red"),
            ],
            expand=True,
        )
    )


# ============================================================================
# Usuários
# ============================================================================
def cadastrar_usuario() -> None:
    ui.titulo("Cadastrar usuário")
    cpf = ui.perguntar("CPF:", validar_cpf)
    nome = ui.perguntar("Nome:")
    sobrenome = ui.perguntar("Sobrenome:")
    email = ui.perguntar("E-mail:", validar_email)
    try:
        doc = dados.inserir_usuario(nome, sobrenome, cpf, email)
        ui.sucesso(f"Usuário {doc['nome']} {doc['sobrenome']} cadastrado.")
    except ErroNegocio as exc:
        ui.erro(str(exc))


def listar_usuarios() -> None:
    usuarios = colecao("usuarios").find().sort("nome", ASCENDING)
    linhas = [
        (f"{u['nome']} {u['sobrenome']}", formatar_cpf(u["cpf"]), u["email"], str(len(u.get("enderecos", []))), formatar_data(u.get("criado_em")))
        for u in usuarios
    ]
    ui.tabela("Usuários", ["Nome", "CPF", "E-mail", ("Endereços", "right"), "Cadastro"], linhas, "Nenhum usuário cadastrado.")


def atualizar_usuario() -> None:
    if not (usuario := selecionar_usuario()):
        return
    nome = ui.perguntar("Nome:", padrao=usuario["nome"])
    sobrenome = ui.perguntar("Sobrenome:", padrao=usuario["sobrenome"])
    email = ui.perguntar("E-mail:", validar_email, padrao=usuario["email"])
    if dados.atualizar_usuario(usuario["_id"], nome, sobrenome, email):
        ui.sucesso("Usuário atualizado.")
    else:
        ui.info("Nenhuma alteração informada.")


def excluir_usuario() -> None:
    if not (usuario := selecionar_usuario()):
        return
    if colecao("pedidos").find_one({"id_comprador": usuario["_id"]}):
        ui.erro("Não é possível excluir: o usuário possui pedidos vinculados.")
        return
    if ui.confirmar(f"Excluir {usuario['nome']} {usuario['sobrenome']}?"):
        dados.excluir_usuario(usuario["_id"])
        ui.sucesso("Usuário excluído.")


def consultar_cep(cep: str) -> dict[str, str] | None:
    """Consulta o ViaCEP. Devolve ``None`` se o CEP não existir ou a API falhar."""
    try:
        resposta = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5)
        resposta.raise_for_status()
        dados = resposta.json()
    except (requests.RequestException, ValueError):
        return None
    return None if dados.get("erro") else dados


def adicionar_endereco() -> None:
    if not (usuario := selecionar_usuario()):
        return
    cep = ui.perguntar("CEP:", validar_cep)
    with ui.processando("Consultando CEP..."):
        achado = consultar_cep(cep)
    if achado:
        ui.sucesso(f"Endereço encontrado: {achado.get('logradouro') or '(sem logradouro)'}, {achado.get('localidade')}/{achado.get('uf')}")
    else:
        ui.aviso("CEP não localizado (ou serviço indisponível). Preencha manualmente.")
        achado = {}
    rua = ui.perguntar("Rua:", padrao=achado.get("logradouro", ""))
    numero = ui.perguntar("Número:")
    complemento = ui.perguntar("Complemento (opcional):", obrigatorio=False) or ""
    bairro = ui.perguntar("Bairro:", padrao=achado.get("bairro", ""))
    cidade = ui.perguntar("Cidade:", padrao=achado.get("localidade", ""))
    estado = ui.perguntar("UF:", padrao=achado.get("uf", ""))
    dados.adicionar_endereco(usuario["_id"], cep, rua, numero, bairro, cidade, estado, complemento)
    ui.sucesso("Endereço adicionado.")


def listar_enderecos() -> None:
    if not (usuario := selecionar_usuario()):
        return
    linhas = [
        (f"{e['rua']}, {e['numero']}" + (f" - {e['complemento']}" if e.get("complemento") else ""), e["bairro"], f"{e['cidade']}/{e['estado']}", formatar_cep(e["cep"]))
        for e in usuario.get("enderecos", [])
    ]
    ui.tabela(f"Endereços de {usuario['nome']}", ["Logradouro", "Bairro", "Cidade", "CEP"], linhas, "Nenhum endereço cadastrado.")


# ============================================================================
# Vendedores
# ============================================================================
def cadastrar_vendedor() -> None:
    ui.titulo("Cadastrar vendedor")
    loja = ui.perguntar("Nome da loja:")
    cnpj = ui.perguntar("CNPJ:", validar_cnpj)
    try:
        doc = dados.inserir_vendedor(loja, cnpj)
        ui.sucesso(f"Loja {doc['nome_loja']} cadastrada.")
    except ErroNegocio as exc:
        ui.erro(str(exc))


def listar_vendedores() -> None:
    vendedores = colecao("vendedores").find().sort("nome_loja", ASCENDING)
    linhas = [
        (v["nome_loja"], formatar_cnpj(v["cnpj"]), str(v["avaliacao"].to_decimal()), ui.status_texto(v["status"]))
        for v in vendedores
    ]
    ui.tabela("Vendedores", ["Loja", "CNPJ", ("Nota", "right"), "Status"], linhas, "Nenhum vendedor cadastrado.")


def atualizar_vendedor() -> None:
    if not (vendedor := selecionar_vendedor()):
        return
    nome = ui.perguntar("Nome da loja:", padrao=vendedor["nome_loja"])
    status = ui.selecionar("Status", [("ativo", "ativo"), ("inativo", "inativo")], voltar=None, padrao=vendedor["status"])
    try:
        if dados.atualizar_vendedor(vendedor["_id"], nome, status):
            ui.sucesso("Vendedor atualizado.")
        else:
            ui.info("Nenhuma alteração informada.")
    except ErroNegocio as exc:
        ui.erro(str(exc))


def excluir_vendedor() -> None:
    if not (vendedor := selecionar_vendedor()):
        return
    if colecao("produtos").find_one({"id_vendedor": vendedor["_id"]}):
        ui.erro("Não é possível excluir: existem produtos vinculados a este vendedor.")
        return
    if ui.confirmar(f"Excluir a loja {vendedor['nome_loja']}?"):
        dados.excluir_vendedor(vendedor["_id"])
        ui.sucesso("Vendedor excluído.")


# ============================================================================
# Produtos
# ============================================================================
def _categorias() -> list[str]:
    return dados.categorias()


def cadastrar_produto() -> None:
    ui.titulo("Cadastrar produto")
    if not (vendedor := selecionar_vendedor(somente_ativos=True)):
        return
    titulo = ui.perguntar("Título:")
    descricao = ui.perguntar("Descrição:")
    preco = ui.perguntar("Preço (R$):", converter_decimal)
    estoque = ui.perguntar("Quantidade em estoque:", converter_inteiro)
    categoria = ui.perguntar("Categoria (ex.: MLB1648):", sugestoes=_categorias())
    doc = dados.inserir_produto(vendedor["_id"], titulo, descricao, preco, estoque, categoria)
    ui.sucesso(f"Produto '{doc['titulo']}' cadastrado.")


def _tabela_produtos(titulo_tabela: str, produtos: Sequence[dict[str, Any]]) -> None:
    linhas = [
        (
            p["titulo"],
            formatar_moeda(p["preco"]),
            str(p["quantidade_disponivel"]),
            str(p.get("quantidade_vendida", 0)),
            p.get("id_categoria", "-"),
            p.get("vendedor", {}).get("nome_loja", "N/A"),
            ui.status_texto(p["status"]),
        )
        for p in produtos
    ]
    ui.tabela(
        titulo_tabela,
        ["Título", ("Preço", "right"), ("Estoque", "right"), ("Vendidos", "right"), "Categoria", "Loja", "Status"],
        linhas,
        "Nenhum produto encontrado.",
    )


def listar_produtos() -> None:
    chave = ui.selecionar("Ordenar por", [(rotulo, k) for k, (rotulo, _) in ORDENACOES.items()], voltar=None)
    rotulo, ordem = ORDENACOES[chave]
    _tabela_produtos(f"Produtos - {rotulo}", _produtos_com_vendedor(ordem=ordem))


def buscar_produtos() -> None:
    """Busca por trecho do título (sem diferenciar maiúsculas), com autocompletar."""
    titulos = colecao("produtos").distinct("titulo")
    if not titulos:
        ui.aviso("Nenhum produto cadastrado.")
        return
    termo = ui.perguntar("Buscar produto (digite parte do título):", sugestoes=sorted(titulos))
    filtro = {"titulo": {"$regex": re.escape(termo), "$options": "i"}}
    _tabela_produtos(f"Resultados para '{termo}'", _produtos_com_vendedor(filtro))


def filtrar_por_categoria() -> None:
    categorias = _categorias()
    if not categorias:
        ui.aviso("Nenhuma categoria cadastrada.")
        return
    categoria = ui.selecionar("Categoria", [(c, c) for c in categorias], filtro=True)
    if categoria:
        _tabela_produtos(f"Categoria {categoria}", _produtos_com_vendedor({"id_categoria": categoria}))


def atualizar_produto() -> None:
    if not (prod := selecionar_produto()):
        return
    titulo = ui.perguntar("Título:", padrao=prod["titulo"])
    descricao = ui.perguntar("Descrição:", padrao=prod.get("descricao", ""))
    preco = ui.perguntar("Preço (R$):", converter_decimal, padrao=str(prod["preco"].to_decimal()))
    estoque = ui.perguntar("Estoque:", converter_inteiro, padrao=str(prod["quantidade_disponivel"]))
    if dados.atualizar_produto(prod["_id"], titulo, descricao, preco, estoque):
        ui.sucesso("Produto atualizado.")
    else:
        ui.info("Nenhuma alteração informada.")


def excluir_produto() -> None:
    if not (prod := selecionar_produto()):
        return
    if colecao("pedidos").find_one({"itens.id_produto": prod["_id"]}):
        ui.erro("Não é possível excluir: o produto possui histórico de pedidos.")
        return
    if ui.confirmar(f"Excluir '{prod['titulo']}'?"):
        dados.excluir_produto(prod["_id"])
        ui.sucesso("Produto excluído.")


def exportar_produtos_csv() -> None:
    produtos = _produtos_com_vendedor()
    if not produtos:
        ui.aviso("Nenhum produto para exportar.")
        return
    PASTA_EXPORTACOES.mkdir(exist_ok=True)
    caminho = PASTA_EXPORTACOES / f"produtos_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with caminho.open("w", newline="", encoding="utf-8-sig") as arq:  # utf-8-sig: abre certo no Excel
        escritor = csv.writer(arq, delimiter=";")
        escritor.writerow(["id", "titulo", "preco", "estoque", "vendidos", "categoria", "loja", "status"])
        for p in produtos:
            escritor.writerow(
                [p["_id"], p["titulo"], p["preco"].to_decimal(), p["quantidade_disponivel"], p.get("quantidade_vendida", 0), p.get("id_categoria", ""), p.get("vendedor", {}).get("nome_loja", ""), p["status"]]
            )
    ui.sucesso(f"{len(produtos)} produtos exportados para {caminho}")


# ============================================================================
# Favoritos
# ============================================================================
def adicionar_favorito() -> None:
    if not (u := selecionar_usuario()) or not (p := selecionar_produto()):
        return
    try:
        if dados.adicionar_favorito(u["_id"], p["_id"]):
            ui.sucesso(f"'{p['titulo']}' adicionado aos favoritos de {u['nome']}.")
        else:
            ui.aviso("Este produto já está nos favoritos.")
    except ErroNegocio as exc:
        ui.erro(str(exc))


def listar_favoritos() -> None:
    if not (u := selecionar_usuario()):
        return
    linhas = [(f["produto"]["titulo"], formatar_moeda(f["produto"]["preco"]), formatar_data(f["criado_em"])) for f in dados.listar_favoritos(u["_id"])]
    ui.tabela(f"Favoritos de {u['nome']}", ["Produto", ("Preço", "right"), "Favoritado em"], linhas, "Nenhum favorito cadastrado.")


def remover_favorito() -> None:
    if not (u := selecionar_usuario()):
        return
    favoritos = dados.listar_favoritos(u["_id"])
    if not favoritos:
        ui.aviso("Nenhum favorito cadastrado.")
        return
    escolhido = ui.selecionar("Qual favorito remover?", [(f["produto"]["titulo"], f) for f in favoritos], filtro=True)
    if escolhido:
        dados.remover_favorito(u["_id"], escolhido["id_produto"])
        ui.sucesso("Favorito removido.")


# ============================================================================
# Pedidos
# ============================================================================
def criar_pedido() -> None:
    ui.titulo("Criar pedido")
    if not (comprador := selecionar_usuario()):
        return
    if not (prod := selecionar_produto({"status": "ativo", "quantidade_disponivel": {"$gt": 0}})):
        return
    qtd = ui.perguntar(
        f"Quantidade (máx. {prod['quantidade_disponivel']}):",
        lambda v: converter_inteiro(v, minimo=1, maximo=prod["quantidade_disponivel"]),
    )
    preco_unitario = prod["preco"].to_decimal()
    total = (preco_unitario * qtd).quantize(Decimal("0.01"))
    ui.console.print(ui.painel("Resumo do pedido", f"{prod['titulo']}\n{qtd} x {formatar_moeda(preco_unitario)} = [bold]{formatar_moeda(total)}[/]\nComprador: {comprador['nome']} {comprador['sobrenome']}"))
    if not ui.confirmar("Confirmar pedido?", padrao=True):
        ui.info("Pedido cancelado.")
        return
    try:
        pedido = dados.criar_pedido(comprador["_id"], prod["_id"], qtd)
        ui.sucesso(f"Pedido criado. Total: {formatar_moeda(pedido['valor_total'])}")
    except ErroNegocio as exc:
        ui.erro(str(exc))


def listar_pedidos() -> None:
    if not (usuario := selecionar_usuario()):
        return
    pedidos = colecao("pedidos").find({"id_comprador": usuario["_id"]}).sort("criado_em", DESCENDING)
    linhas = [
        (
            formatar_data(p["criado_em"]),
            ", ".join(f"{it['titulo']} x{it['quantidade']}" for it in p.get("itens", [])),
            formatar_moeda(p["valor_total"]),
            ui.status_texto(p["status"]),
        )
        for p in pedidos
    ]
    ui.tabela(f"Pedidos de {usuario['nome']}", ["Data", "Itens", ("Total", "right"), "Status"], linhas, "Nenhum pedido encontrado.")


# ============================================================================
# Menus
# ============================================================================
def main() -> None:
    try:
        with ui.processando("Conectando ao MongoDB..."):
            mongo_db().client.admin.command("ping")
            configurar_banco_dados()
    except PyMongoError as exc:
        ui.erro(f"Falha ao conectar ao MongoDB: {exc}")
        return
    ui.sucesso(f"Conectado ao MongoDB ({mongo_db().name}).")
    ui.apresentar("MongoDB", "banco de documentos", RESUMO)

    ui.menu(
        "CATÁLOGO E PEDIDOS (MongoDB)",
        [
            ("Carregar dados de demonstração", carregar_demonstracao),
            ("Painel geral", painel),
            ("Usuários", lambda: ui.menu("USUÁRIOS", [
                ("Cadastrar", cadastrar_usuario), ("Listar", listar_usuarios), ("Atualizar", atualizar_usuario),
                ("Excluir", excluir_usuario), ("Adicionar endereço (busca por CEP)", adicionar_endereco),
                ("Ver endereços", listar_enderecos),
            ])),
            ("Vendedores", lambda: ui.menu("VENDEDORES", [
                ("Cadastrar", cadastrar_vendedor), ("Listar", listar_vendedores),
                ("Atualizar", atualizar_vendedor), ("Excluir", excluir_vendedor),
            ])),
            ("Produtos", lambda: ui.menu("PRODUTOS", [
                ("Cadastrar", cadastrar_produto), ("Listar", listar_produtos), ("Buscar por título", buscar_produtos),
                ("Filtrar por categoria", filtrar_por_categoria), ("Atualizar", atualizar_produto),
                ("Excluir", excluir_produto), ("Exportar para CSV", exportar_produtos_csv),
            ])),
            ("Favoritos", lambda: ui.menu("FAVORITOS", [
                ("Adicionar", adicionar_favorito), ("Listar", listar_favoritos), ("Remover", remover_favorito),
            ])),
            ("Pedidos", lambda: ui.menu("PEDIDOS", [
                ("Criar pedido", criar_pedido), ("Listar pedidos de um usuário", listar_pedidos),
            ])),
        ],
        raiz=True,
    )


if __name__ == "__main__":
    try:
        main()
    finally:
        fechar_conexoes()
