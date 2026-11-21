"""Feedback padrão das operações e cache curto das leituras públicas."""

from __future__ import annotations

from typing import Any

import streamlit as st

from web.components import cards, icones
from web.utils.formatacao import texto

_PENDENTES = "_avisos_pendentes"
ICONE_SUCESSO = ":material/check_circle:"


def resposta(servico: str, resultado: Any, sucesso: str | None = None, invalidar_cache: bool = True, recarregar: bool = True) -> bool:
    """Mostra sucesso (toast) ou erro (faixa na página) de um ``Resultado``. Devolve ``True`` se deu certo.

    ``recarregar=True`` (padrão) vale para quem chama ``st.rerun()`` logo depois: o toast só pode
    aparecer na execução seguinte, senão o rerun o descartaria. Passe ``False`` quando a página
    não recarrega, e o toast aparece na hora.
    """
    if resultado.ok:
        if sucesso:
            if recarregar:
                st.session_state.setdefault(_PENDENTES, []).append(sucesso)
            else:
                st.toast(sucesso, icon=ICONE_SUCESSO)
        if invalidar_cache:
            st.cache_data.clear()
        return True
    cards.erro_resultado(servico, resultado)
    return False


def exibir_pendentes() -> None:
    """Mostra os toasts guardados pela execução anterior (chamado no início de cada página)."""
    for mensagem in st.session_state.pop(_PENDENTES, []):
        st.toast(mensagem, icon=ICONE_SUCESSO)


def pedir_confirmacao(chave: str, titulo: str, acao: str) -> bool:
    """Exclusão em duas etapas: o botão abre um alerta com Cancelar e Excluir definitivamente.

    Devolve ``True`` só no clique de confirmação (e uma única vez). Estado por ``chave`` na sessão.
    """
    estado = f"_confirmando_{chave}"
    if not st.session_state.get(estado):
        if st.button(acao, key=f"btn_{chave}", icon=":material/delete:"):
            st.session_state[estado] = True
            st.rerun()
        return False
    with st.container(border=True):
        st.markdown(
            f'<div class="ml-alerta" role="alert"><span class="ico">{icones.svg("triangle-alert", 20)}</span>'
            f"<div><b>{texto(titulo)}?</b><br>Esta ação não pode ser desfeita.</div></div>",
            unsafe_allow_html=True,
        )
        cancelar, confirmar = st.columns(2)
        if cancelar.button("Cancelar", key=f"cancel_{chave}", width="stretch"):
            st.session_state[estado] = False
            st.rerun()
        if confirmar.button("Excluir definitivamente", key=f"ok_{chave}", type="primary", width="stretch", icon=":material/delete_forever:"):
            st.session_state[estado] = False
            return True
    return False
