"""Formatação e mascaramento de dados para exibição."""

from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal
from typing import Any

from bson import Decimal128, ObjectId

from mercadolivre.validadores import formatar_cnpj, formatar_cpf


def como_decimal(valor: Any) -> Decimal:
    """Converte ``Decimal128``/``float``/``int``/``str`` em ``Decimal`` (0 se vazio)."""
    if valor is None or valor == "":
        return Decimal("0")
    if isinstance(valor, Decimal128):
        return valor.to_decimal()
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def moeda(valor: Any) -> str:
    """R$ 1.234,56 (padrão brasileiro)."""
    texto = f"{como_decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def data_hora(valor: datetime | None) -> str:
    return valor.strftime("%d/%m/%Y %H:%M") if isinstance(valor, datetime) else "-"


def texto(valor: Any) -> str:
    """Texto seguro para inserir em HTML (escapa ``<``, ``>``, ``&`` e aspas)."""
    return html.escape("" if valor is None else str(valor), quote=True)


def id_texto(valor: Any) -> str:
    return str(valor) if isinstance(valor, ObjectId) else "" if valor is None else str(valor)


def mascara_cpf(cpf: str | None) -> str:
    """***.***.***-25: só os dois últimos dígitos."""
    digitos = "".join(c for c in (cpf or "") if c.isdigit())
    return f"***.***.***-{digitos[-2:]}" if len(digitos) == 11 else "***"


def mascara_email(email: str | None) -> str:
    """a***@dominio.com"""
    if not email or "@" not in email:
        return "***"
    local, dominio = email.split("@", 1)
    return f"{local[:1]}***@{dominio}"


def mascara_chave_sessao(chave: str) -> str:
    """session:a***@dominio.com (a chave de sessão contém o e-mail)."""
    prefixo, _, resto = chave.partition(":")
    return f"{prefixo}:{mascara_email(resto)}" if "@" in resto else chave


__all__ = ["como_decimal", "moeda", "data_hora", "texto", "id_texto", "mascara_cpf", "mascara_email", "mascara_chave_sessao", "formatar_cpf", "formatar_cnpj"]
