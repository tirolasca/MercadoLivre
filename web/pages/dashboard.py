"""Dashboard: indicadores reais do MongoDB e sinais de atividade dos demais bancos."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from web.components import cards
from web.components.layout import abrir_pagina
from web.services import catalogo, grafo, historico, sessoes
from web.utils.formatacao import moeda

abrir_pagina("Dashboard", "Visão geral do marketplace, calculada em tempo real a partir dos bancos.")


# Dados agregados e públicos: seguros para o cache compartilhado (curto, 30 s).
@st.cache_data(ttl=30, show_spinner=False)
def _mongo():
    return catalogo.indicadores()


@st.cache_data(ttl=30, show_spinner=False)
def _redis():
    return sessoes.estado()


@st.cache_data(ttl=30, show_spinner=False)
def _neo4j():
    return grafo.resumo()


@st.cache_data(ttl=30, show_spinner=False)
def _cassandra():
    return historico.categorias()


with st.spinner("Consultando os bancos..."):
    mongo, redis, neo4j, cassandra = _mongo(), _redis(), _neo4j(), _cassandra()

# ----------------------------------------------------------------------------
# Indicadores principais (MongoDB)
# ----------------------------------------------------------------------------
if mongo.ok:
    d = mongo.dados
    c = d["contagens"]
    cards.cards([
        {"rotulo": "Usuários", "valor": c["usuarios"]},
        {"rotulo": "Vendedores", "valor": c["vendedores"]},
        {"rotulo": "Produtos", "valor": c["produtos"]},
        {"rotulo": "Pedidos", "valor": c["pedidos"]},
        {"rotulo": "Receita total", "valor": moeda(d["receita"]), "nota": "soma dos pedidos"},
        {"rotulo": "Valor em estoque", "valor": moeda(d["valor_estoque"]), "nota": "preço × quantidade"},
    ])
else:
    cards.cards([{"rotulo": r, "valor": None} for r in ("Usuários", "Vendedores", "Produtos", "Pedidos", "Receita total", "Valor em estoque")])
    cards.indisponivel("MongoDB", mongo.erro)

# ----------------------------------------------------------------------------
# Gráficos
# ----------------------------------------------------------------------------
esq, dir_ = st.columns(2)
with esq:
    st.subheader("Produtos mais vendidos")
    if mongo.ok and mongo.dados["mais_vendidos"]:
        df = pd.DataFrame(mongo.dados["mais_vendidos"]).sort_values("vendidos")
        fig = px.bar(df, x="vendidos", y="titulo", orientation="h", color_discrete_sequence=["#3483fa"])
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=320, yaxis_title=None, xaxis_title="Unidades vendidas")
        st.plotly_chart(fig, width="stretch")
    elif mongo.ok:
        st.info("Ainda não há vendas registradas.")
    else:
        cards.indisponivel("MongoDB")
with dir_:
    st.subheader("Receita por dia")
    if mongo.ok and mongo.dados["vendas_por_dia"]:
        df = pd.DataFrame(mongo.dados["vendas_por_dia"])
        df["receita"] = df["receita"].astype(float)
        fig = px.bar(df, x="dia", y="receita", color_discrete_sequence=["#ffb400"], hover_data={"pedidos": True})
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=320, xaxis_title=None, yaxis_title="R$")
        st.plotly_chart(fig, width="stretch")
    elif mongo.ok:
        st.info("Ainda não há pedidos para exibir a evolução das vendas.")
    else:
        cards.indisponivel("MongoDB")

st.subheader("Estoque baixo")
if mongo.ok:
    limite = mongo.dados["limite_estoque_baixo"]
    cards.tabela(mongo.dados["estoque_baixo"], {"titulo": "Produto", "estoque": "Em estoque"}, f"Nenhum produto com {limite} unidades ou menos.")
else:
    cards.indisponivel("MongoDB")

# ----------------------------------------------------------------------------
# Atividade dos demais bancos
# ----------------------------------------------------------------------------
st.subheader("Atividade nos outros bancos")
nos = {n["nome"]: n["total"] for n in neo4j.dados["nos"]} if neo4j.ok else {}
rels = sum(r["total"] for r in neo4j.dados["relacoes"]) if neo4j.ok else None
cards.cards([
    {"rotulo": "Sessões ativas (Redis)", "valor": (redis.dados["sessoes_login"] + redis.dados["sessoes_demo"]) if redis.ok else None, "nota": "login + demonstração"},
    {"rotulo": "Categorias no histórico (Cassandra)", "valor": len(cassandra.dados) if cassandra.ok else None},
    {"rotulo": "Compras no grafo (Neo4j)", "valor": nos.get("Compra", 0) if neo4j.ok else None},
    {"rotulo": "Relacionamentos no grafo", "valor": rels},
])
for nome, res in (("Redis", redis), ("Cassandra", cassandra), ("Neo4j", neo4j)):
    if not res.ok:
        cards.indisponivel(nome, res.erro)
