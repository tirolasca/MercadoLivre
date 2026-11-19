"""Serviço do Redis: estado, sessões, TTL, tentativas de login e fluxo de cache.

A demonstração usa chaves próprias (``demo_sessao:*``), separadas das sessões de login
da aplicação (``web_sessao:*``), e nunca expõe o conteúdo das sessões. Os e-mails
presentes nas chaves aparecem mascarados para quem não é administrador.
"""

from __future__ import annotations

import secrets
from typing import Any

from redis.exceptions import ResponseError

from mercadolivre import sessoes_dados as redis_dados
from web.auth.permissoes import Ator, Papel, exigir, tem
from web.utils.formatacao import mascara_chave_sessao

from .resultado import Resultado, executar

BANCO = "Redis"
PREFIXO_DEMO = "demo_sessao:"
MAX_DEMOS = 20  # evita encher os 30 MB do plano gratuito


def estado() -> Resultado[dict[str, Any]]:
    def op() -> dict[str, Any]:
        cliente = redis_dados.r()
        cliente.ping()
        try:
            memoria = cliente.info("memory").get("used_memory_human", "n/d")
        except ResponseError:  # alguns planos/servidores restringem o INFO
            memoria = "n/d"
        return {
            "sessoes_login": sum(1 for _ in cliente.scan_iter(match="web_sessao:*", count=200)),
            "sessoes_demo": sum(1 for _ in cliente.scan_iter(match=f"{PREFIXO_DEMO}*", count=200)),
            "memoria_usada": memoria,
            "ttl_padrao": redis_dados.TTL,
            "max_falhas": redis_dados.MAX_FALHAS,
            "janela_falhas": redis_dados.JANELA_FALHAS,
        }
    return executar(BANCO, op)


def sessoes_ativas(ator: Ator) -> Resultado[list[dict[str, Any]]]:
    """Sessões de demonstração e de login, com TTL. Chaves mascaradas fora do admin; sem conteúdo."""
    def op() -> list[dict[str, Any]]:
        linhas = []
        for prefixo, tipo in (("session:", "login (CLI)"), (PREFIXO_DEMO, "demonstração"), ("web_sessao:", "login (web)")):
            if prefixo == "web_sessao:" and not tem(ator, Papel.ADMIN):
                continue  # o identificador é um hash de token: só o admin precisa ver
            for s in redis_dados.listar_sessoes(prefixo):
                chave = s["chave"] if tem(ator, Papel.ADMIN) else mascara_chave_sessao(s["chave"])
                linhas.append({"chave": chave if prefixo != "web_sessao:" else chave[:22] + "…", "tipo": tipo, "ttl": s["ttl"]})
        return linhas
    return executar(BANCO, op)


def criar_sessao_demo(ator: Ator) -> Resultado[str]:
    """Cria uma sessão descartável para mostrar TTL (qualquer usuário autenticado)."""
    def op() -> str:
        exigir(ator, Papel.USUARIO)
        if len(redis_dados.listar_sessoes(PREFIXO_DEMO)) >= MAX_DEMOS:
            raise ValueError("Limite de sessões de demonstração atingido. Aguarde algumas expirarem.")
        chave = f"{PREFIXO_DEMO}{secrets.token_hex(4)}"
        redis_dados.criar_sessao(chave, {"demo": True})
        return chave
    return executar(BANCO, op)


def ttl_da_sessao(chave: str) -> Resultado[int]:
    return executar(BANCO, lambda: redis_dados.ttl_restante(chave) if chave.startswith(PREFIXO_DEMO) else 0)


def renovar_sessao_demo(ator: Ator, chave: str) -> Resultado[bool]:
    def op() -> bool:
        exigir(ator, Papel.USUARIO)
        return chave.startswith(PREFIXO_DEMO) and redis_dados.renovar_sessao(chave)
    return executar(BANCO, op)


def encerrar_sessao_demo(ator: Ator, chave: str) -> Resultado[None]:
    def op() -> None:
        exigir(ator, Papel.USUARIO)
        if chave.startswith(PREFIXO_DEMO):
            redis_dados.logout(chave)
    return executar(BANCO, op)


def tentativas_de_login(ator: Ator) -> Resultado[list[dict[str, Any]]]:
    """Contadores de tentativas inválidas ativos (usuário mascarado fora do admin)."""
    def op() -> list[dict[str, Any]]:
        linhas = []
        for prefixo in ("web_login_falhas:", "login_falhas:"):
            for chave in redis_dados.r().scan_iter(match=f"{prefixo}*", count=100):
                nome = chave[len(prefixo):]
                tentativas, restante = redis_dados.falhas_de(nome, prefixo)
                linhas.append({
                    "usuario": nome if tem(ator, Papel.ADMIN) else mascara_chave_sessao(f"x:{nome}")[2:],
                    "tentativas": tentativas, "limite": redis_dados.MAX_FALHAS, "bloqueado": tentativas >= redis_dados.MAX_FALHAS, "reinicia_em": restante,
                })
        return linhas
    return executar(BANCO, op)


def executar_fluxo(ator: Ator) -> Resultado[list[tuple[str, str, Any]]]:
    """Fluxo MongoDB -> Redis -> MongoDB (move 2 produtos e devolve). Somente admin."""
    def op() -> list[tuple[str, str, Any]]:
        exigir(ator, Papel.ADMIN)
        eventos: list[tuple[str, str, Any]] = []
        redis_dados.executar_fluxo(lambda etapa, msg, dados=None: eventos.append((etapa, msg, dados)))
        return eventos
    return executar(BANCO, op)
