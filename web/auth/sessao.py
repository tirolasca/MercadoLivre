"""Login web com sessão no servidor.

O navegador guarda apenas um token opaco (em ``st.session_state``, isolado por aba/usuário).
Quem o token representa vive no servidor, no Redis, com TTL deslizante; o Redis guarda o
*hash* do token, então um dump do Redis não revela tokens válidos. Se o Redis estiver
indisponível, a autenticação continua funcionando com um armazém em memória do processo
(sessões se perdem ao reiniciar). Isso mantém a aplicação utilizável com um banco fora do ar.

A proteção contra tentativas inválidas reutiliza o contador por usuário do Redis
(``sessoes_dados``), com prefixo próprio, e também tem fallback em memória.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass

from mercadolivre import sessoes_dados as redis_dados

from .permissoes import VISITANTE, Ator, Papel
from .senhas import verificar
from .usuarios import ContaWeb

log = logging.getLogger(__name__)

PREFIXO_SESSAO = "web_sessao:"
PREFIXO_FALHAS = "web_login_falhas:"


def ttl_sessao() -> int:
    try:
        return max(60, int(os.getenv("WEB_SESSION_TTL", 1800)))
    except ValueError:
        return 1800


def _id(token: str) -> str:
    return PREFIXO_SESSAO + hashlib.sha256(token.encode()).hexdigest()


# ----------------------------------------------------------------------------
# Armazém de reserva (memória do processo)
# ----------------------------------------------------------------------------
class _Memoria:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sessoes: dict[str, tuple[float, str]] = {}
        self.falhas: dict[str, tuple[int, float]] = {}

    def limpar(self) -> None:
        agora = time.time()
        self.sessoes = {k: v for k, v in self.sessoes.items() if v[0] > agora}
        self.falhas = {k: v for k, v in self.falhas.items() if v[1] > agora}


_memoria = _Memoria()


def _redis_ok() -> bool:
    try:
        redis_dados.r().ping()
        return True
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/driver cai na reserva
        log.warning("Redis indisponível para autenticação (%s); usando memória.", type(exc).__name__)
        return False


# ----------------------------------------------------------------------------
# Tentativas inválidas
# ----------------------------------------------------------------------------
def _espera_bloqueio(usuario: str) -> int:
    if _redis_ok():
        return redis_dados.bloqueado(usuario, PREFIXO_FALHAS)
    with _memoria.lock:
        _memoria.limpar()
        n, ate = _memoria.falhas.get(usuario, (0, 0))
        return max(int(ate - time.time()), 0) if n >= redis_dados.MAX_FALHAS else 0


def _registrar_falha(usuario: str) -> None:
    if _redis_ok():
        redis_dados.registrar_falha(usuario, PREFIXO_FALHAS)
        return
    with _memoria.lock:
        n, ate = _memoria.falhas.get(usuario, (0, 0))
        _memoria.falhas[usuario] = (n + 1, ate if n else time.time() + redis_dados.JANELA_FALHAS)


def _limpar_falhas(usuario: str) -> None:
    if _redis_ok():
        redis_dados.limpar_falhas(usuario, PREFIXO_FALHAS)
    with _memoria.lock:
        _memoria.falhas.pop(usuario, None)


# ----------------------------------------------------------------------------
# Sessões
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class ResultadoEntrada:
    ok: bool
    token: str | None = None
    mensagem: str = ""


def entrar(usuario: str, senha: str, contas: dict[str, ContaWeb]) -> ResultadoEntrada:
    usuario = (usuario or "").strip().lower()
    if not usuario or not senha:
        return ResultadoEntrada(False, mensagem="Informe usuário e senha.")
    if espera := _espera_bloqueio(usuario):
        return ResultadoEntrada(False, mensagem=f"Muitas tentativas. Tente novamente em {espera}s.")
    conta = contas.get(usuario)
    # verificar() roda mesmo sem conta, para não revelar por tempo se o usuário existe
    senha_ok = verificar(senha, conta.senha_hash if conta else None)
    if conta is None or not senha_ok:
        _registrar_falha(usuario)
        return ResultadoEntrada(False, mensagem="Usuário ou senha incorretos.")
    _limpar_falhas(usuario)
    token = secrets.token_urlsafe(32)
    valor = json.dumps({"usuario": conta.usuario, "papel": conta.papel.value, "email": conta.email})
    ttl = ttl_sessao()
    if _redis_ok():
        redis_dados.r().set(_id(token), valor, ex=ttl)
    else:
        with _memoria.lock:
            _memoria.limpar()
            _memoria.sessoes[_id(token)] = (time.time() + ttl, valor)
    return ResultadoEntrada(True, token)


def ator_do_token(token: str | None, renovar: bool = True) -> Ator:
    """Quem é o dono do token. Token ausente, inválido ou expirado = visitante."""
    if not token:
        return VISITANTE
    chave, valor = _id(token), None
    if _redis_ok():
        valor = redis_dados.r().get(chave)
        if valor and renovar:
            redis_dados.r().expire(chave, ttl_sessao())
    if valor is None:
        with _memoria.lock:
            _memoria.limpar()
            achado = _memoria.sessoes.get(chave)
            if achado:
                valor = achado[1]
                if renovar:
                    _memoria.sessoes[chave] = (time.time() + ttl_sessao(), valor)
    if valor is None:
        return VISITANTE
    try:
        dados = json.loads(valor)
        return Ator(dados["usuario"], Papel(dados["papel"]), dados.get("email"))
    except (ValueError, KeyError):
        return VISITANTE


def sair(token: str | None) -> None:
    if not token:
        return
    chave = _id(token)
    if _redis_ok():
        redis_dados.r().delete(chave)
    with _memoria.lock:
        _memoria.sessoes.pop(chave, None)
