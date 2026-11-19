"""Fixtures da interface web: bancos simulados, ambiente isolado do .env e atalhos de login."""

from pathlib import Path

import fakeredis
import mongomock
import pytest
import streamlit as st

from mercadolivre import catalogo_dados, conexoes, sessoes_dados
from web import state
from web.auth import sessao
from web.auth.permissoes import Papel
from web.auth.senhas import gerar_hash
from web.auth.usuarios import ContaWeb
from web.services import resultado

RAIZ = Path(__file__).resolve().parents[2]
VARIAVEIS_DE_BANCO = (
    "MONGODB_URI", "REDIS_URL", "REDIS_HOST", "REDIS_PASSWORD", "ASTRA_DB_TOKEN", "ASTRA_SCB_PATH",
    "ASTRA_SCB_B64", "NEO4J_URI", "NEO4J_PASSWORD", "AUTH_USUARIOS",
)
SENHA = "senha-de-teste-123"


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    """Isola cada teste: sem credenciais reais (.env), produção por padrão, estado limpo."""
    for nome in VARIAVEIS_DE_BANCO:
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    resultado.reiniciar_disjuntores()
    sessao._memoria.sessoes.clear()
    sessao._memoria.falhas.clear()
    st.cache_data.clear()
    st.cache_resource.clear()
    yield


@pytest.fixture
def mongo(monkeypatch):
    db = mongomock.MongoClient().db
    monkeypatch.setattr(catalogo_dados, "mongo_db", lambda: db)
    monkeypatch.setattr(sessoes_dados, "mongo_db", lambda: db)
    # o mongomock não suporta $multiply com Decimal128 (o MongoDB real suporta)
    from decimal import Decimal
    monkeypatch.setattr(catalogo_dados, "valor_em_estoque", lambda: Decimal("450.00"))
    return db


@pytest.fixture
def redis_falso(monkeypatch):
    cliente = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(sessoes_dados, "redis_cliente", lambda: cliente)
    return cliente


@pytest.fixture
def contas():
    iteracoes = 1000  # rápido nos testes
    return {
        "admin": ContaWeb("admin", Papel.ADMIN, gerar_hash(SENHA, iteracoes), "admin@exemplo.com"),
        "ana": ContaWeb("ana", Papel.USUARIO, gerar_hash(SENHA, iteracoes), "ana@exemplo.com"),
        "beto": ContaWeb("beto", Papel.USUARIO, gerar_hash(SENHA, iteracoes), "beto@exemplo.com"),
    }


@pytest.fixture
def token(redis_falso, contas):
    """Faz login de verdade (``sessao.entrar``) e devolve o token do papel pedido."""
    def criar(usuario: str) -> str:
        r = sessao.entrar(usuario, SENHA, contas)
        assert r.ok, r.mensagem
        return r.token
    return criar


@pytest.fixture
def ator(token):
    return lambda usuario: sessao.ator_do_token(token(usuario))


@pytest.fixture
def pagina(monkeypatch, mongo, redis_falso):
    """Abre uma página isolada no AppTest já autenticada (ou como visitante, com ``token=None``)."""
    from streamlit.testing.v1 import AppTest

    def abrir(nome: str, token: str | None = None, timeout: int = 30):
        at = AppTest.from_file(str(RAIZ / "web" / "pages" / f"{nome}.py"), default_timeout=timeout)
        if token:
            at.session_state[state.CHAVE_TOKEN] = token
        return at.run()
    return abrir


@pytest.fixture
def semeado(mongo):
    """Um vendedor, dois usuários (Ana e Beto) e um produto no MongoDB simulado."""
    catalogo_dados.configurar_banco_dados()
    vendedor = catalogo_dados.inserir_vendedor("Loja Teste", "12345678000195")
    ana = catalogo_dados.inserir_usuario("Ana", "Lima", "52998224725", "ana@exemplo.com")
    beto = catalogo_dados.inserir_usuario("Beto", "Souza", "11144477735", "beto@exemplo.com")
    produto = catalogo_dados.inserir_produto(vendedor["_id"], "Teclado", "ABNT2", "150,00", 5, "mlb1648")
    return {"vendedor": vendedor, "ana": ana, "beto": beto, "produto": produto}
