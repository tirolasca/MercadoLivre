"""Pedidos: criação com baixa atômica de estoque (regra do núcleo) e consulta."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import resposta
from web.components.layout import abrir_pagina
from web.services import catalogo
from web.utils.formatacao import data_hora, moeda

ator = abrir_pagina("Pedidos", "Compras registradas no MongoDB.", minimo=Papel.USUARIO, icone="receipt-text")
admin = tem(ator, Papel.ADMIN)

# ----------------------------------------------------------------------------
# Novo pedido
# ----------------------------------------------------------------------------
st.subheader("Novo pedido")
compradores = catalogo.compradores_permitidos(ator)
produtos = catalogo.listar_produtos()
if cards.erro_resultado("MongoDB", compradores) or cards.erro_resultado("MongoDB", produtos):
    st.stop()
disponiveis = [p for p in produtos.dados if p["status"] == "ativo" and p["estoque"] > 0]

if not compradores.dados:
    st.info("Não há cadastro de comprador vinculado à sua conta. Peça a um administrador para cadastrá-lo.")
elif not disponiveis:
    cards.estado_vazio("Nenhum produto disponível para compra", "Quando houver produtos ativos com estoque, eles aparecem aqui.", "package-search")
else:
    comprador = st.selectbox("Comprador", compradores.dados, format_func=lambda u: f"{u['nome']} {u['sobrenome']}", disabled=not admin)
    produto = st.selectbox("Produto", disponiveis, format_func=lambda p: f"{p['titulo']} — {moeda(p['preco'])} ({p['estoque']} em estoque)")
    qtd = st.number_input("Quantidade", min_value=1, max_value=int(produto["estoque"]), value=1, step=1)
    total = produto["preco"] * int(qtd)
    st.markdown(f"**Total: {moeda(total)}**")
    if st.button("Confirmar pedido", type="primary"):
        r = catalogo.criar_pedido(ator, comprador["id"], produto["id"], int(qtd))
        if resposta("MongoDB", r, f"Pedido criado. Total: {moeda(r.dados['total']) if r.ok else ''}"):
            st.rerun()
st.caption("O cancelamento de pedidos não existe nas regras do núcleo (a CLI também não o oferece), por isso não é exposto aqui.")

# ----------------------------------------------------------------------------
# Listagem
# ----------------------------------------------------------------------------
st.subheader("Pedidos" if admin else "Meus pedidos")
res = catalogo.listar_pedidos(ator)
if not cards.erro_resultado("MongoDB", res):
    pedidos = res.dados
    cards.tabela(
        [{**p, "data": data_hora(p["criado_em"]), "itens_txt": ", ".join(f"{i['titulo']} x{i['quantidade']}" for i in p["itens"]), "total_txt": moeda(p["total"])} for p in pedidos],
        {"data": "Data", "comprador": "Comprador", "itens_txt": "Itens", "total_txt": "Total", "status": "Status"}, "Nenhum pedido encontrado.",
    )
    if pedidos:
        p = st.selectbox("Detalhes do pedido", pedidos, format_func=lambda x: f"{data_hora(x['criado_em'])} — {moeda(x['total'])}")
        cards.tabela(
            [{**i, "preco_unitario": moeda(i["preco_unitario"]), "total": moeda(i["total"])} for i in p["itens"]],
            {"titulo": "Produto", "quantidade": "Qtd", "preco_unitario": "Unitário", "total": "Total"},
        )
