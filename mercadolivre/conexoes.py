
"""Conexões com MongoDB, Redis, Cassandra (DataStax Astra) e Neo4j (AuraDB).

Todas são criadas sob demanda (lazy) e reaproveitadas durante a execução, então
importar este módulo não abre conexão nenhuma e quem usa só um banco não precisa
dos drivers dos outros. Configuração via variáveis de ambiente / arquivo ``.env``
(na web, os Secrets do Streamlit são copiados para o ambiente por ``config.py``).

Os clientes ficam num cache de processo: todos são thread-safe e compartilhados
entre as sessões da web. Eles não guardam nada de nenhum usuário (o estado de
login vive no Redis, por chave de sessão).
"""

from __future__ import annotations

import atexit
import base64
import os
import tempfile
from functools import cache
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:  # pragma: no cover
    from cassandra.cluster import Cluster, Session
    from neo4j import Driver
    from pymongo import MongoClient
    from pymongo.database import Database
    from redis import Redis

load_dotenv()

MONGO_TIMEOUT_MS = 5000
TIMEOUT_S = 10  # conexão e consultas dos demais bancos


def cassandra_keyspace() -> str:
    return os.getenv("ASTRA_KEYSPACE", "mercadolivre")


def _limite_pool(nome: str, padrao: int) -> int:
    """Tamanho máximo do pool. Os planos gratuitos limitam conexões."""
    try:
        return max(1, int(os.getenv(nome, padrao)))
    except ValueError:
        return padrao


# ----------------------------------------------------------------------------
# MongoDB
# ----------------------------------------------------------------------------
@cache
def mongo_cliente() -> "MongoClient":
    import pymongo
    from pymongo.server_api import ServerApi

    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    opcoes = {
        "serverSelectionTimeoutMS": MONGO_TIMEOUT_MS,
        "connectTimeoutMS": MONGO_TIMEOUT_MS,
        "socketTimeoutMS": TIMEOUT_S * 1000,
        "maxPoolSize": _limite_pool("MONGODB_MAX_POOL", 10),
    }
    if uri.startswith("mongodb+srv"):  # Atlas
        opcoes["server_api"] = ServerApi("1")
    return pymongo.MongoClient(uri, **opcoes)


def mongo_db() -> "Database":
    return mongo_cliente()[os.getenv("MONGODB_DATABASE", "mercadolivre")]


# ----------------------------------------------------------------------------
# Redis
# ----------------------------------------------------------------------------
@cache
def redis_cliente() -> "Redis":
    import redis

    comum = {
        "decode_responses": True,
        "socket_connect_timeout": TIMEOUT_S,
        "socket_timeout": TIMEOUT_S,
        "health_check_interval": 30,
        "max_connections": _limite_pool("REDIS_MAX_CONNECTIONS", 10),
    }

    url = os.getenv("REDIS_URL")
    if url:
        return redis.Redis(
            connection_pool=redis.ConnectionPool.from_url(url, **comum)
        )

    opcoes = {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "password": os.getenv("REDIS_PASSWORD") or None,
        **comum,
    }

    ssl_ativado = (
        os.getenv("REDIS_SSL", "false").strip().lower() == "true"
    )

    if ssl_ativado:
        opcoes["connection_class"] = redis.SSLConnection

    return redis.Redis(
        connection_pool=redis.ConnectionPool(**opcoes)
    )


# ----------------------------------------------------------------------------
# Cassandra (Astra DB)
# ----------------------------------------------------------------------------
def _caminho_bundle() -> str:
    """Secure Connect Bundle: caminho em ``ASTRA_SCB_PATH`` ou conteúdo em base64 em ``ASTRA_SCB_B64``.

    O base64 existe para hospedagens sem upload de arquivos (Streamlit Community Cloud):
    o bundle é gravado em um arquivo temporário (permissão 600) removido ao encerrar.
    """
    caminho, b64 = os.getenv("ASTRA_SCB_PATH"), os.getenv("ASTRA_SCB_B64")
    if caminho and os.path.isfile(caminho):
        return caminho
    if b64:
        try:
            conteudo = base64.b64decode("".join(b64.split()), validate=True)
        except ValueError as exc:
            raise RuntimeError("ASTRA_SCB_B64 não é um base64 válido.") from exc
        fd, destino = tempfile.mkstemp(suffix=".zip", prefix="scb-")
        with os.fdopen(fd, "wb") as arq:
            arq.write(conteudo)
        atexit.register(lambda: os.path.exists(destino) and os.remove(destino))
        return destino
    if caminho:
        raise RuntimeError(f"Secure Connect Bundle não encontrado em: {caminho}")
    raise RuntimeError("Defina ASTRA_SCB_PATH (ou ASTRA_SCB_B64) e ASTRA_DB_TOKEN.")


@cache
def cassandra_cluster() -> "Cluster":
    from cassandra.auth import PlainTextAuthProvider
    from cassandra.cluster import Cluster

    token = os.getenv("ASTRA_DB_TOKEN")
    if not token:
        raise RuntimeError("Defina ASTRA_DB_TOKEN.")

    return Cluster(
        cloud={"secure_connect_bundle": _caminho_bundle()},
        auth_provider=PlainTextAuthProvider("token", token),
        connect_timeout=TIMEOUT_S,
    )


@cache
def cassandra_sessao() -> "Session":
    sessao = cassandra_cluster().connect(cassandra_keyspace())
    sessao.default_timeout = TIMEOUT_S
    return sessao


# ----------------------------------------------------------------------------
# Neo4j (AuraDB)
# ----------------------------------------------------------------------------
@cache
def neo4j_driver() -> "Driver":
    from neo4j import GraphDatabase

    uri, senha = os.getenv("NEO4J_URI"), os.getenv("NEO4J_PASSWORD")
    if not uri or not senha:
        raise RuntimeError("Defina NEO4J_URI e NEO4J_PASSWORD.")

    return GraphDatabase.driver(
        uri,
        auth=(os.getenv("NEO4J_USERNAME", "neo4j"), senha),
        connection_timeout=TIMEOUT_S,
        max_transaction_retry_time=3,
        max_connection_pool_size=_limite_pool("NEO4J_MAX_POOL", 10),
    )


def neo4j_banco() -> str:
    return os.getenv("NEO4J_DATABASE", "neo4j")


# ----------------------------------------------------------------------------
# Encerramento
# ----------------------------------------------------------------------------
def fechar_conexoes() -> None:
    """Fecha apenas as conexões que foram realmente abertas."""
    if mongo_cliente.cache_info().currsize:
        mongo_cliente().close()
        mongo_cliente.cache_clear()

    if redis_cliente.cache_info().currsize:
        redis_cliente().close()
        redis_cliente.cache_clear()

    if cassandra_cluster.cache_info().currsize:
        cassandra_cluster().shutdown()
        cassandra_sessao.cache_clear()
        cassandra_cluster.cache_clear()

    if neo4j_driver.cache_info().currsize:
        neo4j_driver().close()
        neo4j_driver.cache_clear()
