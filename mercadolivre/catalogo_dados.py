"""Operações do catálogo no MongoDB, sem nenhuma interface (CLI ou web).

Este módulo concentra as regras de negócio do MongoDB: validação, unicidade,
baixa atômica de estoque e consultas. A CLI (``catalogo.py``) e a interface web
(``web/``) chamam as mesmas funções, então a regra existe em um lugar só.

Não importa ``rich``, ``questionary`` nem ``streamlit``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from bson import Decimal128, ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

from .conexoes import mongo_db
from .validadores import (
    converter_decimal,
    converter_inteiro,
    normalizar,
    validar_cep,
    validar_cnpj,
    validar_cpf,
    validar_email,
)

LIMITE_ESTOQUE_BAIXO = 3
LIMITE_LISTAGEM = 500

ORDENACOES = {
    "titulo": ("Título (A-Z)", [("titulo", ASCENDING)]),
    "menor_preco": ("Menor preço", [("preco", ASCENDING), ("titulo", ASCENDING)]),
    "maior_preco": ("Maior preço", [("preco", DESCENDING), ("titulo", ASCENDING)]),
    "maior_estoque": ("Maior estoque", [("quantidade_disponivel", DESCENDING), ("titulo", ASCENDING)]),
    "mais_vendidos": ("Mais vendidos", [("quantidade_vendida", DESCENDING), ("titulo", ASCENDING)]),
}


class ErroNegocio(ValueError):
    """Regra de negócio violada (duplicidade, vínculo existente, estoque insuficiente...)."""


# ----------------------------------------------------------------------------
# Acesso ao banco
# ----------------------------------------------------------------------------
def colecao(nome: str) -> Collection:
    return mongo_db()[nome]


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def dinheiro(valor: Decimal | str) -> Decimal128:
    return Decimal128(Decimal(str(valor)).quantize(Decimal("0.01")))


def como_objectid(valor: ObjectId | str) -> ObjectId:
    """Aceita ``ObjectId`` ou texto (vindo de um formulário web) e rejeita ids malformados."""
    try:
        return valor if isinstance(valor, ObjectId) else ObjectId(str(valor))
    except (InvalidId, TypeError) as exc:
        raise ErroNegocio("Identificador inválido.") from exc


def configurar_banco_dados() -> None:
    """Cria os índices (idempotente), uma chamada por coleção."""
    idx = IndexModel
    colecao("usuarios").create_indexes([idx([("cpf", ASCENDING)], unique=True), idx([("nome", ASCENDING), ("sobrenome", ASCENDING)])])
    colecao("vendedores").create_indexes([idx([("cnpj", ASCENDING)], unique=True), idx([("nome_loja", ASCENDING)], unique=True)])
    colecao("produtos").create_indexes([idx([("titulo", ASCENDING)]), idx([("id_categoria", ASCENDING)]), idx([("id_vendedor", ASCENDING)])])
    colecao("favoritos").create_indexes([idx([("id_usuario", ASCENDING), ("id_produto", ASCENDING)], unique=True)])
    colecao("pedidos").create_indexes([idx([("id_comprador", ASCENDING)]), idx([("criado_em", DESCENDING)])])


def _trecho(termo: str | None) -> dict[str, Any] | None:
    termo = (termo or "").strip()
    return {"$regex": re.escape(termo), "$options": "i"} if termo else None


# ----------------------------------------------------------------------------
# Usuários
# ----------------------------------------------------------------------------
def inserir_usuario(nome: str, sobrenome: str, cpf: str, email: str) -> dict[str, Any]:
    doc = {
        "nome": normalizar(nome),
        "sobrenome": normalizar(sobrenome),
        "cpf": validar_cpf(cpf),
        "email": validar_email(email),
        "enderecos": [],
        "criado_em": agora_utc(),
        "atualizado_em": agora_utc(),
    }
    if not doc["nome"] or not doc["sobrenome"]:
        raise ErroNegocio("Informe nome e sobrenome.")
    try:
        colecao("usuarios").insert_one(doc)
    except DuplicateKeyError as exc:
        raise ErroNegocio("Já existe um usuário com esse CPF.") from exc
    return doc


def buscar_usuario(id_usuario: ObjectId | str) -> dict[str, Any] | None:
    return colecao("usuarios").find_one({"_id": como_objectid(id_usuario)})


def buscar_usuario_por_email(email: str) -> dict[str, Any] | None:
    return colecao("usuarios").find_one({"email": (email or "").strip().lower()})


def listar_usuarios(termo: str | None = None) -> list[dict[str, Any]]:
    filtro: dict[str, Any] = {}
    if (rx := _trecho(termo)) is not None:
        filtro["$or"] = [{"nome": rx}, {"sobrenome": rx}, {"email": rx}, {"cpf": rx}]
    return list(colecao("usuarios").find(filtro).sort("nome", ASCENDING).limit(LIMITE_LISTAGEM))


def atualizar_usuario(id_usuario: ObjectId | str, nome: str, sobrenome: str, email: str) -> bool:
    """Atualiza só o que mudou. Devolve ``False`` quando não havia nada a alterar."""
    usuario = buscar_usuario(id_usuario)
    if usuario is None:
        raise ErroNegocio("Usuário não encontrado.")
    novos = {"nome": normalizar(nome), "sobrenome": normalizar(sobrenome), "email": validar_email(email)}
    alteracoes = {k: v for k, v in novos.items() if v != usuario[k]}
    if not alteracoes:
        return False
    alteracoes["atualizado_em"] = agora_utc()
    colecao("usuarios").update_one({"_id": usuario["_id"]}, {"$set": alteracoes})
    return True


def excluir_usuario(id_usuario: ObjectId | str) -> None:
    _id = como_objectid(id_usuario)
    if colecao("pedidos").find_one({"id_comprador": _id}):
        raise ErroNegocio("Não é possível excluir: o usuário possui pedidos vinculados.")
    colecao("favoritos").delete_many({"id_usuario": _id})
    colecao("usuarios").delete_one({"_id": _id})


def adicionar_endereco(id_usuario: ObjectId | str, cep: str, rua: str, numero: str, bairro: str, cidade: str, estado: str, complemento: str = "") -> dict[str, str]:
    endereco = {
        "cep": validar_cep(cep),
        "rua": normalizar(rua),
        "numero": (numero or "").strip(),
        "complemento": (complemento or "").strip(),
        "bairro": normalizar(bairro),
        "cidade": normalizar(cidade),
        "estado": (estado or "").strip().upper(),
    }
    if not all(endereco[c] for c in ("rua", "numero", "bairro", "cidade", "estado")):
        raise ErroNegocio("Preencha rua, número, bairro, cidade e UF.")
    res = colecao("usuarios").update_one(
        {"_id": como_objectid(id_usuario)}, {"$push": {"enderecos": endereco}, "$set": {"atualizado_em": agora_utc()}}
    )
    if res.matched_count != 1:
        raise ErroNegocio("Usuário não encontrado.")
    return endereco


# ----------------------------------------------------------------------------
# Vendedores
# ----------------------------------------------------------------------------
def inserir_vendedor(nome_loja: str, cnpj: str) -> dict[str, Any]:
    doc = {
        "nome_loja": normalizar(nome_loja),
        "cnpj": validar_cnpj(cnpj),
        "avaliacao": Decimal128("0.00"),
        "quantidade_avaliacoes": 0,
        "status": "ativo",
        "criado_em": agora_utc(),
        "atualizado_em": agora_utc(),
    }
    if not doc["nome_loja"]:
        raise ErroNegocio("Informe o nome da loja.")
    try:
        colecao("vendedores").insert_one(doc)
    except DuplicateKeyError as exc:
        raise ErroNegocio("Já existe uma loja com este CNPJ ou nome.") from exc
    return doc


def buscar_vendedor(id_vendedor: ObjectId | str) -> dict[str, Any] | None:
    return colecao("vendedores").find_one({"_id": como_objectid(id_vendedor)})


def listar_vendedores(termo: str | None = None, somente_ativos: bool = False) -> list[dict[str, Any]]:
    filtro: dict[str, Any] = {"status": "ativo"} if somente_ativos else {}
    if (rx := _trecho(termo)) is not None:
        filtro["$or"] = [{"nome_loja": rx}, {"cnpj": rx}]
    return list(colecao("vendedores").find(filtro).sort("nome_loja", ASCENDING).limit(LIMITE_LISTAGEM))


def atualizar_vendedor(id_vendedor: ObjectId | str, nome_loja: str, status: str) -> bool:
    vendedor = buscar_vendedor(id_vendedor)
    if vendedor is None:
        raise ErroNegocio("Vendedor não encontrado.")
    if status not in ("ativo", "inativo"):
        raise ErroNegocio("Status inválido.")
    novos = {"nome_loja": normalizar(nome_loja), "status": status}
    if not novos["nome_loja"]:
        raise ErroNegocio("Informe o nome da loja.")
    alteracoes = {k: v for k, v in novos.items() if v != vendedor[k]}
    if not alteracoes:
        return False
    alteracoes["atualizado_em"] = agora_utc()
    try:
        colecao("vendedores").update_one({"_id": vendedor["_id"]}, {"$set": alteracoes})
    except DuplicateKeyError as exc:
        raise ErroNegocio("Já existe uma loja com esse nome.") from exc
    return True


def excluir_vendedor(id_vendedor: ObjectId | str) -> None:
    _id = como_objectid(id_vendedor)
    if colecao("produtos").find_one({"id_vendedor": _id}):
        raise ErroNegocio("Não é possível excluir: existem produtos vinculados a este vendedor.")
    colecao("vendedores").delete_one({"_id": _id})


# ----------------------------------------------------------------------------
# Produtos
# ----------------------------------------------------------------------------
def categorias() -> list[str]:
    return sorted(c for c in colecao("produtos").distinct("id_categoria") if c)


def inserir_produto(id_vendedor: ObjectId | str, titulo: str, descricao: str, preco: Decimal | str, estoque: int | str, categoria: str) -> dict[str, Any]:
    vendedor = buscar_vendedor(id_vendedor)
    if vendedor is None or vendedor["status"] != "ativo":
        raise ErroNegocio("Selecione um vendedor ativo.")
    qtd = converter_inteiro(str(estoque))
    doc = {
        "id_site": "MLB",
        "titulo": normalizar(titulo),
        "descricao": (descricao or "").strip(),
        "preco": dinheiro(converter_decimal(str(preco))),
        "quantidade_disponivel": qtd,
        "id_categoria": (categoria or "").strip().upper(),
        "id_vendedor": vendedor["_id"],
        "status": "ativo" if qtd > 0 else "pausado",
        "condicao": "novo",
        "quantidade_vendida": 0,
        "criado_em": agora_utc(),
        "atualizado_em": agora_utc(),
    }
    if not doc["titulo"] or not doc["id_categoria"]:
        raise ErroNegocio("Informe título e categoria.")
    colecao("produtos").insert_one(doc)
    return doc


def produtos_com_vendedor(filtro: dict[str, Any] | None = None, ordem: list[tuple[str, int]] | None = None) -> list[dict[str, Any]]:
    """Produtos com os dados da loja anexados (``$lookup``, o "JOIN" do MongoDB)."""
    pipeline: list[dict[str, Any]] = []
    if filtro:
        pipeline.append({"$match": filtro})
    pipeline += [
        {"$lookup": {"from": "vendedores", "localField": "id_vendedor", "foreignField": "_id", "as": "vendedor"}},
        {"$unwind": {"path": "$vendedor", "preserveNullAndEmptyArrays": True}},
        {"$sort": dict(ordem or [("titulo", ASCENDING)])},
        {"$limit": LIMITE_LISTAGEM},
    ]
    return list(colecao("produtos").aggregate(pipeline))


def buscar_produtos(termo: str | None = None, categoria: str | None = None, id_vendedor: ObjectId | str | None = None, ordenar: str = "titulo") -> list[dict[str, Any]]:
    filtro: dict[str, Any] = {}
    if (rx := _trecho(termo)) is not None:
        filtro["titulo"] = rx
    if categoria:
        filtro["id_categoria"] = categoria
    if id_vendedor:
        filtro["id_vendedor"] = como_objectid(id_vendedor)
    return produtos_com_vendedor(filtro or None, ORDENACOES.get(ordenar, ORDENACOES["titulo"])[1])


def buscar_produto(id_produto: ObjectId | str) -> dict[str, Any] | None:
    achados = produtos_com_vendedor({"_id": como_objectid(id_produto)})
    return achados[0] if achados else None


def atualizar_produto(id_produto: ObjectId | str, titulo: str, descricao: str, preco: Decimal | str, estoque: int | str) -> bool:
    produto = colecao("produtos").find_one({"_id": como_objectid(id_produto)})
    if produto is None:
        raise ErroNegocio("Produto não encontrado.")
    novos: dict[str, Any] = {
        "titulo": normalizar(titulo),
        "descricao": (descricao or "").strip(),
        "preco": dinheiro(converter_decimal(str(preco))),
        "quantidade_disponivel": converter_inteiro(str(estoque)),
    }
    if not novos["titulo"]:
        raise ErroNegocio("Informe o título.")
    alteracoes = {k: v for k, v in novos.items() if v != produto.get(k)}
    if not alteracoes:
        return False
    if "quantidade_disponivel" in alteracoes:  # 0 é um estoque válido (pausa o anúncio)
        alteracoes["status"] = "ativo" if alteracoes["quantidade_disponivel"] > 0 else "pausado"
    alteracoes["atualizado_em"] = agora_utc()
    colecao("produtos").update_one({"_id": produto["_id"]}, {"$set": alteracoes})
    return True


def excluir_produto(id_produto: ObjectId | str) -> None:
    _id = como_objectid(id_produto)
    if colecao("pedidos").find_one({"itens.id_produto": _id}):
        raise ErroNegocio("Não é possível excluir: o produto possui histórico de pedidos.")
    colecao("favoritos").delete_many({"id_produto": _id})
    colecao("produtos").delete_one({"_id": _id})


# ----------------------------------------------------------------------------
# Pedidos
# ----------------------------------------------------------------------------
def criar_pedido(id_comprador: ObjectId | str, id_produto: ObjectId | str, quantidade: int | str) -> dict[str, Any]:
    """Cria o pedido com baixa atômica de estoque (desfeita se a gravação do pedido falhar)."""
    comprador = buscar_usuario(id_comprador)
    if comprador is None:
        raise ErroNegocio("Comprador não encontrado.")
    prod = colecao("produtos").find_one({"_id": como_objectid(id_produto)})
    if prod is None or prod.get("status") != "ativo":
        raise ErroNegocio("Produto indisponível.")
    qtd = converter_inteiro(str(quantidade), minimo=1, maximo=prod["quantidade_disponivel"] or None)
    preco_unitario = prod["preco"].to_decimal()
    total = (preco_unitario * qtd).quantize(Decimal("0.01"))

    # Baixa atômica: só decrementa se ainda houver saldo suficiente.
    res = colecao("produtos").update_one(
        {"_id": prod["_id"], "quantidade_disponivel": {"$gte": qtd}, "status": "ativo"},
        {"$inc": {"quantidade_disponivel": -qtd, "quantidade_vendida": qtd}, "$set": {"atualizado_em": agora_utc()}},
    )
    if res.modified_count != 1:
        raise ErroNegocio("Falha ao reservar o estoque (outro pedido pode ter esgotado o produto). Tente novamente.")

    pedido = {
        "status": "pago",
        "id_comprador": comprador["_id"],
        "id_vendedor": prod["id_vendedor"],
        "itens": [
            {
                "id_produto": prod["_id"],
                "titulo": prod["titulo"],
                "quantidade": qtd,
                "preco_unitario": dinheiro(preco_unitario),
                "total": dinheiro(total),
            }
        ],
        "valor_total": dinheiro(total),
        "criado_em": agora_utc(),
        "atualizado_em": agora_utc(),
    }
    try:
        colecao("pedidos").insert_one(pedido)
    except PyMongoError:
        colecao("produtos").update_one(  # desfaz a baixa de estoque
            {"_id": prod["_id"]},
            {"$inc": {"quantidade_disponivel": qtd, "quantidade_vendida": -qtd}, "$set": {"atualizado_em": agora_utc()}},
        )
        raise
    return pedido


def listar_pedidos(id_comprador: ObjectId | str | None = None) -> list[dict[str, Any]]:
    """Pedidos (mais novos primeiro) com o nome do comprador anexado."""
    pipeline: list[dict[str, Any]] = []
    if id_comprador is not None:
        pipeline.append({"$match": {"id_comprador": como_objectid(id_comprador)}})
    pipeline += [
        {"$sort": {"criado_em": -1}},
        {"$limit": LIMITE_LISTAGEM},
        {"$lookup": {"from": "usuarios", "localField": "id_comprador", "foreignField": "_id", "as": "comprador"}},
        {"$unwind": {"path": "$comprador", "preserveNullAndEmptyArrays": True}},
    ]
    return list(colecao("pedidos").aggregate(pipeline))


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------
def _soma(cursor: Any) -> Decimal:
    for doc in cursor:
        total = doc["total"]
        return total.to_decimal() if isinstance(total, Decimal128) else Decimal(str(total))
    return Decimal("0")


def valor_em_estoque() -> Decimal:
    """Soma de preço x quantidade de todos os produtos, calculada no próprio MongoDB."""
    return _soma(
        colecao("produtos").aggregate(
            [{"$group": {"_id": None, "total": {"$sum": {"$multiply": ["$preco", "$quantidade_disponivel"]}}}}]
        )
    )


def receita_total() -> Decimal:
    return _soma(colecao("pedidos").aggregate([{"$group": {"_id": None, "total": {"$sum": "$valor_total"}}}]))


def contagens() -> dict[str, int]:
    return {nome: colecao(nome).count_documents({}) for nome in ("usuarios", "vendedores", "produtos", "pedidos", "favoritos")}


def mais_vendidos(limite: int = 5) -> list[dict[str, Any]]:
    return list(colecao("produtos").find({"quantidade_vendida": {"$gt": 0}}).sort("quantidade_vendida", DESCENDING).limit(limite))


def estoque_baixo(limite: int = 5) -> list[dict[str, Any]]:
    filtro = {"quantidade_disponivel": {"$lte": LIMITE_ESTOQUE_BAIXO}}
    return list(colecao("produtos").find(filtro).sort("quantidade_disponivel", ASCENDING).limit(limite))


def vendas_por_dia() -> list[dict[str, Any]]:
    """Receita e número de pedidos por dia (UTC), calculados no MongoDB."""
    pipeline = [
        {"$group": {"_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$criado_em"}}, "pedidos": {"$sum": 1}, "receita": {"$sum": "$valor_total"}}},
        {"$sort": {"_id": 1}},
    ]
    return [
        {"dia": d["_id"], "pedidos": d["pedidos"], "receita": d["receita"].to_decimal() if isinstance(d["receita"], Decimal128) else Decimal(str(d["receita"]))}
        for d in colecao("pedidos").aggregate(pipeline)
    ]


# ----------------------------------------------------------------------------
# Dados de demonstração
# ----------------------------------------------------------------------------
def carregar_demonstracao() -> None:
    """Carrega o conjunto de exemplo (``dados_demo``). Idempotente: ``$setOnInsert`` só grava o que ainda não existe."""
    from . import dados_demo

    agora = agora_utc()
    for cpf, nome, sobrenome, email in dados_demo.USUARIOS:
        colecao("usuarios").update_one(
            {"cpf": cpf},
            {"$setOnInsert": {"nome": nome, "sobrenome": sobrenome, "email": email, "enderecos": [], "criado_em": agora, "atualizado_em": agora}},
            upsert=True,
        )
    ids_vendedor = {}
    for cnpj, loja in dados_demo.LOJAS:
        colecao("vendedores").update_one(
            {"cnpj": cnpj},
            {"$setOnInsert": {"nome_loja": loja, "avaliacao": Decimal128("0.00"), "quantidade_avaliacoes": 0, "status": "ativo", "criado_em": agora, "atualizado_em": agora}},
            upsert=True,
        )
        ids_vendedor[cnpj] = colecao("vendedores").find_one({"cnpj": cnpj})["_id"]
    for p in dados_demo.PRODUTOS:
        colecao("produtos").update_one(
            {"titulo": p.titulo, "id_vendedor": ids_vendedor[p.cnpj]},
            {"$setOnInsert": {
                "id_site": "MLB", "descricao": p.descricao, "preco": dinheiro(p.preco), "quantidade_disponivel": p.estoque,
                "id_categoria": p.categoria, "status": "ativo", "condicao": "novo", "quantidade_vendida": 0,
                "criado_em": agora, "atualizado_em": agora,
            }},
            upsert=True,
        )
