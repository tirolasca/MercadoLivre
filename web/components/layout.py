"""Estrutura comum das páginas: tema, cabeçalho e controle de acesso por papel."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Ator, Papel, tem
from web.components import cards, feedback, tema
from web.state import ator_atual


def abrir_pagina(titulo: str, subtitulo: str = "", minimo: Papel = Papel.VISITANTE, icone: str | None = None) -> Ator:
    """Aplica o tema, confere o papel mínimo (interrompe a página se faltar) e devolve o ator."""
    tema.aplicar()
    ator = ator_atual()
    if not tem(ator, minimo):
        cards.cabecalho(titulo, subtitulo, icone)
        st.warning("Esta página exige login." if minimo == Papel.USUARIO else "Esta página é restrita a administradores.", icon=":material/lock:")
        st.stop()
    cards.cabecalho(titulo, subtitulo, icone)
    feedback.exibir_pendentes()
    return ator
