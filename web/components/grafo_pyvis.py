"""Desenho interativo do grafo com PyVis (vis-network).

PyVis foi escolhido por render pronto no navegador (arrastar, zoom, tooltip, física),
sem servidor extra nem JavaScript próprio, e gera um HTML autossuficiente
(``cdn_resources="in_line"``), que funciona mesmo em hospedagens com rede restrita.
Plotly/NetworkX desenhariam um layout estático e sem física. Limitação: o PyVis não
devolve o clique ao Streamlit, por isso os detalhes do elemento aparecem ao passar o
mouse (tooltip) e em um seletor abaixo do grafo.
"""

from __future__ import annotations

import json
from typing import Any

from web.utils.formatacao import texto

CORES = {
    "Usuario": "#3483fa", "Compra": "#ffb400", "Produto": "#0f9d58",
    "Vendedor": "#8e44ad", "Categoria": "#e74c3c",
}
FORMAS = {"Usuario": "dot", "Compra": "diamond", "Produto": "square", "Vendedor": "triangle", "Categoria": "star"}
ROTULOS = {"Usuario": "Usuário", "Compra": "Compra", "Produto": "Produto", "Vendedor": "Vendedor", "Categoria": "Categoria"}

_OPCOES = {
    "interaction": {"hover": True, "tooltipDelay": 80, "navigationButtons": True, "keyboard": True},
    "physics": {"solver": "forceAtlas2Based", "stabilization": {"iterations": 150}},
    "edges": {"arrows": {"to": {"enabled": True, "scaleFactor": 0.6}}, "smooth": {"type": "dynamic"}, "font": {"size": 10, "align": "middle"}},
    "nodes": {"font": {"size": 13}},
}


def _tooltip(no: dict[str, Any]) -> str:
    linhas = "".join(f"<br><b>{texto(k)}</b>: {texto(v)}" for k, v in no["propriedades"].items())
    return f"<b>{texto(ROTULOS.get(no['rotulo'], no['rotulo']))}</b>{linhas}"


def gerar_html(nos: list[dict[str, Any]], arestas: list[dict[str, Any]], altura: int = 560) -> str:
    from pyvis.network import Network

    rede = Network(height=f"{altura}px", width="100%", directed=True, notebook=False, cdn_resources="in_line")
    for no in nos:
        rede.add_node(no["id"], label=str(no["nome"])[:28], title=_tooltip(no), color=CORES.get(no["rotulo"], "#999"), shape=FORMAS.get(no["rotulo"], "dot"), size=18)
    for a in arestas:
        rede.add_edge(a["origem"], a["destino"], label=a["tipo"], title=a["tipo"])
    rede.set_options(json.dumps(_OPCOES))
    return _ajustar_visual(rede.generate_html())


# O desenho vive num iframe: o CSS do app não o alcança. Aqui alinhamos a moldura ao restante da interface
# (sem a margem padrão do <body>) e, no modo escuro, trocamos fundo e cor dos rótulos (o texto é um <canvas>).
_ESTILO = (
    "<style>html,body{margin:0;background:transparent}"
    ".card{border:0 !important;background:transparent !important}"
    "#mynetwork{box-sizing:border-box;border:1px solid #e2e6f0 !important;border-radius:12px;background:#fff}"
    "@media (prefers-color-scheme: dark){#mynetwork{background:#141930 !important;border-color:#262d4d !important}}</style>"
)
_SCRIPT_ESCURO = (
    "<script>(function(){try{if(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches&&window.network){"
    "network.setOptions({nodes:{font:{color:'#eceffa'}},edges:{font:{color:'#c3cae3',strokeWidth:3,strokeColor:'#141930'},"
    "color:{color:'#5b668f',highlight:'#8db4ff',hover:'#8db4ff'}}});}}catch(e){}})();</script>"
)


def _ajustar_visual(html: str) -> str:
    html = html.replace("</head>", _ESTILO + "</head>", 1)
    return html.replace("</body>", _SCRIPT_ESCURO + "</body>", 1)


def legenda_html() -> str:
    itens = "".join(
        f'<span style="display:inline-block;margin-right:14px;"><span style="color:{cor};font-size:1.1em;">●</span> {texto(ROTULOS[r])}</span>'
        for r, cor in CORES.items()
    )
    return f'<div style="font-size:.85rem;">{itens}</div>'
