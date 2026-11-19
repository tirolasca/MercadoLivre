"""Resultado padronizado das operações e tratamento de erros dos bancos.

Cada chamada da interface passa por ``executar``: ela captura falhas de banco, rede
e configuração, registra o detalhe técnico no log (sem credenciais) e devolve uma
mensagem compreensível, sem expor informações internas. Uma falha em um banco não
derruba a página inteira e não afeta os outros bancos.

Há também um disjuntor simples por banco: após uma falha, novas chamadas ao mesmo banco
são recusadas por alguns segundos, para a interface não ficar esperando o timeout de um
serviço que está fora do ar (Aura/Astra gratuitos hibernam por inatividade).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from mercadolivre import config
from mercadolivre.catalogo_dados import ErroNegocio
from web.auth.permissoes import PermissaoNegada

log = logging.getLogger("mercadolivre.web")
T = TypeVar("T")

PAUSA_APOS_FALHA_S = 20
_lock = threading.Lock()
_falhou_em: dict[str, float] = {}


@dataclass(frozen=True)
class Resultado(Generic[T]):
    ok: bool
    dados: T | None = None
    erro: str | None = None
    indisponivel: bool = False  # True quando o problema é o serviço, não o pedido do usuário

    @staticmethod
    def sucesso(dados: T) -> "Resultado[T]":
        return Resultado(True, dados)


def _tipos_de_falha_de_infra() -> tuple[type[BaseException], ...]:
    """Exceções de drivers e rede, importadas só se o driver estiver instalado."""
    tipos: list[type[BaseException]] = [OSError, TimeoutError, ConnectionError]
    try:
        from pymongo.errors import PyMongoError
        tipos.append(PyMongoError)
    except ImportError:  # pragma: no cover
        pass
    try:
        from redis.exceptions import RedisError
        tipos.append(RedisError)
    except ImportError:  # pragma: no cover
        pass
    try:
        from cassandra import DriverException
        from cassandra.cluster import NoHostAvailable
        tipos += [DriverException, NoHostAvailable]
    except ImportError:  # pragma: no cover
        pass
    try:
        from neo4j.exceptions import DriverError, Neo4jError
        tipos += [DriverError, Neo4jError]
    except ImportError:  # pragma: no cover
        pass
    return tuple(tipos)


def sem_segredos(texto: str) -> str:
    """Remove do texto qualquer valor secreto configurado (defesa extra para logs)."""
    for nome in config.SEGREDOS:
        valor = os.getenv(nome, "")
        if len(valor) >= 6:
            texto = texto.replace(valor, "***")
    return texto


def _pausado(banco: str) -> bool:
    with _lock:
        t = _falhou_em.get(banco)
        return t is not None and time.monotonic() - t < PAUSA_APOS_FALHA_S


def _marcar_falha(banco: str) -> None:
    with _lock:
        _falhou_em[banco] = time.monotonic()


def _marcar_ok(banco: str) -> None:
    with _lock:
        _falhou_em.pop(banco, None)


def reiniciar_disjuntores() -> None:
    with _lock:
        _falhou_em.clear()


def executar(banco: str, funcao: Callable[..., T], *args: Any, **kwargs: Any) -> Resultado[T]:
    """Roda ``funcao`` protegendo a interface de falhas do ``banco``."""
    if _pausado(banco):
        return Resultado(False, erro=f"{banco} está indisponível no momento. Tentaremos de novo em instantes.", indisponivel=True)
    try:
        dados = funcao(*args, **kwargs)
    except (ErroNegocio, PermissaoNegada) as exc:
        return Resultado(False, erro=str(exc))
    except ValueError as exc:  # validação de entrada (CPF, preço, quantidade...)
        return Resultado(False, erro=str(exc))
    except RuntimeError as exc:  # configuração ausente (ex.: "Defina NEO4J_URI...")
        log.warning("%s: configuração incompleta: %s", banco, sem_segredos(str(exc)))
        _marcar_falha(banco)
        return Resultado(False, erro=f"{banco} não está configurado nesta instalação.", indisponivel=True)
    except _tipos_de_falha_de_infra() as exc:
        log.error("%s: falha de infraestrutura: %s: %s", banco, type(exc).__name__, sem_segredos(str(exc))[:300])
        _marcar_falha(banco)
        return Resultado(False, erro=f"Não foi possível acessar o {banco}. O serviço pode estar fora do ar ou hibernado.", indisponivel=True)
    except Exception:  # noqa: BLE001 - última barreira: registra o traceback e não deixa a página inteira cair
        log.exception("%s: erro inesperado", banco)
        return Resultado(False, erro="Ocorreu um erro inesperado ao processar o pedido. Os detalhes foram registrados no log.")
    _marcar_ok(banco)
    return Resultado.sucesso(dados)
