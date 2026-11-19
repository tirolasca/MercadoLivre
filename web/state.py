"""Estado de sessão da interface: o único ponto que liga ``st.session_state`` à autenticação.

``st.session_state`` guarda só o token opaco. O papel NÃO é lido dele: a cada execução o
token é validado no servidor (``ator_do_token``), então editar o estado no navegador
não concede permissão alguma.
"""

from __future__ import annotations

import streamlit as st

from web.auth import sessao
from web.auth.permissoes import Ator
from web.auth.usuarios import ContaWeb, carregar_contas

CHAVE_TOKEN = "_token_sessao"


@st.cache_resource(show_spinner=False)
def contas_configuradas() -> dict[str, ContaWeb]:
    try:
        secretas = list(st.secrets.get("auth", {}).get("usuarios", []))
    except Exception:  # noqa: BLE001 - st.secrets lança se não houver arquivo de secrets
        secretas = []
    return carregar_contas(secretas)


def ator_atual() -> Ator:
    return sessao.ator_do_token(st.session_state.get(CHAVE_TOKEN))


def entrar(usuario: str, senha: str) -> str | None:
    """Devolve uma mensagem de erro, ou ``None`` se o login foi feito."""
    r = sessao.entrar(usuario, senha, contas_configuradas())
    if r.ok:
        st.session_state[CHAVE_TOKEN] = r.token
        return None
    return r.mensagem


def sair() -> None:
    sessao.sair(st.session_state.pop(CHAVE_TOKEN, None))
