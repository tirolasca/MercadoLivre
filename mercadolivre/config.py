"""Configuração centralizada: um só lugar para ler variáveis, em qualquer ambiente.

* Desenvolvimento local: arquivo ``.env`` (carregado por ``conexoes.py``).
* Produção (Streamlit Community Cloud): Secrets, copiados para o ambiente por
  ``aplicar_secrets`` na inicialização da web. Variáveis já definidas no ambiente
  têm prioridade, então ``MONGODB_URI=... streamlit run ...`` continua funcionando.

Este módulo não importa o Streamlit: quem chama passa os Secrets já lidos.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

AMBIENTES = ("development", "production")

# Chaves que nunca devem aparecer em tela ou log, nem mascaradas parcialmente.
SEGREDOS = (
    "MONGODB_URI", "REDIS_URL", "REDIS_PASSWORD", "ASTRA_DB_TOKEN", "ASTRA_SCB_B64",
    "NEO4J_PASSWORD", "AUTH_SENHA_ADMIN_HASH", "AUTH_USUARIOS",
)


def ambiente() -> str:
    """``production`` (padrão, o mais restritivo) ou ``development``."""
    valor = os.getenv("APP_ENV", "production").strip().lower()
    return valor if valor in AMBIENTES else "production"


def em_producao() -> bool:
    return ambiente() == "production"


def modo_demo() -> bool:
    """Demo pública: visitantes veem os dados mascarados e não gravam nada."""
    return os.getenv("DEMO_MODE", "true").strip().lower() in ("1", "true", "sim", "yes")


def aplicar_secrets(secrets: Mapping[str, Any]) -> list[str]:
    """Copia Secrets (chaves de primeiro nível em maiúsculas) para ``os.environ`` sem sobrescrever.

    Devolve apenas os NOMES copiados (nunca os valores).
    """
    copiadas = []
    for chave, valor in secrets.items():
        if isinstance(valor, (str, int, float, bool)) and chave.upper() == chave and chave not in os.environ:
            os.environ[chave] = str(valor)
            copiadas.append(chave)
    return copiadas


def configurado(*nomes: str) -> bool:
    return all(os.getenv(n) for n in nomes)


def bancos_configurados() -> dict[str, bool]:
    """Quais bancos têm credenciais definidas (sem tentar conectar)."""
    return {
        "MongoDB": configurado("MONGODB_URI"),
        "Redis": configurado("REDIS_URL") or configurado("REDIS_HOST"),
        "Cassandra": configurado("ASTRA_DB_TOKEN") and (configurado("ASTRA_SCB_B64") or configurado("ASTRA_SCB_PATH")),
        "Neo4j": configurado("NEO4J_URI", "NEO4J_PASSWORD"),
    }
