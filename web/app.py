"""Ponto de entrada da interface web (Streamlit).

Execução local:  streamlit run web/app.py
Streamlit Community Cloud: "Main file path" = web/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Mercado Livre — Persistência Poliglota", page_icon="🛒", layout="wide", initial_sidebar_state="expanded")

from mercadolivre import config  # noqa: E402
from web import state  # noqa: E402
from web.auth.permissoes import Papel, tem  # noqa: E402
from web.components import sidebar, tema  # noqa: E402


@st.cache_resource(show_spinner=False)
def _configurar() -> list[str]:
    """Copia os Secrets do Streamlit para o ambiente, uma vez por processo (sem sobrescrever)."""
    try:
        return config.aplicar_secrets(dict(st.secrets))
    except Exception:  # noqa: BLE001 - sem arquivo de secrets (execução local com .env)
        return []


_configurar()
tema.aplicar()
ator = state.ator_atual()

PAGINAS = [
    ("pages/dashboard.py", "Dashboard", "📊", "dashboard", Papel.VISITANTE),
    ("pages/produtos.py", "Produtos", "📦", "produtos", Papel.VISITANTE),
    ("pages/vendedores.py", "Vendedores", "🏪", "vendedores", Papel.VISITANTE),
    ("pages/usuarios.py", "Usuários", "👤", "usuarios", Papel.USUARIO),
    ("pages/pedidos.py", "Pedidos", "🧾", "pedidos", Papel.USUARIO),
    ("pages/sessoes.py", "Sessões e cache", "⚡", "sessoes", Papel.VISITANTE),
    ("pages/historico.py", "Histórico de compras", "🗂️", "historico", Papel.VISITANTE),
    ("pages/grafo.py", "Grafo", "🕸️", "grafo", Papel.VISITANTE),
    ("pages/diagnostico.py", "Diagnóstico", "🩺", "diagnostico", Papel.VISITANTE),
]

sidebar.renderizar(ator)

if ator.papel == Papel.VISITANTE and not config.modo_demo():
    st.title("Mercado Livre — Persistência Poliglota")
    st.info("Entre com a sua conta na barra lateral para continuar.")
    st.stop()

paginas = [st.Page(arq, title=nome, icon=icone, url_path=url) for arq, nome, icone, url, minimo in PAGINAS if tem(ator, minimo)]
st.navigation(paginas).run()
