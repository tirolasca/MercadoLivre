"""Paginação com botões Anterior/Próxima; volta à página 1 quando os filtros mudam."""

from __future__ import annotations

from typing import Any

import streamlit as st


def paginar(total: int, por_pagina: int, chave: str, assinatura: Any = None) -> tuple[int, int, slice]:
    """Desenha os controles e devolve ``(pagina, total_de_paginas, fatia)`` (página começa em 1).

    ``assinatura`` identifica os filtros atuais: se mudar, a lista volta para a página 1.
    """
    paginas = max(1, -(-total // por_pagina))
    k_pag, k_sig = f"_pag_{chave}", f"_pagsig_{chave}"
    if st.session_state.get(k_sig) != assinatura:
        st.session_state[k_sig], st.session_state[k_pag] = assinatura, 1
    pagina = min(max(1, st.session_state.get(k_pag, 1)), paginas)
    st.session_state[k_pag] = pagina

    def _ir(delta: int) -> None:
        st.session_state[k_pag] = min(max(1, st.session_state[k_pag] + delta), paginas)

    esquerda, centro, direita = st.columns([1, 2, 1], vertical_alignment="center")
    esquerda.button("Anterior", key=f"ant_{chave}", icon=":material/chevron_left:", on_click=_ir, args=(-1,), disabled=pagina <= 1, width="stretch") if paginas > 1 else None
    centro.markdown(f'<div class="ml-paginacao">{total} item(ns) · página <b>{pagina}</b> de <b>{paginas}</b></div>', unsafe_allow_html=True)
    direita.button("Próxima", key=f"prox_{chave}", icon=":material/chevron_right:", icon_position="right", on_click=_ir, args=(1,), disabled=pagina >= paginas, width="stretch") if paginas > 1 else None
    inicio = (pagina - 1) * por_pagina
    return pagina, paginas, slice(inicio, inicio + por_pagina)
