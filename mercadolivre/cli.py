"""Ponto de entrada: menu principal que abre cada módulo da aplicação.

Execute com ``python -m mercadolivre``.
"""

from __future__ import annotations

from importlib import import_module

from . import __version__, ui
from .conexoes import fechar_conexoes

MODULOS = [
    ("Catálogo e pedidos         (MongoDB)", "catalogo"),
    ("Sessões e cache            (Redis)", "sessoes"),
    ("Histórico de compras       (Cassandra)", "historico"),
    ("Grafo de compras           (Neo4j)", "grafo"),
    ("Diagnóstico de conexões", "diagnostico"),
]


def abrir(nome_modulo: str) -> None:
    # Importação sob demanda: quem usa só um banco não precisa dos drivers dos outros.
    try:
        modulo = import_module(f"mercadolivre.{nome_modulo}")
        (modulo.executar if nome_modulo == "diagnostico" else modulo.main)()
    except ui.Cancelado:
        ui.aviso("Operação cancelada.")
    except Exception as exc:  # noqa: BLE001 - não derrubar o menu principal
        ui.erro(f"{type(exc).__name__}: {exc}")


def main() -> None:
    ui.banner(f"MERCADO LIVRE  v{__version__}", "Marketplace com persistência poliglota: MongoDB · Redis · Cassandra · Neo4j")
    try:
        while True:
            escolha = ui.selecionar("O que deseja abrir?", MODULOS, voltar="Sair")
            if escolha is None:
                break
            abrir(escolha)
    except (ui.Cancelado, KeyboardInterrupt):
        pass
    finally:
        fechar_conexoes()
        ui.info("Até logo!")


if __name__ == "__main__":
    main()
