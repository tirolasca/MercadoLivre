"""Serviço de diagnóstico: usa a lógica de ``mercadolivre.diagnostico``.

O detalhe técnico (nome do banco, mensagem do driver) só vai para o administrador;
os demais veem apenas ONLINE/FALHA e a latência.
"""

from __future__ import annotations

from typing import Any

from mercadolivre import config, conexoes, diagnostico
from web.auth.permissoes import Ator, Papel, tem

from .resultado import reiniciar_disjuntores, sem_segredos

OPERACOES = {
    "MongoDB": "Catálogo, usuários, vendedores, favoritos e pedidos",
    "Redis": "Sessões, autenticação e cache",
    "Cassandra (Astra DB)": "Histórico de compras",
    "Neo4j (AuraDB)": "Grafo de relacionamentos",
}
_CONFIG = {"MongoDB": "MongoDB", "Redis": "Redis", "Cassandra (Astra DB)": "Cassandra", "Neo4j (AuraDB)": "Neo4j"}


def verificar(ator: Ator) -> list[dict[str, Any]]:
    configurados = config.bancos_configurados()
    linhas = []
    for nome, fn in diagnostico.VERIFICACOES:
        if not configurados.get(_CONFIG[nome], True):
            linhas.append({"servico": nome, "ok": False, "ms": None, "detalhe": "Credenciais não configuradas.", "operacoes": OPERACOES[nome], "configurado": False})
            continue
        r = diagnostico.verificar_um(nome, fn)
        detalhe = sem_segredos(str(r["detalhe"])) if tem(ator, Papel.ADMIN) else ("Operando normalmente." if r["ok"] else "Serviço indisponível no momento.")
        linhas.append({"servico": nome, "ok": r["ok"], "ms": r["ms"], "detalhe": detalhe, "operacoes": OPERACOES[nome], "configurado": True})
    return linhas


def reiniciar_conexoes(ator: Ator) -> None:
    """Descarta as conexões em cache (útil depois que um banco gratuito 'acorda')."""
    if tem(ator, Papel.ADMIN):
        conexoes.fechar_conexoes()
        reiniciar_disjuntores()
