"""Dashboard: indicadores reais do MongoDB e sinais de atividade dos demais bancos."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from web.components import cards, graficos
from web.components.layout import abrir_pagina
from web.services import catalogo, grafo, historico, sessoes
from web.utils.formatacao import moeda

abrir_pagina("Dashboard", "Visão geral do marketplace, calculada em tempo real a partir dos bancos.", icone="layout-dashboard")


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


# Esqueleto dos cards enquanto os bancos respondem (some assim que os dados chegam).
carregando = st.empty()
with carregando.container():
    cards.cards_carregando(6)
mongo, redis, neo4j, cassandra = _mongo(), _redis(), _neo4j(), _cassandra()
carregando.empty()

# ----------------------------------------------------------------------------
# Indicadores principais (MongoDB)
# ----------------------------------------------------------------------------
if mongo.ok:
    d = mongo.dados
    c = d["contagens"]
    cards.cards([
        {"rotulo": "Usuários", "valor": c["usuarios"], "icone": "users"},
        {"rotulo": "Vendedores", "valor": c["vendedores"], "icone": "store"},
        {"rotulo": "Produtos", "valor": c["produtos"], "icone": "package"},
        {"rotulo": "Pedidos", "valor": c["pedidos"], "icone": "receipt-text"},
        {"rotulo": "Receita total", "valor": moeda(d["receita"]), "nota": "soma dos pedidos", "icone": "wallet", "destaque": True},
        {"rotulo": "Valor em estoque", "valor": moeda(d["valor_estoque"]), "nota": "preço × quantidade", "icone": "boxes"},
    ])
else:
    cards.cards([{"rotulo": r, "valor": None, "icone": i} for r, i in (("Usuários", "users"), ("Vendedores", "store"), ("Produtos", "package"), ("Pedidos", "receipt-text"), ("Receita total", "wallet"), ("Valor em estoque", "boxes"))])
    cards.indisponivel("MongoDB", mongo.erro)

# ----------------------------------------------------------------------------
# Gráficos e estoque (só existem com o MongoDB; o aviso acima já explica a ausência)
# ----------------------------------------------------------------------------
if mongo.ok:
    esq, dir_ = st.columns(2)
    with esq:
        st.subheader("Produtos mais vendidos")
        if mongo.dados["mais_vendidos"]:
            df = pd.DataFrame(mongo.dados["mais_vendidos"]).sort_values("vendidos")
            fig = px.bar(df, x="vendidos", y="titulo", orientation="h", color_discrete_sequence=[graficos.AZUL])
            fig.update_traces(hovertemplate="<b>%{y}</b><br>%{x} unidade(s) vendida(s)<extra></extra>")
            fig.update_xaxes(dtick=max(1, -(-int(df["vendidos"].max()) // 5)), tickformat="d")  # só números inteiros
            st.plotly_chart(graficos.estilizar(fig, titulo_x="Unidades vendidas"), width="stretch", config=graficos.CONFIG)
        else:
            cards.estado_vazio("Ainda não há vendas registradas", "Quando um pedido for criado, os produtos mais vendidos aparecem aqui.", "trending-up")
    with dir_:
        st.subheader("Receita por dia")
        if mongo.dados["vendas_por_dia"]:
            df = pd.DataFrame(mongo.dados["vendas_por_dia"])
            df["receita"] = df["receita"].astype(float)
            df["dia"] = pd.to_datetime(df["dia"]).dt.strftime("%d/%m")
            fig = px.bar(df, x="dia", y="receita", color_discrete_sequence=[graficos.AMBAR], custom_data=["pedidos"])
            fig.update_traces(hovertemplate="<b>%{x}</b><br>Receita: R$ %{y:,.2f}<br>Pedidos: %{customdata[0]}<extra></extra>")
            st.plotly_chart(graficos.estilizar(fig, titulo_y="R$"), width="stretch", config=graficos.CONFIG)
        else:
            cards.estado_vazio("Ainda não há pedidos", "A receita diária aparece assim que o primeiro pedido for registrado.", "wallet")

    st.subheader("Estoque baixo")
    limite = mongo.dados["limite_estoque_baixo"]
    cards.tabela(mongo.dados["estoque_baixo"], {"titulo": "Produto", "estoque": "Em estoque"}, f"Nenhum produto com {limite} unidades ou menos.")

# ----------------------------------------------------------------------------
# Atividade dos demais bancos
# ----------------------------------------------------------------------------
st.subheader("Atividade nos outros bancos")
nos = {n["nome"]: n["total"] for n in neo4j.dados["nos"]} if neo4j.ok else {}
rels = sum(r["total"] for r in neo4j.dados["relacoes"]) if neo4j.ok else None
cards.cards([
    {"rotulo": "Sessões ativas (Redis)", "valor": (redis.dados["sessoes_login"] + redis.dados["sessoes_demo"]) if redis.ok else None, "nota": "login + demonstração", "icone": "zap"},
    {"rotulo": "Categorias no histórico (Cassandra)", "valor": len(cassandra.dados) if cassandra.ok else None, "icone": "history"},
    {"rotulo": "Compras no grafo (Neo4j)", "valor": nos.get("Compra", 0) if neo4j.ok else None, "icone": "shopping-cart"},
    {"rotulo": "Relacionamentos no grafo", "valor": rels, "icone": "waypoints"},
])
for nome, res in (("Redis", redis), ("Cassandra", cassandra), ("Neo4j", neo4j)):
    if not res.ok:
        cards.indisponivel(nome, res.erro)
