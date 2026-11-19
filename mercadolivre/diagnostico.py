"""Diagnóstico das conexões com MongoDB, Redis, Cassandra e Neo4j."""

from __future__ import annotations

import time
from typing import Callable

from rich.text import Text

from . import ui
from .conexoes import cassandra_sessao, fechar_conexoes, mongo_db, neo4j_banco, neo4j_driver, redis_cliente


def _mongo() -> str:
    db = mongo_db()
    db.client.admin.command("ping")
    return f"banco '{db.name}'"


def _redis() -> str:
    r = redis_cliente()
    r.ping()
    r.set("diagnostico:teste", "OK", ex=10)  # ida e volta: escrita, leitura e remoção
    if r.get("diagnostico:teste") != "OK":
        raise RuntimeError("leitura do Redis diferente do valor gravado")
    r.delete("diagnostico:teste")
    return "ping e escrita/leitura OK"


def _cassandra() -> str:
    return f"keyspace '{cassandra_sessao().keyspace}'"


def _neo4j() -> str:
    driver = neo4j_driver()
    driver.verify_connectivity()
    driver.execute_query("RETURN 1 AS ok", database_=neo4j_banco())
    return f"banco '{neo4j_banco()}'"


VERIFICACOES: list[tuple[str, Callable[[], str]]] = [
    ("MongoDB", _mongo),
    ("Redis", _redis),
    ("Cassandra (Astra DB)", _cassandra),
    ("Neo4j (AuraDB)", _neo4j),
]


def verificar_um(nome: str, verificar: Callable[[], str]) -> dict[str, object]:
    """Executa uma verificação e devolve ``{servico, ok, ms, detalhe, erro}`` (sem interface)."""
    inicio = time.perf_counter()
    try:
        detalhe, ok, erro = verificar(), True, None
    except Exception as exc:  # noqa: BLE001 - queremos relatar qualquer falha
        detalhe, ok, erro = "", False, type(exc).__name__
        detalhe = (str(exc).splitlines() or [erro])[0][:80]
    return {"servico": nome, "ok": ok, "ms": (time.perf_counter() - inicio) * 1000, "detalhe": detalhe, "erro": erro}


def verificar_todos() -> list[dict[str, object]]:
    return [verificar_um(nome, fn) for nome, fn in VERIFICACOES]


def executar() -> bool:
    """Testa cada banco e mostra uma tabela. Devolve ``True`` se todos responderam."""
    linhas, todos_ok = [], True
    for nome, verificar in VERIFICACOES:
        with ui.processando(f"Testando {nome}..."):
            r = verificar_um(nome, verificar)
        ok = bool(r["ok"])
        status = Text("ONLINE", style="bold green") if ok else Text("FALHA", style="bold red")
        todos_ok &= ok
        linhas.append((nome, status, f"{r['ms']:.0f} ms", r["detalhe"]))
    ui.tabela("Diagnóstico de conexões", ["Serviço", "Status", ("Tempo", "right"), "Detalhe"], linhas)
    return todos_ok


if __name__ == "__main__":
    try:
        raise SystemExit(0 if executar() else 1)
    finally:
        fechar_conexoes()
