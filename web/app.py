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

st.set_page_config(page_title="Mercado Livre — Persistência Poliglota", page_icon=":material/storefront:", layout="wide", initial_sidebar_state="auto")

from mercadolivre import config  # noqa: E402
from web import state  # noqa: E402
from web.auth.permissoes import Papel, tem  # noqa: E402
from web.components import cards, sidebar, tema  # noqa: E402


@st.cache_resource(show_spinner=False)
def _configurar() -> list[str]:
    """Copia os Secrets do Streamlit para o ambiente, uma vez por processo (sem sobrescrever)."""
    try:
        return config.aplicar_secrets(dict(st.secrets))
    except Exception:  # noqa: BLE001 - sem arquivo de secrets (execução local com .env)
        return []


_configurar()
tema.aplicar()
# Marca fixa no topo da barra lateral, acima do menu (no celular vira o ícone quando recolhida).
st.logo(str(RAIZ / "web" / "styles" / "logo.svg"), icon_image=str(RAIZ / "web" / "styles" / "logo-icone.svg"), size="large")
ator = state.ator_atual()

# ATENÇÃO: a pasta das páginas NÃO pode se chamar "pages". Com esse nome o Streamlit a descobre sozinho
# e, num link direto (ex.: /pedidos) como primeiro acesso após subir o servidor, executa a página sem
# passar por este arquivo, causando ModuleNotFoundError: No module named 'web'.
PAGINAS = [
    ("paginas/dashboard.py", "Dashboard", ":material/dashboard:", "dashboard", Papel.VISITANTE),
    ("paginas/produtos.py", "Produtos", ":material/inventory_2:", "produtos", Papel.VISITANTE),
    ("paginas/vendedores.py", "Vendedores", ":material/storefront:", "vendedores", Papel.VISITANTE),
    ("paginas/usuarios.py", "Usuários", ":material/group:", "usuarios", Papel.USUARIO),
    ("paginas/pedidos.py", "Pedidos", ":material/receipt_long:", "pedidos", Papel.USUARIO),
    ("paginas/favoritos.py", "Favoritos", ":material/favorite:", "favoritos", Papel.USUARIO),
    ("paginas/sessoes.py", "Sessões e cache", ":material/bolt:", "sessoes", Papel.VISITANTE),
    ("paginas/historico.py", "Histórico de compras", ":material/history:", "historico", Papel.VISITANTE),
    ("paginas/grafo.py", "Grafo", ":material/hub:", "grafo", Papel.VISITANTE),
    ("paginas/diagnostico.py", "Diagnóstico", ":material/monitor_heart:", "diagnostico", Papel.VISITANTE),
]

sidebar.renderizar(ator)

if ator.papel == Papel.VISITANTE and not config.modo_demo():
    cards.cabecalho("Mercado Livre — Persistência Poliglota", "Marketplace sobre MongoDB, Redis, Cassandra e Neo4j.", "shopping-bag")
    cards.estado_vazio("Entre para continuar", "Use o formulário de login na barra lateral. Em telas pequenas, abra o menu no canto superior esquerdo.", "log-in")
    st.stop()

paginas = [st.Page(arq, title=nome, icon=icone, url_path=url) for arq, nome, icone, url, minimo in PAGINAS if tem(ator, minimo)]
st.navigation(paginas).run()
