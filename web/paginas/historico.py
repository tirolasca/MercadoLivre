"""Histórico de compras (Cassandra): modelagem orientada às consultas."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import resposta
from web.components.layout import abrir_pagina
from web.services import historico
from web.utils.formatacao import data_hora, mascara_cpf, moeda

ator = abrir_pagina("Histórico de compras", "Cassandra: cada tabela foi desenhada para uma consulta, sem JOIN.", icone="history")
admin, logado = tem(ator, Papel.ADMIN), tem(ator, Papel.USUARIO)

aba_cat, aba_compras, aba_modelo = st.tabs(["Produtos por categoria", "Compras por usuário", "Modelagem"])

with aba_cat:
    st.write("Consulta em `produto_por_categoria`: a categoria é a *partition key* e o título é a *clustering key*, então a lista já vem em ordem alfabética e a busca por prefixo é uma faixa de chaves.")
    cats = historico.categorias()
    if not cards.erro_resultado("Cassandra", cats):
        if not cats.dados:
            cards.estado_vazio("Ainda não há produtos no Cassandra", "Carregue os dados de demonstração no fim da página para ver o histórico.", "history")
        else:
            a, b = st.columns([1, 2])
            categoria = a.selectbox("Categoria", cats.dados)
            prefixo = b.text_input("Prefixo do título (diferencia maiúsculas)", placeholder="ex.: Te", max_chars=40)
            res = historico.produtos_da_categoria(categoria, prefixo)
            if not cards.erro_resultado("Cassandra", res):
                cards.tabela([{**p, "preco": moeda(p["preco"])} for p in res.dados], {"titulo": "Título", "preco": "Preço", "id_produto": "Id"}, "Nenhum produto com esse prefixo.")

with aba_compras:
    if not logado:
        st.info("Faça login para consultar compras.")
    else:
        cpf = None
        if admin:
            us = historico.usuarios(ator)
            if not cards.erro_resultado("Cassandra", us):
                if us.dados:
                    escolhido = st.selectbox("Usuário", us.dados, format_func=lambda u: f"{u['nome']} — CPF {mascara_cpf(u['cpf'])}")
                    cpf = escolhido["cpf"]
                else:
                    st.info("Nenhum usuário no Cassandra.")
        else:
            meu = historico.cpf_do_proprio_usuario(ator)
            if not cards.erro_resultado("Cassandra", meu):
                cpf = meu.dados
                if not cpf:
                    st.info("Não há cadastro no Cassandra vinculado ao e-mail da sua conta.")
        if cpf:
            res = historico.compras_do_usuario(ator, cpf)
            if not cards.erro_resultado("Cassandra", res):
                st.caption("Tabela `compra_por_usuario`: ordenada da compra mais nova para a mais antiga pela clustering key.")
                cards.tabela([{**c, "data": data_hora(c["data"]), "total": moeda(c["total"])} for c in res.dados], {"data": "Data", "titulo": "Produto", "quantidade": "Qtd", "total": "Total", "status": "Status"}, "Nenhuma compra registrada.")

with aba_modelo:
    st.write("Cada consulta tem a sua tabela. O mesmo dado pode ser gravado em duas (denormalização): escrever é barato, consultar fica rápido.")
    cards.tabela([{"t": t, "p": p, "c": c, "u": u} for t, p, c, u in historico.MODELAGEM], {"t": "Tabela", "p": "Partition key", "c": "Clustering key", "u": "Consulta que atende"})
    st.markdown("**Consulta fora da chave:** o Cassandra recusa filtrar por um campo que não é chave, pois varreria o cluster inteiro.")
    if st.button("Tentar buscar produto por título"):
        r = historico.consulta_sem_chave("Teclado")
        if not cards.erro_resultado("Cassandra", r):
            st.code(r.dados)
    if admin:
        st.divider()
        if st.button("Carregar dados de demonstração (Cassandra)"):
            resposta("Cassandra", historico.carregar_demonstracao(ator), "Dados de demonstração carregados.", recarregar=False)
