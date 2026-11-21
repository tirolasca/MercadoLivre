"""Componentes visuais reutilizáveis (cards, selos, avisos)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from web.components import icones
from web.utils.formatacao import texto


def cabecalho(titulo: str, subtitulo: str = "", icone: str | None = None) -> None:
    ico = f'<div class="ico">{icones.svg(icone, 22)}</div>' if icone else ""
    sub = f"<p>{texto(subtitulo)}</p>" if subtitulo else ""
    st.markdown(f'<div class="ml-cabecalho">{ico}<div><h1>{texto(titulo)}</h1>{sub}</div></div>', unsafe_allow_html=True)


def cards(itens: list[dict[str, Any]]) -> None:
    """Cada item: ``rotulo``, ``valor`` (``None`` = indisponível), ``nota``, ``icone``, ``tom`` (``ok``/``erro``) e ``destaque`` opcionais."""
    html = ['<div class="ml-cards">']
    for it in itens:
        indisponivel = it.get("valor") is None
        classes = ["ml-card"]
        if indisponivel:
            classes.append("indisponivel")
        else:
            classes += [c for c in (it.get("tom"), "destaque" if it.get("destaque") else None) if c]
        valor = "Indisponível" if indisponivel else texto(it["valor"])
        nota = f'<div class="nota">{texto(it["nota"])}</div>' if it.get("nota") else ""
        ico = f'<span class="ico">{icones.svg(it["icone"], 16)}</span>' if it.get("icone") else ""
        html.append(
            f'<div class="{" ".join(classes)}"><div class="topo"><span class="rotulo">{texto(it["rotulo"])}</span>{ico}</div>'
            f'<div class="valor">{valor}</div>{nota}</div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def cards_carregando(quantidade: int = 4) -> None:
    """Esqueleto dos cards enquanto os bancos respondem (troque por ``cards`` ao terminar)."""
    um = '<div class="ml-card skel"><div class="ml-skel linha-a"></div><div class="ml-skel linha-b"></div></div>'
    st.markdown(f'<div class="ml-cards" aria-busy="true" aria-label="Carregando indicadores">{um * quantidade}</div>', unsafe_allow_html=True)


def selo(rotulo: str, tipo: str = "neutro") -> str:
    """HTML de um selo (``ok``, ``erro``, ``aviso`` ou ``neutro``)."""
    return f'<span class="ml-selo {tipo}">{texto(rotulo)}</span>'


def indisponivel(servico: str, mensagem: str | None = None) -> None:
    corpo = texto(mensagem or "Esta parte da página volta quando o serviço responder.")
    st.markdown(
        f'<div class="ml-indisponivel" role="status"><span class="ico">{icones.svg("cloud-off", 20)}</span>'
        f"<div><b>{texto(servico)} indisponível.</b> {corpo}</div></div>",
        unsafe_allow_html=True,
    )


def estado_vazio(titulo: str, orientacao: str = "", icone: str = "inbox") -> None:
    """Estado vazio com orientação do que fazer em seguida."""
    dica = f'<div class="texto">{texto(orientacao)}</div>' if orientacao else ""
    st.markdown(
        f'<div class="ml-vazio" role="status"><span class="ico">{icones.svg(icone, 22)}</span><div class="titulo">{texto(titulo)}</div>{dica}</div>',
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


def tabela(linhas: list[dict[str, Any]], colunas: dict[str, str], vazio: str = "Nada para mostrar.", altura: int | None = None, filtrada: bool = False) -> None:
    """Tabela legível. ``colunas`` mapeia chave -> título exibido (na ordem desejada)."""
    if not linhas:
        estado_vazio(vazio, "Ajuste os filtros ou volte mais tarde." if filtrada else "")
        return
    df = pd.DataFrame([{titulo: l.get(chave) for chave, titulo in colunas.items()} for l in linhas])
    opcoes = {"height": altura} if altura else {}
    st.dataframe(df, hide_index=True, width="stretch", **opcoes)
