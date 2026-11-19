import fakeredis
import mongomock
import pytest

from mercadolivre import catalogo, catalogo_dados, sessoes, sessoes_dados


@pytest.fixture
def banco(monkeypatch):
    """MongoDB em memória (mongomock) usado pelos módulos que acessam o banco."""
    db = mongomock.MongoClient().db
    monkeypatch.setattr(catalogo, "mongo_db", lambda: db)
    monkeypatch.setattr(catalogo_dados, "mongo_db", lambda: db)
    monkeypatch.setattr(sessoes, "mongo_db", lambda: db)
    monkeypatch.setattr(sessoes_dados, "mongo_db", lambda: db)
    return db


@pytest.fixture
def redis_falso(monkeypatch):
    """Redis em memória (fakeredis)."""
    cliente = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessoes, "redis_cliente", lambda: cliente)
    monkeypatch.setattr(sessoes_dados, "redis_cliente", lambda: cliente)
    return cliente


@pytest.fixture
def respostas(monkeypatch):
    """Simula o teclado: ``respostas(["a", "b"])`` alimenta ui.perguntar na ordem.

    Os validadores continuam sendo aplicados, como na interface real.
    """

    def configurar(valores, selecoes=(), confirmacoes=()):
        fila, filas_sel, fila_conf = list(valores), list(selecoes), list(confirmacoes)

        def perguntar(rotulo, validador=str, obrigatorio=True, padrao="", senha=False, sugestoes=None):
            bruto = fila.pop(0)
            return validador(bruto) if bruto else None

        monkeypatch.setattr("mercadolivre.ui.perguntar", perguntar)
        monkeypatch.setattr("mercadolivre.ui.selecionar", lambda *a, **k: filas_sel.pop(0))
        monkeypatch.setattr("mercadolivre.ui.confirmar", lambda *a, **k: fila_conf.pop(0))

    return configurar
