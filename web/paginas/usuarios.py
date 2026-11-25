"""Usuários: administrador gerencia; usuário comum vê só o próprio perfil."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import pedir_confirmacao, resposta
from web.components.layout import abrir_pagina
from web.services import catalogo
from web.utils.formatacao import data_hora, formatar_cpf, moeda

ator = abrir_pagina("Usuários", "Cadastro de compradores (MongoDB).", minimo=Papel.USUARIO, icone="users")
admin = tem(ator, Papel.ADMIN)

termo = st.text_input("Pesquisar por nome, e-mail ou CPF", max_chars=80) if admin else ""
res = catalogo.listar_usuarios(ator, termo)
if cards.erro_resultado("MongoDB", res):
    st.stop()
usuarios = res.dados
if not admin and not usuarios:
    st.info("Não há cadastro de comprador vinculado ao e-mail da sua conta.")
    st.stop()

cards.tabela(
    [{**u, "nome_completo": f"{u['nome']} {u['sobrenome']}", "cpf": formatar_cpf(u["cpf"]), "qtd_end": len(u["enderecos"]), "criado": data_hora(u["criado_em"])} for u in usuarios],
    {"nome_completo": "Nome", "cpf": "CPF", "email": "E-mail", "qtd_end": "Endereços", "criado": "Cadastro"},
    "Nenhum usuário encontrado.",
)

if usuarios:
    st.subheader("Detalhes")
    u = st.selectbox("Usuário", usuarios, format_func=lambda x: f"{x['nome']} {x['sobrenome']}", key="detalhe_usuario")
    st.markdown(f"**{u['nome']} {u['sobrenome']}** · CPF {formatar_cpf(u['cpf'])} · {u['email']}")
    cards.tabela(u["enderecos"], {"rua": "Rua", "numero": "Nº", "bairro": "Bairro", "cidade": "Cidade", "estado": "UF", "cep": "CEP"}, "Nenhum endereço cadastrado.")

    st.markdown("**Favoritos**")
    favs = catalogo.listar_favoritos(ator, u["id"])
    if not cards.erro_resultado("MongoDB", favs):
        cards.tabela(
            [{**f, "preco": moeda(f["preco"]), "desde": data_hora(f["favoritado_em"])} for f in favs.dados],
            {"titulo": "Produto", "preco": "Preço", "loja": "Loja", "desde": "Favoritado em"}, "Nenhum favorito cadastrado.",
        )

if not admin:
    st.stop()

st.divider()
aba_novo, aba_editar, aba_end, aba_excluir = st.tabs(["Cadastrar", "Editar", "Adicionar endereço", "Excluir"])
with aba_novo:
    with st.form("novo_usuario", clear_on_submit=True):
        a, b = st.columns(2)
        nome, sobrenome = a.text_input("Nome", max_chars=60), b.text_input("Sobrenome", max_chars=60)
        c, d = st.columns(2)
        cpf, email = c.text_input("CPF", max_chars=14), d.text_input("E-mail", max_chars=120)
        if st.form_submit_button("Cadastrar usuário", type="primary"):
            if resposta("MongoDB", catalogo.criar_usuario(ator, nome, sobrenome, cpf, email), "Usuário cadastrado."):
                st.rerun()
if usuarios:
    with aba_editar:
        alvo = st.selectbox("Usuário a editar", usuarios, format_func=lambda x: f"{x['nome']} {x['sobrenome']}", key="editar_usuario")
        with st.form(f"editar_{alvo['id']}"):
            nome = st.text_input("Nome", alvo["nome"], max_chars=60)
            sobrenome = st.text_input("Sobrenome", alvo["sobrenome"], max_chars=60)
            email = st.text_input("E-mail", alvo["email"], max_chars=120)
            if st.form_submit_button("Salvar alterações", type="primary"):
                r = catalogo.atualizar_usuario(ator, alvo["id"], nome, sobrenome, email)
                if resposta("MongoDB", r, "Usuário atualizado." if r.ok and r.dados else None):
                    if r.dados:
                        st.rerun()
                    st.info("Nenhuma alteração informada.")
    with aba_end:
        alvo = st.selectbox("Usuário", usuarios, format_func=lambda x: f"{x['nome']} {x['sobrenome']}", key="end_usuario")
        with st.form(f"end_{alvo['id']}", clear_on_submit=True):
            a, b, c = st.columns([2, 3, 1])
            cep, rua, numero = a.text_input("CEP"), b.text_input("Rua"), c.text_input("Nº")
            d, e, f = st.columns([2, 2, 1])
            bairro, cidade, uf = d.text_input("Bairro"), e.text_input("Cidade"), f.text_input("UF", max_chars=2)
            complemento = st.text_input("Complemento (opcional)")
            if st.form_submit_button("Adicionar endereço", type="primary"):
                if resposta("MongoDB", catalogo.adicionar_endereco(ator, alvo["id"], cep=cep, rua=rua, numero=numero, bairro=bairro, cidade=cidade, estado=uf, complemento=complemento), "Endereço adicionado."):
                    st.rerun()
    with aba_excluir:
        alvo = st.selectbox("Usuário a excluir", usuarios, format_func=lambda x: f"{x['nome']} {x['sobrenome']}", key="excluir_usuario")
        st.warning("A exclusão é permanente e remove também os favoritos. Usuários com pedidos não podem ser excluídos.")
        if pedir_confirmacao(f"usuario_{alvo['id']}", f"Excluir {alvo['nome']} {alvo['sobrenome']}", "Excluir usuário"):
            if resposta("MongoDB", catalogo.excluir_usuario(ator, alvo["id"]), "Usuário excluído."):
                st.rerun()
