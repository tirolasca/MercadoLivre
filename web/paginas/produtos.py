"""Produtos: consulta pública e gestão pelo administrador."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import pedir_confirmacao, resposta
from web.components.layout import abrir_pagina
from web.components.paginacao import paginar
from web.services import catalogo
from web.utils.formatacao import moeda

ator = abrir_pagina("Produtos", "Catálogo do MongoDB: busca, filtros, estoque e preços.", icone="package")
admin = tem(ator, Papel.ADMIN)

ORDENS = {"titulo": "Título (A-Z)", "menor_preco": "Menor preço", "maior_preco": "Maior preço", "maior_estoque": "Maior estoque", "mais_vendidos": "Mais vendidos"}

lojas = catalogo.listar_vendedores()
categorias = catalogo.categorias()
if cards.erro_resultado("MongoDB", lojas):
    st.stop()

c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
termo = c1.text_input("Buscar por título", placeholder="ex.: teclado", max_chars=80)
categoria = c2.selectbox("Categoria", ["Todas", *(categorias.dados or [])])
nome_loja = {v["nome_loja"]: v["id"] for v in lojas.dados}
loja = c3.selectbox("Vendedor", ["Todos", *nome_loja])
ordem = c4.selectbox("Ordenar por", list(ORDENS), format_func=ORDENS.get)

res = catalogo.listar_produtos(termo, None if categoria == "Todas" else categoria, nome_loja.get(loja), ordem)
if cards.erro_resultado("MongoDB", res):
    st.stop()
produtos = res.dados

# Paginação (volta à página 1 quando um filtro muda)
_, _, fatia = paginar(len(produtos), 10, "produtos", (termo, categoria, loja, ordem))
visiveis = produtos[fatia]
cards.tabela(
    [{**p, "preco": moeda(p["preco"])} for p in visiveis],
    {"titulo": "Título", "preco": "Preço", "estoque": "Estoque", "vendidos": "Vendidos", "categoria": "Categoria", "loja": "Loja", "status": "Status"},
    "Nenhum produto encontrado com esses filtros.",
)

# Detalhes
if produtos:
    st.subheader("Detalhes")
    escolhido = st.selectbox("Produto", produtos, format_func=lambda p: f"{p['titulo']} — {moeda(p['preco'])}", key="detalhe_produto")
    st.markdown(f"**{escolhido['titulo']}** · {moeda(escolhido['preco'])} · {escolhido['estoque']} em estoque · loja **{escolhido['loja']}**")
    st.write(escolhido["descricao"] or "_Sem descrição._")

    # Favoritar: a lista fica dentro do documento do usuário (visitante não tem cadastro, então não vê o botão).
    if tem(ator, Papel.USUARIO):
        quem = catalogo.listar_usuarios(ator)
        if not quem.ok:
            cards.erro_resultado("MongoDB", quem)
        elif quem.dados:
            dono = st.selectbox("Favoritar para", quem.dados, format_func=lambda u: f"{u['nome']} {u['sobrenome']}", key="fav_dono") if admin else quem.dados[0]
            ja = escolhido["id"] in dono["favoritos"]
            rotulo = "Nos favoritos — remover" if ja else "Favoritar"
            if st.button(rotulo, key=f"{'fav-ativo' if ja else 'fav-inativo'}-{escolhido['id']}", icon=":material/favorite:"):
                acao = catalogo.desfavoritar if ja else catalogo.favoritar
                if resposta("MongoDB", acao(ator, dono["id"], escolhido["id"]), "Removido dos favoritos." if ja else "Adicionado aos favoritos."):
                    st.rerun()

if not admin:
    st.caption("O cadastro e a edição de produtos são feitos por administradores.")
    st.stop()

# ----------------------------------------------------------------------------
# Gestão (administrador)
# ----------------------------------------------------------------------------
st.divider()
aba_novo, aba_editar, aba_excluir = st.tabs(["Cadastrar", "Editar / estoque", "Excluir"])

with aba_novo:
    ativas = {v["nome_loja"]: v["id"] for v in lojas.dados if v["status"] == "ativo"}
    if not ativas:
        cards.estado_vazio("Cadastre um vendedor ativo primeiro", "Todo produto pertence a uma loja. Crie o vendedor na página Vendedores e volte aqui.", "store")
    else:
        with st.form("novo_produto", clear_on_submit=True):
            vendedor = st.selectbox("Vendedor", list(ativas))
            titulo = st.text_input("Título", max_chars=120)
            descricao = st.text_area("Descrição", max_chars=500)
            a, b, c = st.columns(3)
            preco = a.text_input("Preço (R$)", placeholder="150,00")
            estoque = b.number_input("Estoque", min_value=0, step=1)
            cat = c.text_input("Categoria", placeholder="MLB1648", max_chars=20)
            if st.form_submit_button("Cadastrar produto", type="primary"):
                if resposta("MongoDB", catalogo.criar_produto(ator, ativas[vendedor], titulo, descricao, preco, str(int(estoque)), cat), "Produto cadastrado."):
                    st.rerun()

with aba_editar:
    if produtos:
        alvo = st.selectbox("Produto a editar", produtos, format_func=lambda p: p["titulo"], key="editar_produto")
        with st.form(f"editar_{alvo['id']}"):
            titulo = st.text_input("Título", alvo["titulo"], max_chars=120)
            descricao = st.text_area("Descrição", alvo["descricao"], max_chars=500)
            a, b = st.columns(2)
            preco = a.text_input("Preço (R$)", str(alvo["preco"]))
            estoque = b.number_input("Estoque", min_value=0, value=int(alvo["estoque"]), step=1)
            if st.form_submit_button("Salvar alterações", type="primary"):
                res = catalogo.atualizar_produto(ator, alvo["id"], titulo, descricao, preco, str(int(estoque)))
                if resposta("MongoDB", res, "Produto atualizado." if res.ok and res.dados else None) and not res.dados:
                    st.info("Nenhuma alteração informada.")
                elif res.ok:
                    st.rerun()

with aba_excluir:
    if produtos:
        alvo = st.selectbox("Produto a excluir", produtos, format_func=lambda p: p["titulo"], key="excluir_produto")
        st.warning("A exclusão é permanente. Produtos com histórico de pedidos não podem ser excluídos.")
        if pedir_confirmacao(f"produto_{alvo['id']}", f"Excluir “{alvo['titulo']}”", "Excluir produto"):
            if resposta("MongoDB", catalogo.excluir_produto(ator, alvo["id"]), "Produto excluído."):
                st.rerun()

st.divider()
st.caption("Primeira execução? Carregue um conjunto de exemplo (2 usuários, 2 lojas, 4 produtos). É seguro repetir: nada é duplicado.")
if st.button("Carregar dados de demonstração (MongoDB)"):
    if resposta("MongoDB", catalogo.carregar_demonstracao(ator), "Dados de demonstração carregados."):
        st.rerun()
