"""Serviço do Neo4j (grafo de relacionamentos) para a web.

Reaproveita as consultas de ``mercadolivre.grafo`` e a nova ``subgrafo``. Visitantes só
recebem a parte pública do grafo (Loja -> Produto -> Categoria), sem nós de usuário
ou de compra e sem CPF/e-mail.
"""

from __future__ import annotations

from typing import Any

from mercadolivre import grafo as neo
from web.auth.permissoes import Ator, Papel, PermissaoNegada, exigir, tem

from .resultado import Resultado, executar

BANCO = "Neo4j"


def resumo() -> Resultado[dict[str, list[dict[str, Any]]]]:
    def op() -> dict[str, list[dict[str, Any]]]:
        nos, relacoes = neo.resumo_do_grafo()
        return {"nos": nos, "relacoes": relacoes}
    return executar(BANCO, op)


def subgrafo(ator: Ator, cpf: str | None = None) -> Resultado[dict[str, list[dict[str, Any]]]]:
    """Visitante: grafo público. Usuário comum: público + a própria árvore. Admin: tudo."""
    def op() -> dict[str, list[dict[str, Any]]]:
        pessoas = tem(ator, Papel.USUARIO)
        if cpf is not None:
            exigir(ator, Papel.USUARIO)
            if not tem(ator, Papel.ADMIN) and not _cpf_e_do_ator(ator, cpf):
                raise PermissaoNegada("Você só pode explorar as suas próprias compras.")
        elif pessoas and not tem(ator, Papel.ADMIN):
            pessoas = False  # usuário comum vê o grafo público até escolher a própria árvore
        nos, arestas = neo.subgrafo(cpf=cpf, com_pessoas=pessoas)
        return {"nos": nos, "arestas": arestas}
    return executar(BANCO, op)


def _cpf_e_do_ator(ator: Ator, cpf: str) -> bool:
    if not ator.email:
        return False
    u = neo.buscar_usuario(cpf)
    return bool(u and (u["email"] or "").lower() == ator.email.lower())


def cpf_do_proprio_usuario(ator: Ator) -> Resultado[str | None]:
    def op() -> str | None:
        exigir(ator, Papel.USUARIO)
        if not ator.email:
            return None
        return next((u["cpf"] for u in neo.buscar_usuarios(ator.email) if (u["email"] or "").lower() == ator.email.lower()), None)
    return executar(BANCO, op)


def buscar_usuarios(ator: Ator, termo: str | None) -> Resultado[list[dict[str, Any]]]:
    def op() -> list[dict[str, Any]]:
        exigir(ator, Papel.ADMIN)
        return neo.buscar_usuarios(termo)
    return executar(BANCO, op)


def buscar_vendedores(termo: str | None) -> Resultado[list[dict[str, Any]]]:
    return executar(BANCO, lambda: neo.buscar_vendedores(termo))


def buscar_produtos(termo: str | None = None, categoria: str | None = None, cnpj: str | None = None) -> Resultado[list[dict[str, Any]]]:
    return executar(BANCO, lambda: neo.buscar_produtos(termo, categoria, cnpj))


def categorias() -> Resultado[list[str]]:
    return executar(BANCO, neo.listar_categorias)


def compras(ator: Ator, cpf: str | None = None, id_produto: str | None = None) -> Resultado[list[dict[str, Any]]]:
    """Caminho Usuário -> Compra -> Produto -> Loja. Usuário comum: apenas o próprio CPF."""
    def op() -> list[dict[str, Any]]:
        exigir(ator, Papel.USUARIO)
        if not tem(ator, Papel.ADMIN) and (cpf is None or not _cpf_e_do_ator(ator, cpf)):
            raise PermissaoNegada("Você só pode consultar as suas próprias compras.")
        return neo.buscar_compras(cpf=cpf, id_produto=id_produto)
    return executar(BANCO, op)


def carregar_demonstracao(ator: Ator) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        neo.carregar_demonstracao()
    return executar(BANCO, op)

