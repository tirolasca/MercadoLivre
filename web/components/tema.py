"""Tema: injeta o CSS da aplicação (uma vez por execução de página)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

_CSS = Path(__file__).resolve().parent.parent / "styles" / "app.css"


def aplicar() -> None:
    st.markdown(f"<style>{_CSS.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
