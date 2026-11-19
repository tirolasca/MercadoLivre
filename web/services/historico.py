"""Serviço do Cassandra (histórico de compras) para a web.

Usa as consultas de ``mercadolivre.historico``, cada uma já desenhada para uma tabela
(sem JOIN). Visitantes consultam apenas o catálogo por categoria/prefixo; compras de
um usuário exigem login, e o usuário comum só vê as próprias.
"""

from __future__ import annotations

from typing import Any

from mercadolivre import historico as cass
from web.auth.permissoes import Ator, Papel, PermissaoNegada, exigir, tem
from web.utils.formatacao import como_decimal

from .resultado import Resultado, executar

BANCO = "Cassandra"


def categorias() -> Resultado[list[str]]:
    return executar(BANCO, cass.listar_categorias)


def produtos_da_categoria(categoria: str, prefixo: str | None = None) -> Resultado[list[dict[str, Any]]]:
    def op() -> list[dict[str, Any]]:
        return [
            {"id_produto": str(r.id_produto), "titulo": r.titulo, "preco": como_decimal(r.preco)}
            for r in cass.listar_produtos_categoria(categoria, (prefixo or "").strip() or None)
        ]
    return executar(BANCO, op)


def usuarios(ator: Ator) -> Resultado[list[dict[str, Any]]]:
    """Admin: todos. Usuário comum: nenhum (a página usa o CPF do próprio usuário)."""
    def op() -> list[dict[str, Any]]:
        exigir(ator, Papel.ADMIN)
        return [{"cpf": r.cpf, "nome": f"{r.nome} {r.sobrenome}", "email": r.email} for r in cass.listar_usuarios()]
    return executar(BANCO, op)


def compras_do_usuario(ator: Ator, cpf: str) -> Resultado[list[dict[str, Any]]]:
    def op() -> list[dict[str, Any]]:
        exigir(ator, Papel.USUARIO)
        if not tem(ator, Papel.ADMIN) and not cpf_do_ator(ator, cpf):
            raise PermissaoNegada("Você só pode consultar as suas próprias compras.")
        return [
            {"id_compra": str(r.id_compra), "data": r.data_compra, "titulo": r.titulo, "quantidade": r.quantidade, "total": como_decimal(r.valor_total), "status": r.status}
            for r in cass.listar_compras(cpf)
        ]
    return executar(BANCO, op)


def cpf_do_ator(ator: Ator, cpf: str) -> bool:
    """O CPF consultado pertence ao usuário logado? (e-mail da conta = e-mail do cadastro)."""
    if not ator.email:
        return False
    achado = cass.buscar_usuario(cpf)
    return bool(achado and (achado.email or "").lower() == ator.email.lower())


def cpf_do_proprio_usuario(ator: Ator) -> Resultado[str | None]:
    """Procura, no Cassandra, o cadastro cujo e-mail é o da conta logada."""
    def op() -> str | None:
        exigir(ator, Papel.USUARIO)
        if not ator.email:
            return None
        return next((r.cpf for r in cass.listar_usuarios() if (r.email or "").lower() == ator.email.lower()), None)
    return executar(BANCO, op)


def consulta_sem_chave(titulo: str) -> Resultado[str]:
    """Demonstra a recusa do Cassandra para consultas fora da chave de partição."""
    return executar(BANCO, lambda: cass.consulta_sem_chave(titulo))


def carregar_demonstracao(ator: Ator) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.ADMIN)
        cass.carregar_demonstracao()
    return executar(BANCO, op)


MODELAGEM = [
    ("usuario", "cpf", "—", "Dados de um usuário pelo CPF"),
    ("vendedor", "cnpj", "—", "Dados de uma loja pelo CNPJ"),
    ("produto", "id_produto", "—", "Dados de um produto pelo id"),
    ("produto_por_categoria", "id_categoria", "titulo, id_produto", "Produtos de uma categoria em ordem alfabética (e por prefixo)"),
    ("compra", "id_compra", "—", "Dados de uma compra pelo id"),
    ("compra_por_usuario", "cpf", "data_compra DESC, id_compra", "Compras de um usuário, da mais nova para a mais antiga"),
]
