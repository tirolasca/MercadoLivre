"""Papéis e permissões. Toda checagem de acesso passa por aqui."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Papel(str, Enum):
    VISITANTE = "visitante"
    USUARIO = "usuario"
    ADMIN = "admin"


_ORDEM = {Papel.VISITANTE: 0, Papel.USUARIO: 1, Papel.ADMIN: 2}


@dataclass(frozen=True)
class Ator:
    """Quem está agindo. ``usuario``/``email`` são ``None`` para visitantes."""

    usuario: str | None
    papel: Papel
    email: str | None = None


VISITANTE = Ator(None, Papel.VISITANTE)


class PermissaoNegada(Exception):
    """O ator não tem papel suficiente para a operação."""


def tem(ator: Ator, minimo: Papel) -> bool:
    return _ORDEM[ator.papel] >= _ORDEM[minimo]


def exigir(ator: Ator, minimo: Papel) -> None:
    """Chamada no início de cada operação de escrita/consulta sensível dos serviços."""
    if not tem(ator, minimo):
        raise PermissaoNegada("Você não tem permissão para esta operação." if ator.papel != Papel.VISITANTE else "Faça login para continuar.")
