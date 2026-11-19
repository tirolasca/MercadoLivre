"""Validação de entrada e formatação de valores (CPF, CNPJ, e-mail, moeda, datas).

Módulo sem dependências externas e sem acesso a banco, o que facilita os testes.
Os validadores levantam ``ValueError`` com mensagem amigável e, quando fazem
sentido, devolvem o valor já normalizado.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ----------------------------------------------------------------------------
# Texto
# ----------------------------------------------------------------------------
def limpar(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def normalizar(valor: str) -> str:
    """Remove espaços nas pontas e espaços duplicados."""
    return " ".join(limpar(valor).split())


# ----------------------------------------------------------------------------
# Documentos
# ----------------------------------------------------------------------------
def _digito_cpf(base: str) -> int:
    pesos = range(len(base) + 1, 1, -1)
    return (sum(int(n) * p for n, p in zip(base, pesos)) * 10 % 11) % 10


def _digito_cnpj(base: str) -> int:
    pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
    resto = sum(int(n) * p for n, p in zip(base, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cpf_valido(valor: str) -> bool:
    d = digitos(valor)
    if len(d) != 11 or d == d[0] * 11:
        return False
    d1 = _digito_cpf(d[:9])
    d2 = _digito_cpf(d[:9] + str(d1))
    return d[9:] == f"{d1}{d2}"


def cnpj_valido(valor: str) -> bool:
    d = digitos(valor)
    if len(d) != 14 or d == d[0] * 14:
        return False
    d1 = _digito_cnpj(d[:12])
    d2 = _digito_cnpj(d[:12] + str(d1))
    return d[12:] == f"{d1}{d2}"


def validar_cpf(valor: str) -> str:
    if not cpf_valido(valor):
        raise ValueError("CPF inválido")
    return digitos(valor)


def validar_cnpj(valor: str) -> str:
    if not cnpj_valido(valor):
        raise ValueError("CNPJ inválido")
    return digitos(valor)


def validar_email(valor: str) -> str:
    valor = limpar(valor).lower()
    if not EMAIL_RE.match(valor):
        raise ValueError("E-mail inválido")
    return valor


def validar_cep(valor: str) -> str:
    d = digitos(valor)
    if len(d) != 8:
        raise ValueError("CEP deve ter 8 dígitos")
    return d


# ----------------------------------------------------------------------------
# Números
# ----------------------------------------------------------------------------
def converter_decimal(valor: str, minimo: Decimal = Decimal("0.01")) -> Decimal:
    """Aceita ``49,90``, ``49.90`` e ``1.234,56``."""
    texto = limpar(valor)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        raise ValueError("Informe um número válido, ex.: 49,90") from None
    if not numero.is_finite():
        raise ValueError("Informe um número válido, ex.: 49,90")
    if numero < minimo:
        raise ValueError(f"O valor deve ser maior ou igual a {minimo}")
    return numero.quantize(Decimal("0.01"))


def converter_inteiro(valor: str, minimo: int = 0, maximo: int | None = None) -> int:
    try:
        numero = int(limpar(valor))
    except ValueError:
        raise ValueError("Informe um número inteiro") from None
    if numero < minimo:
        raise ValueError(f"O valor deve ser maior ou igual a {minimo}")
    if maximo is not None and numero > maximo:
        raise ValueError(f"O valor deve ser menor ou igual a {maximo}")
    return numero


# ----------------------------------------------------------------------------
# Formatação
# ----------------------------------------------------------------------------
def formatar_moeda(valor: Any) -> str:
    """``Decimal``, ``Decimal128`` (BSON) ou número -> ``R$ 1.234,56``."""
    if hasattr(valor, "to_decimal"):
        valor = valor.to_decimal()
    texto = f"{Decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_cpf(valor: str) -> str:
    d = digitos(valor)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else valor


def formatar_cnpj(valor: str) -> str:
    d = digitos(valor)
    if len(d) != 14:
        return valor
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def formatar_cep(valor: str) -> str:
    d = digitos(valor)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else valor


def formatar_data(valor: datetime | None) -> str:
    """Datas dos bancos vêm em UTC (naive); exibe no fuso local."""
    if valor is None:
        return "-"
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone().strftime("%d/%m/%Y %H:%M")
