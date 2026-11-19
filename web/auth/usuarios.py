"""Contas da aplicação web, vindas de configuração (nunca do código).

Formato (variável ``AUTH_USUARIOS`` em JSON, ou tabela ``[[auth.usuarios]]`` nos Secrets)::

    [{"usuario": "admin", "papel": "admin", "email": "admin@exemplo.com", "senha_hash": "pbkdf2_sha256$..."}]

Gere o hash com ``python -m web.auth.senhas``. Papéis válidos: ``usuario`` e ``admin``.
Em produção só existem as contas configuradas; as contas de demonstração do
desenvolvimento nunca são carregadas.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterable

from mercadolivre import config

from .permissoes import Papel
from .senhas import gerar_hash

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContaWeb:
    usuario: str
    papel: Papel
    senha_hash: str
    email: str | None = None


def _validar(bruto: dict[str, Any]) -> ContaWeb | None:
    usuario = str(bruto.get("usuario", "")).strip().lower()
    papel = str(bruto.get("papel", "usuario")).strip().lower()
    senha_hash = str(bruto.get("senha_hash", ""))
    if not usuario or papel not in (Papel.USUARIO.value, Papel.ADMIN.value) or not senha_hash.startswith("pbkdf2_sha256$"):
        log.warning("Conta web ignorada: campos inválidos (usuario=%r).", usuario)
        return None
    email = str(bruto.get("email", "")).strip().lower() or None
    return ContaWeb(usuario, Papel(papel), senha_hash, email)


def _contas_de_desenvolvimento() -> list[ContaWeb]:
    """SOMENTE com ``APP_ENV=development``: contas descartáveis para testar localmente."""
    from mercadolivre.sessoes_dados import USUARIOS_DEMO

    contas = [ContaWeb("admin", Papel.ADMIN, gerar_hash("admin-dev-local", iteracoes=1000), "admin@dev.local")]
    contas += [ContaWeb(email, Papel.USUARIO, gerar_hash(senha.ljust(10, "_"), iteracoes=1000), email) for email, senha in USUARIOS_DEMO.items()]
    return contas


def carregar_contas(secrets_auth: Iterable[dict[str, Any]] | None = None) -> dict[str, ContaWeb]:
    brutas: list[dict[str, Any]] = list(secrets_auth or [])
    if (env := os.getenv("AUTH_USUARIOS")):
        try:
            brutas += json.loads(env)
        except json.JSONDecodeError:
            log.error("AUTH_USUARIOS não é um JSON válido; ignorada.")
    contas = {c.usuario: c for b in brutas if (c := _validar(dict(b)))}
    if not contas and not config.em_producao():
        contas = {c.usuario: c for c in _contas_de_desenvolvimento()}
    return contas
