"""Dados de demonstração compartilhados pelos quatro bancos.

O mesmo conjunto (2 usuários, 2 lojas, 4 produtos) é carregado no MongoDB, no
Cassandra e no Neo4j. Assim, na apresentação, dá para mostrar **os mesmos dados
guardados de quatro jeitos diferentes**.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import NamedTuple

USUARIOS = [
    ("52998224725", "Fulano", "de Tal", "fulano@exemplo.com"),
    ("11144477735", "Beltrana", "Silva", "beltrana@exemplo.com"),
]  # cpf, nome, sobrenome, e-mail

LOJAS = [
    ("12345678000195", "Loja do Teclado"),
    ("11222333000181", "Mundo Periférico"),
]  # cnpj, nome da loja


class ProdutoDemo(NamedTuple):
    chave: str
    cnpj: str
    titulo: str
    descricao: str
    preco: Decimal
    estoque: int
    categoria: str


PRODUTOS = [
    ProdutoDemo("teclado", LOJAS[0][0], "Teclado Mecanico", "Teclado ABNT2 switch azul", Decimal("150.00"), 10, "MLB1648"),
    ProdutoDemo("gamer", LOJAS[0][0], "Teclado Gamer", "Teclado RGB", Decimal("220.00"), 5, "MLB1648"),
    ProdutoDemo("mouse", LOJAS[1][0], "Mouse Sem Fio", "Mouse 2.4GHz", Decimal("80.00"), 20, "MLB1649"),
    ProdutoDemo("headset", LOJAS[1][0], "Headset USB", "Headset com microfone", Decimal("130.00"), 8, "MLB1649"),
]

# (índice do usuário, chave do produto, quantidade)
COMPRAS = [(0, "teclado", 1), (0, "mouse", 2), (1, "gamer", 1), (1, "mouse", 1)]


def id_produto(chave: str) -> uuid.UUID:
    """Id fixo por produto: recarregar a demonstração não duplica nada."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"mercadolivre.demo.{chave}")
