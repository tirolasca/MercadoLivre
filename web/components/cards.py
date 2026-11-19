"""Componentes visuais reutilizáveis (cards, selos, avisos)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from web.utils.formatacao import texto


def cabecalho(titulo: str, subtitulo: str = "") -> None:
    st.markdown(
        f'<div class="ml-cabecalho"><h1>{texto(titulo)}</h1>' + (f"<p>{texto(subtitulo)}</p>" if subtitulo else "") + "</div>",
        unsafe_allow_html=True,
    )


def cards(itens: list[dict[str, Any]]) -> None:
    """Cada item: ``rotulo``, ``valor`` (``None`` = indisponível), ``nota`` opcional."""
    html = ['<div class="ml-cards">']
    for it in itens:
        indisponivel = it.get("valor") is None
        classe = "ml-card indisponivel" if indisponivel else "ml-card"
        valor = "Indisponível" if indisponivel else texto(it["valor"])
        nota = f'<div class="nota">{texto(it["nota"])}</div>' if it.get("nota") else ""
        html.append(f'<div class="{classe}"><div class="rotulo">{texto(it["rotulo"])}</div><div class="valor">{valor}</div>{nota}</div>')
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def selo(rotulo: str, tipo: str = "neutro") -> str:
    """HTML de um selo (``ok``, ``erro``, ``aviso`` ou ``neutro``)."""
    return f'<span class="ml-selo {tipo}">{texto(rotulo)}</span>'


def indisponivel(servico: str, mensagem: str | None = None) -> None:
    st.markdown(
        f'<div class="ml-indisponivel"><b>{texto(servico)} indisponível.</b> {texto(mensagem or "Esta parte da página volta quando o serviço responder.")}</div>',
        unsafe_allow_html=True,
    )


def erro_resultado(servico: str, resultado: Any) -> bool:
    """Mostra o problema de um ``Resultado`` com falha. Devolve ``True`` se havia falha."""
    if resultado.ok:
        return False
    if resultado.indisponivel:
        indisponivel(servico, resultado.erro)
    else:
        st.error(resultado.erro)
    return True


def tabela(linhas: list[dict[str, Any]], colunas: dict[str, str], vazio: str = "Nada para mostrar.", altura: int | None = None) -> None:
    """Tabela legível. ``colunas`` mapeia chave -> título exibido (na ordem desejada)."""
    if not linhas:
        st.info(vazio)
        return
    df = pd.DataFrame([{titulo: l.get(chave) for chave, titulo in colunas.items()} for l in linhas])
    opcoes = {"height": altura} if altura else {}
    st.dataframe(df, hide_index=True, width="stretch", **opcoes)
