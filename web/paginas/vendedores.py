"""Vendedores: consulta pública e gestão pelo administrador."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import pedir_confirmacao, resposta
from web.components.layout import abrir_pagina
from web.services import catalogo
from web.utils.formatacao import formatar_cnpj, moeda

ator = abrir_pagina("Vendedores", "Lojas do marketplace e seus produtos (MongoDB).", icone="store")
admin = tem(ator, Papel.ADMIN)

termo = st.text_input("Pesquisar por loja ou CNPJ", max_chars=80)
res = catalogo.listar_vendedores(termo)
if cards.erro_resultado("MongoDB", res):
    st.stop()
vendedores = res.dados
cards.tabela(
    [{**v, "cnpj": formatar_cnpj(v["cnpj"]), "nota": str(v["avaliacao"])} for v in vendedores],
    {"nome_loja": "Loja", "cnpj": "CNPJ", "nota": "Nota", "status": "Status"}, "Nenhum vendedor encontrado.",
)

if vendedores:
    st.subheader("Detalhes e produtos")
    v = st.selectbox("Vendedor", vendedores, format_func=lambda x: x["nome_loja"], key="detalhe_vendedor")
    st.markdown(f"**{v['nome_loja']}** · CNPJ {formatar_cnpj(v['cnpj'])} · {v['status']}")
    prods = catalogo.produtos_do_vendedor(v["id"])
    if not cards.erro_resultado("MongoDB", prods):
        cards.tabela([{**p, "preco": moeda(p["preco"])} for p in prods.dados], {"titulo": "Produto", "preco": "Preço", "estoque": "Estoque", "status": "Status"}, "Esta loja ainda não tem produtos.")

if not admin:
    st.caption("O cadastro e a edição de vendedores são feitos por administradores.")
    st.stop()

st.divider()
aba_novo, aba_editar, aba_excluir = st.tabs(["Cadastrar", "Editar", "Excluir"])
with aba_novo:
    with st.form("novo_vendedor", clear_on_submit=True):
        a, b = st.columns(2)
        loja, cnpj = a.text_input("Nome da loja", max_chars=80), b.text_input("CNPJ", max_chars=18)
        if st.form_submit_button("Cadastrar vendedor", type="primary"):
            if resposta("MongoDB", catalogo.criar_vendedor(ator, loja, cnpj), "Vendedor cadastrado."):
                st.rerun()
if vendedores:
    with aba_editar:
        alvo = st.selectbox("Vendedor a editar", vendedores, format_func=lambda x: x["nome_loja"], key="editar_vendedor")
        with st.form(f"editar_{alvo['id']}"):
            loja = st.text_input("Nome da loja", alvo["nome_loja"], max_chars=80)
            status = st.selectbox("Status", ["ativo", "inativo"], index=0 if alvo["status"] == "ativo" else 1)
            if st.form_submit_button("Salvar alterações", type="primary"):
                r = catalogo.atualizar_vendedor(ator, alvo["id"], loja, status)
                if resposta("MongoDB", r, "Vendedor atualizado." if r.ok and r.dados else None):
                    if r.dados:
                        st.rerun()
                    st.info("Nenhuma alteração informada.")
    with aba_excluir:
        alvo = st.selectbox("Vendedor a excluir", vendedores, format_func=lambda x: x["nome_loja"], key="excluir_vendedor")
        st.warning("A exclusão é permanente. Vendedores com produtos não podem ser excluídos.")
        if pedir_confirmacao(f"vendedor_{alvo['id']}", f"Excluir {alvo['nome_loja']}", "Excluir vendedor"):
            if resposta("MongoDB", catalogo.excluir_vendedor(ator, alvo["id"]), "Vendedor excluído."):
                st.rerun()
