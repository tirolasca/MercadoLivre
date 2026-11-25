"""Serviço do MongoDB (catálogo, usuários, favoritos, vendedores e pedidos) para a web.

Reaproveita ``mercadolivre.catalogo_dados`` (a mesma regra da CLI), acrescentando:
checagem de papel em cada operação, conversão de tipos do BSON e mascaramento de
dados pessoais para quem não é administrador.
"""

from __future__ import annotations

from typing import Any

from mercadolivre import catalogo_dados as dados
from mercadolivre.catalogo_dados import ErroNegocio
from web.auth.permissoes import Ator, Papel, exigir, tem
from web.utils.formatacao import como_decimal, id_texto

from .resultado import Resultado, executar

BANCO = "MongoDB"


# ----------------------------------------------------------------------------
# Conversões BSON -> tipos simples
# ----------------------------------------------------------------------------
def _produto(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": id_texto(p["_id"]), "titulo": p["titulo"], "descricao": p.get("descricao", ""),
        "preco": como_decimal(p["preco"]), "estoque": p["quantidade_disponivel"],
        "vendidos": p.get("quantidade_vendida", 0), "categoria": p.get("id_categoria", ""),
        "loja": (p.get("vendedor") or {}).get("nome_loja", "N/A"), "id_vendedor": id_texto(p.get("id_vendedor")),
        "status": p.get("status", ""),
    }


def _usuario(u: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": id_texto(u["_id"]), "nome": u["nome"], "sobrenome": u["sobrenome"], "cpf": u["cpf"], "email": u["email"],
        "enderecos": u.get("enderecos", []), "criado_em": u.get("criado_em"),
        "favoritos": [id_texto(f["id_produto"]) for f in u.get("favoritos", [])],
    }


def _favorito(f: dict[str, Any]) -> dict[str, Any]:
    return _produto({**f["produto"], "vendedor": f.get("vendedor")}) | {"favoritado_em": f.get("criado_em")}


def _vendedor(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": id_texto(v["_id"]), "nome_loja": v["nome_loja"], "cnpj": v["cnpj"], "status": v["status"],
        "avaliacao": como_decimal(v.get("avaliacao")), "criado_em": v.get("criado_em"),
    }


def _pedido(p: dict[str, Any], com_pessoas: bool) -> dict[str, Any]:
    comprador = p.get("comprador") or {}
    return {
        "id": id_texto(p["_id"]), "criado_em": p.get("criado_em"), "status": p.get("status", ""),
        "comprador": f"{comprador.get('nome', '')} {comprador.get('sobrenome', '')}".strip() or "—" if com_pessoas else "—",
        "itens": [{"titulo": i["titulo"], "quantidade": i["quantidade"], "preco_unitario": como_decimal(i["preco_unitario"]), "total": como_decimal(i["total"])} for i in p.get("itens", [])],
        "total": como_decimal(p["valor_total"]),
    }


# ----------------------------------------------------------------------------
# Indicadores (públicos: apenas agregados)
# ----------------------------------------------------------------------------
def _indicadores() -> dict[str, Any]:
    return {
        "contagens": dados.contagens(),
        "receita": dados.receita_total(),
        "valor_estoque": dados.valor_em_estoque(),
        "mais_vendidos": [{"titulo": p["titulo"], "vendidos": p["quantidade_vendida"]} for p in dados.mais_vendidos(8)],
        "estoque_baixo": [{"titulo": p["titulo"], "estoque": p["quantidade_disponivel"]} for p in dados.estoque_baixo(8)],
        "vendas_por_dia": dados.vendas_por_dia(),
        "limite_estoque_baixo": dados.LIMITE_ESTOQUE_BAIXO,
    }


def indicadores() -> Resultado[dict[str, Any]]:
    return executar(BANCO, _indicadores)


# ----------------------------------------------------------------------------
# Produtos
# ----------------------------------------------------------------------------
def listar_produtos(termo: str | None = None, categoria: str | None = None, id_vendedor: str | None = None, ordenar: str = "titulo") -> Resultado[list[dict[str, Any]]]:
    return executar(BANCO, lambda: [_produto(p) for p in dados.buscar_produtos(termo, categoria, id_vendedor or None, ordenar)])


def categorias() -> Resultado[list[str]]:
    return executar(BANCO, dados.categorias)


def criar_produto(ator: Ator, id_vendedor: str, titulo: str, descricao: str, preco: str, estoque: str, categoria: str) -> Resultado[str]:
    def op() -> str:
        exigir(ator, Papel.ADMIN)
        return id_texto(dados.inserir_produto(id_vendedor, titulo, descricao, preco, estoque, categoria)["_id"])
    return executar(BANCO, op)


def atualizar_produto(ator: Ator, id_produto: str, titulo: str, descricao: str, preco: str, estoque: str) -> Resultado[bool]:
    def op() -> bool:
        exigir(ator, Papel.ADMIN)
        return dados.atualizar_produto(id_produto, titulo, descricao, preco, estoque)
    return executar(BANCO, op)


def excluir_produto(ator: Ator, id_produto: str) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        dados.excluir_produto(id_produto)
    return executar(BANCO, op)


# ----------------------------------------------------------------------------
# Usuários (dados pessoais: admin vê todos; usuário vê só o próprio)
# ----------------------------------------------------------------------------
def _usuario_do_ator(ator: Ator) -> dict[str, Any] | None:
    return dados.buscar_usuario_por_email(ator.email or "") if ator.email else None


def listar_usuarios(ator: Ator, termo: str | None = None) -> Resultado[list[dict[str, Any]]]:
    def op() -> list[dict[str, Any]]:
        exigir(ator, Papel.USUARIO)
        if tem(ator, Papel.ADMIN):
            return [_usuario(u) for u in dados.listar_usuarios(termo)]
        proprio = _usuario_do_ator(ator)
        return [_usuario(proprio)] if proprio else []
    return executar(BANCO, op)


def criar_usuario(ator: Ator, nome: str, sobrenome: str, cpf: str, email: str) -> Resultado[str]:
    def op() -> str:
        exigir(ator, Papel.ADMIN)
        return id_texto(dados.inserir_usuario(nome, sobrenome, cpf, email)["_id"])
    return executar(BANCO, op)


def atualizar_usuario(ator: Ator, id_usuario: str, nome: str, sobrenome: str, email: str) -> Resultado[bool]:
    def op() -> bool:
        exigir(ator, Papel.ADMIN)
        return dados.atualizar_usuario(id_usuario, nome, sobrenome, email)
    return executar(BANCO, op)


def excluir_usuario(ator: Ator, id_usuario: str) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        dados.excluir_usuario(id_usuario)
    return executar(BANCO, op)


def adicionar_endereco(ator: Ator, id_usuario: str, **campos: str) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        dados.adicionar_endereco(id_usuario, **campos)
    return executar(BANCO, op)


# ----------------------------------------------------------------------------
# Favoritos (dentro do documento do usuário: o dono gerencia os seus; o admin, os de qualquer um)
# ----------------------------------------------------------------------------
def _exigir_dono_do_favorito(ator: Ator, id_usuario: str) -> None:
    exigir(ator, Papel.USUARIO)
    if tem(ator, Papel.ADMIN):
        return
    proprio = _usuario_do_ator(ator)
    if proprio is None or id_texto(proprio["_id"]) != id_usuario:
        raise ErroNegocio("Você só pode gerenciar os seus próprios favoritos.")


def listar_favoritos(ator: Ator, id_usuario: str) -> Resultado[list[dict[str, Any]]]:
    def op() -> list[dict[str, Any]]:
        _exigir_dono_do_favorito(ator, id_usuario)
        return [_favorito(f) for f in dados.listar_favoritos(id_usuario)]
    return executar(BANCO, op)


def favoritar(ator: Ator, id_usuario: str, id_produto: str) -> Resultado[bool]:
    """``True`` se favoritou agora; ``False`` se já estava na lista."""
    def op() -> bool:
        _exigir_dono_do_favorito(ator, id_usuario)
        return dados.adicionar_favorito(id_usuario, id_produto)
    return executar(BANCO, op)


def desfavoritar(ator: Ator, id_usuario: str, id_produto: str) -> Resultado[bool]:
    """``True`` se removeu; ``False`` se o produto não estava na lista."""
    def op() -> bool:
        _exigir_dono_do_favorito(ator, id_usuario)
        return dados.remover_favorito(id_usuario, id_produto)
    return executar(BANCO, op)


# ----------------------------------------------------------------------------
# Vendedores
# ----------------------------------------------------------------------------
def listar_vendedores(termo: str | None = None, somente_ativos: bool = False) -> Resultado[list[dict[str, Any]]]:
    return executar(BANCO, lambda: [_vendedor(v) for v in dados.listar_vendedores(termo, somente_ativos)])


def produtos_do_vendedor(id_vendedor: str) -> Resultado[list[dict[str, Any]]]:
    return executar(BANCO, lambda: [_produto(p) for p in dados.buscar_produtos(id_vendedor=id_vendedor)])


def criar_vendedor(ator: Ator, nome_loja: str, cnpj: str) -> Resultado[str]:
    def op() -> str:
        exigir(ator, Papel.ADMIN)
        return id_texto(dados.inserir_vendedor(nome_loja, cnpj)["_id"])
    return executar(BANCO, op)


def atualizar_vendedor(ator: Ator, id_vendedor: str, nome_loja: str, status: str) -> Resultado[bool]:
    def op() -> bool:
        exigir(ator, Papel.ADMIN)
        return dados.atualizar_vendedor(id_vendedor, nome_loja, status)
    return executar(BANCO, op)


def excluir_vendedor(ator: Ator, id_vendedor: str) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        dados.excluir_vendedor(id_vendedor)
    return executar(BANCO, op)


# ----------------------------------------------------------------------------
# Pedidos
# ----------------------------------------------------------------------------
def compradores_permitidos(ator: Ator) -> Resultado[list[dict[str, Any]]]:
    """Admin pode comprar por qualquer usuário; usuário comum, só por si mesmo."""
    return listar_usuarios(ator)


def listar_pedidos(ator: Ator) -> Resultado[list[dict[str, Any]]]:
    def op() -> list[dict[str, Any]]:
        exigir(ator, Papel.USUARIO)
        if tem(ator, Papel.ADMIN):
            return [_pedido(p, True) for p in dados.listar_pedidos()]
        proprio = _usuario_do_ator(ator)
        return [_pedido(p, True) for p in dados.listar_pedidos(proprio["_id"])] if proprio else []
    return executar(BANCO, op)


def criar_pedido(ator: Ator, id_comprador: str, id_produto: str, quantidade: int) -> Resultado[dict[str, Any]]:
    """Mesma regra da CLI (baixa atômica de estoque). Usuário comum só compra por si mesmo."""
    def op() -> dict[str, Any]:
        exigir(ator, Papel.USUARIO)
        if not tem(ator, Papel.ADMIN):
            proprio = _usuario_do_ator(ator)
            if proprio is None or id_texto(proprio["_id"]) != id_comprador:
                raise ErroNegocio("Você só pode fazer pedidos em seu próprio nome.")
        pedido = dados.criar_pedido(id_comprador, id_produto, quantidade)
        return _pedido(pedido, False) | {"total": como_decimal(pedido["valor_total"])}
    return executar(BANCO, op)


def carregar_demonstracao(ator: Ator) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        dados.configurar_banco_dados()
        dados.carregar_demonstracao()
    return executar(BANCO, op)

