"""Favoritos: os produtos que o usuário guardou (a lista mora DENTRO do documento dele no MongoDB)."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import resposta
from web.components.layout import abrir_pagina
from web.services import catalogo

ator = abrir_pagina("Favoritos", "Produtos que você guardou para ver depois.", minimo=Papel.USUARIO, icone="heart")
admin = tem(ator, Papel.ADMIN)

quem = catalogo.listar_usuarios(ator)
if cards.erro_resultado("MongoDB", quem):
    st.stop()
if not quem.dados:
    st.info("Não há cadastro de comprador vinculado à sua conta. Peça a um administrador para cadastrá-lo.")
    st.stop()

dono = st.selectbox("Favoritos de", quem.dados, format_func=lambda u: f"{u['nome']} {u['sobrenome']}", key="favoritos_usuario") if admin else quem.dados[0]

res = catalogo.listar_favoritos(ator, dono["id"])
if cards.erro_resultado("MongoDB", res):
    st.stop()
favoritos = res.dados
if not favoritos:
    cards.estado_vazio("Nenhum favorito ainda", "Abra Produtos, escolha um item e toque em Favoritar.", "heart-off")
    st.stop()

cards.favoritos(favoritos)

st.subheader("Gerenciar")
alvo = st.selectbox("Produto", favoritos, format_func=lambda p: p["titulo"], key="favoritos_remover")
if st.button("Remover dos favoritos", key="favoritos_btn_remover", icon=":material/delete:"):
    if resposta("MongoDB", catalogo.desfavoritar(ator, dono["id"], alvo["id"]), "Removido dos favoritos."):
        st.rerun()
