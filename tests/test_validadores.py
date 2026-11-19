from datetime import datetime
from decimal import Decimal

import pytest

from mercadolivre.validadores import (
    converter_decimal,
    converter_inteiro,
    cnpj_valido,
    cpf_valido,
    formatar_cnpj,
    formatar_cpf,
    formatar_data,
    formatar_moeda,
    normalizar,
    validar_cep,
    validar_cpf,
    validar_email,
)


@pytest.mark.parametrize("cpf", ["529.982.247-25", "52998224725", "111.444.777-35"])
def test_cpf_valido(cpf):
    assert cpf_valido(cpf)


@pytest.mark.parametrize("cpf", ["111.111.111-11", "529.982.247-24", "123", "", "abcdefghijk"])
def test_cpf_invalido(cpf):
    assert not cpf_valido(cpf)


@pytest.mark.parametrize("cnpj", ["12.345.678/0001-95", "11222333000181"])
def test_cnpj_valido(cnpj):
    assert cnpj_valido(cnpj)


@pytest.mark.parametrize("cnpj", ["11.111.111/1111-11", "12.345.678/0001-96", "123"])
def test_cnpj_invalido(cnpj):
    assert not cnpj_valido(cnpj)


def test_validar_cpf_normaliza_e_rejeita():
    assert validar_cpf("529.982.247-25") == "52998224725"
    with pytest.raises(ValueError):
        validar_cpf("111.111.111-11")


def test_email_e_cep():
    assert validar_email("  Fulano@Exemplo.COM ") == "fulano@exemplo.com"
    with pytest.raises(ValueError):
        validar_email("sem-arroba")
    assert validar_cep("12.235-000") == "12235000"
    with pytest.raises(ValueError):
        validar_cep("123")


@pytest.mark.parametrize(
    "texto, esperado",
    [("49,90", "49.90"), ("49.90", "49.90"), ("1.234,56", "1234.56"), ("10", "10.00")],
)
def test_converter_decimal(texto, esperado):
    assert converter_decimal(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", ["abc", "0", "-5", "NaN", "Infinity"])
def test_converter_decimal_invalido(texto):
    with pytest.raises(ValueError):
        converter_decimal(texto)


def test_converter_inteiro_limites():
    assert converter_inteiro("0") == 0  # zero é válido por padrão (estoque)
    assert converter_inteiro("5", minimo=1, maximo=5) == 5
    for invalido in ("x", "-1"):
        with pytest.raises(ValueError):
            converter_inteiro(invalido)
    with pytest.raises(ValueError):
        converter_inteiro("6", maximo=5)


def test_formatacao():
    assert formatar_moeda(Decimal("1234.5")) == "R$ 1.234,50"
    assert formatar_cpf("52998224725") == "529.982.247-25"
    assert formatar_cnpj("12345678000195") == "12.345.678/0001-95"
    assert normalizar("  João   da  Silva ") == "João da Silva"
    assert formatar_data(None) == "-"
    assert len(formatar_data(datetime(2026, 11, 4, 12, 0))) == 16
