"""Estilo comum dos gráficos Plotly: fundo transparente (o cartão vem do CSS), grade discreta, tooltip legível."""

from __future__ import annotations

from typing import Any

# Sem barra de ferramentas (zoom/câmera): ruído para um painel de leitura.
CONFIG = {"displayModeBar": False}

# Cores semânticas: azul = volume de itens, âmbar = dinheiro. Funcionam nos modos claro e escuro.
AZUL = "#3a76e6"
AMBAR = "#e5a800"

_FONTE = 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'


def estilizar(fig: Any, altura: int = 320, titulo_x: str | None = None, titulo_y: str | None = None) -> Any:
    """Aplica o visual padrão e devolve a própria figura."""
    fig.update_layout(
        height=altura,
        margin=dict(l=12, r=20, t=16, b=28),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=_FONTE, size=12),
        xaxis_title=titulo_x,
        yaxis_title=titulo_y,
        hoverlabel=dict(font_family=_FONTE, font_size=12),
        separators=",.",  # padrão brasileiro: vírgula decimal, ponto de milhar
        showlegend=False,
        bargap=0.35,
    )
    grade = "rgba(128,128,128,.18)"
    fig.update_xaxes(gridcolor=grade, zeroline=False, automargin=True)
    fig.update_yaxes(gridcolor=grade, zeroline=False, automargin=True)
    fig.update_traces(marker_cornerradius=6)
    return fig
