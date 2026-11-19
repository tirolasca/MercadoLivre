"""Feedback padrão das operações e cache curto das leituras públicas."""

from __future__ import annotations

from typing import Any

import streamlit as st

from web.components import cards


def resposta(servico: str, resultado: Any, sucesso: str | None = None, invalidar_cache: bool = True) -> bool:
    """Mostra sucesso ou erro de um ``Resultado``. Devolve ``True`` se deu certo."""
    if resultado.ok:
        if sucesso:
            st.success(sucesso)
        if invalidar_cache:
            st.cache_data.clear()
        return True
    cards.erro_resultado(servico, resultado)
    return False


def pedir_confirmacao(chave: str, rotulo: str, acao: str) -> bool:
    """Exclusão em duas etapas: marcar a confirmação e só então clicar no botão."""
    confirmado = st.checkbox(rotulo, key=f"conf_{chave}")
    return st.button(acao, key=f"btn_{chave}", type="primary", disabled=not confirmado)
