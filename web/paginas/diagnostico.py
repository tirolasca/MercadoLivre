"""Diagnóstico dos quatro bancos."""

from __future__ import annotations

import time

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.layout import abrir_pagina
from web.services import diagnostico

ator = abrir_pagina("Diagnóstico", "Estado de cada banco, latência e operações dependentes.", icone="stethoscope")
admin = tem(ator, Papel.ADMIN)

# O resultado fica 30 s na sessão do usuário (cada verificação pode esperar o timeout de um banco fora do ar).
agora = time.monotonic()
guardado = st.session_state.get("_diag")
if st.button("Executar diagnóstico novamente", icon=":material/refresh:") or guardado is None or agora - guardado[0] > 30:
    with st.spinner("Testando os quatro bancos..."):
        guardado = (agora, diagnostico.verificar(ator))
    st.session_state["_diag"] = guardado
linhas = guardado[1]

_ICONES = {"MongoDB": "database", "Redis": "zap", "Cassandra": "layers", "Neo4j": "waypoints"}
cards.cards([
    {
        "rotulo": l["servico"],
        "valor": "Online" if l["ok"] else "Falha",
        "nota": f"{l['ms']:.0f} ms" if l["ms"] is not None else "não configurado",
        "icone": next((i for nome, i in _ICONES.items() if l["servico"].startswith(nome)), "server"),
        "tom": "ok" if l["ok"] else "erro",
    }
    for l in linhas
])
for l in linhas:
    cols = st.columns([2, 1.8, 4.2])
    cols[0].markdown(f"**{l['servico']}**")
    cols[1].markdown(cards.selo("ONLINE" if l["ok"] else ("NÃO CONFIGURADO" if not l["configurado"] else "FALHA"), "ok" if l["ok"] else "erro"), unsafe_allow_html=True)
    cols[2].write(l["detalhe"])
    cols[2].caption(f"Operações: {l['operacoes']}" + ("" if l["ok"] else " — desabilitadas enquanto o serviço estiver fora do ar."))

if not all(l["ok"] for l in linhas):
    st.info("Bancos gratuitos hibernam por inatividade (Astra após 48 h, Aura após 72 h). Retome-os no painel do provedor e use o botão abaixo para reconectar.")
if admin:
    st.divider()
    if st.button("Reiniciar conexões"):
        diagnostico.reiniciar_conexoes(ator)
        st.session_state.pop("_diag", None)
        st.rerun()
