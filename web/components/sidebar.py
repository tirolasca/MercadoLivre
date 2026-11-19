"""Barra lateral: marca, login/logout e aviso de ambiente."""

from __future__ import annotations

import streamlit as st

from mercadolivre import config
from web import state
from web.auth.permissoes import Ator, Papel
from web.utils.formatacao import texto


def renderizar(ator: Ator) -> None:
    with st.sidebar:
        st.markdown('<div class="ml-marca"><span>ML</span>Marketplace</div>', unsafe_allow_html=True)
        if not config.em_producao():
            st.warning("Modo desenvolvimento: contas descartáveis ativas.", icon="⚠️")
        if ator.papel == Papel.VISITANTE:
            if not state.contas_configuradas():
                st.caption("Nenhuma conta configurada: o login está desativado (veja docs/DEPLOY.md).")
            with st.form("login", clear_on_submit=False):
                usuario = st.text_input("Usuário", max_chars=60, autocomplete="username")
                senha = st.text_input("Senha", type="password", max_chars=128, autocomplete="current-password")
                if st.form_submit_button("Entrar", type="primary", width="stretch"):
                    if (mensagem := state.entrar(usuario, senha)) is None:
                        st.rerun()
                    st.error(mensagem)
            st.caption("Você está navegando como **visitante** (somente leitura, dados pessoais ocultos).")
        else:
            st.markdown(f'<div class="ml-usuario">Conectado como <b>{texto(ator.usuario)}</b> ({ator.papel.value})</div>', unsafe_allow_html=True)
            if st.button("Sair", width="stretch"):
                state.sair()
                st.rerun()
