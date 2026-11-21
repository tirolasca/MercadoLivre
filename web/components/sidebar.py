"""Barra lateral: marca, login/logout e aviso de ambiente."""

from __future__ import annotations

import streamlit as st

from mercadolivre import config
from web import state
from web.auth.permissoes import Ator, Papel
from web.utils.formatacao import texto

_ROTULO_PAPEL = {Papel.ADMIN: "Administrador", Papel.USUARIO: "Usuário"}


def renderizar(ator: Ator) -> None:
    with st.sidebar:
        if not config.em_producao():
            st.warning("Modo desenvolvimento: contas descartáveis ativas.", icon=":material/warning:")
        if ator.papel == Papel.VISITANTE:
            if not state.contas_configuradas():
                st.caption("Nenhuma conta configurada: o login está desativado (veja docs/DEPLOY.md).")
            with st.form("login", clear_on_submit=False):
                usuario = st.text_input("Usuário", max_chars=60, autocomplete="username")
                senha = st.text_input("Senha", type="password", max_chars=128, autocomplete="current-password")
                if st.form_submit_button("Entrar", type="primary", width="stretch", icon=":material/login:"):
                    if (mensagem := state.entrar(usuario, senha)) is None:
                        st.rerun()
                    st.error(mensagem)
            st.caption("Você está navegando como **visitante** (somente leitura, dados pessoais ocultos).")
        else:
            nome = texto(ator.usuario)
            papel = texto(_ROTULO_PAPEL.get(ator.papel, ator.papel.value))
            st.markdown(
                f'<div class="ml-usuario"><div class="avatar" aria-hidden="true">{nome[:1]}</div>'
                f"<div>Conectado como <b>{nome}</b><br><span class=\"ml-selo ok\">{papel}</span></div></div>",
                unsafe_allow_html=True,
            )
            if st.button("Sair", width="stretch", icon=":material/logout:"):
                state.sair()
                st.rerun()
