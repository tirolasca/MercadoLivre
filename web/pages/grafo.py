"""Grafo de relacionamentos (Neo4j): visualização interativa e consultas."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as componentes

from web.auth.permissoes import Papel, tem
from web.components import cards, grafo_pyvis
from web.components.feedback import resposta
from web.components.layout import abrir_pagina
from web.services import grafo
from web.utils.formatacao import data_hora, mascara_cpf, moeda

ator = abrir_pagina("Grafo de relacionamentos", "Neo4j: nós e relacionamentos reais entre usuários, compras, produtos, lojas e categorias.")
admin, logado = tem(ator, Papel.ADMIN), tem(ator, Papel.USUARIO)

resumo = grafo.resumo()
if cards.erro_resultado("Neo4j", resumo):
    st.stop()
nos_total = {n["nome"]: n["total"] for n in resumo.dados["nos"]}
cards.cards([{"rotulo": grafo_pyvis.ROTULOS.get(n["nome"], n["nome"]), "valor": n["total"], "nota": "nós"} for n in resumo.dados["nos"]] + [{"rotulo": r["nome"], "valor": r["total"], "nota": "relacionamentos"} for r in resumo.dados["relacoes"]])
if not nos_total:
    st.info("O grafo está vazio." + (" Use o botão no fim da página para carregar os dados de demonstração." if admin else ""))

aba_grafo, aba_prod, aba_lojas, aba_compras = st.tabs(["Visualização", "Produtos", "Lojas", "Compras (caminho)"])

# ----------------------------------------------------------------------------
with aba_grafo:
    cpf = None
    if admin:
        termo = st.text_input("Filtrar por usuário (nome, e-mail ou CPF). Vazio = grafo completo", max_chars=80)
        if termo:
            us = grafo.buscar_usuarios(ator, termo)
            if not cards.erro_resultado("Neo4j", us) and us.dados:
                u = st.selectbox("Usuário", us.dados, format_func=lambda x: f"{x['nome']} {x['sobrenome']} — {mascara_cpf(x['cpf'])}")
                cpf = u["cpf"]
            elif us.ok:
                st.info("Nenhum usuário encontrado.")
    elif logado:
        if st.toggle("Mostrar apenas as minhas compras"):
            meu = grafo.cpf_do_proprio_usuario(ator)
            if meu.ok and meu.dados:
                cpf = meu.dados
            elif meu.ok:
                st.info("Não há usuário no grafo vinculado ao e-mail da sua conta.")
    else:
        st.caption("Visão pública: lojas, produtos e categorias. Faça login para ver mais.")

    sub = grafo.subgrafo(ator, cpf)
    if not cards.erro_resultado("Neo4j", sub):
        if not sub.dados["nos"]:
            st.info("Não há relacionamentos para desenhar.")
        else:
            st.markdown(grafo_pyvis.legenda_html(), unsafe_allow_html=True)
            componentes.html(grafo_pyvis.gerar_html(sub.dados["nos"], sub.dados["arestas"]), height=580)
            st.caption(f"{len(sub.dados['nos'])} nós e {len(sub.dados['arestas'])} relacionamentos (limite de 150 arestas). Arraste os nós, use o zoom e passe o mouse para ver os detalhes.")
            escolhido = st.selectbox("Detalhes de um elemento", sub.dados["nos"], format_func=lambda n: f"{grafo_pyvis.ROTULOS.get(n['rotulo'], n['rotulo'])}: {n['nome']}")
            st.json({k: str(v) for k, v in escolhido["propriedades"].items()})
            ligacoes = [a for a in sub.dados["arestas"] if escolhido["id"] in (a["origem"], a["destino"])]
            nomes = {n["id"]: n["nome"] for n in sub.dados["nos"]}
            cards.tabela([{"de": nomes[a["origem"]], "tipo": a["tipo"], "para": nomes[a["destino"]]} for a in ligacoes], {"de": "De", "tipo": "Relacionamento", "para": "Para"}, "Sem relacionamentos neste recorte.")

# ----------------------------------------------------------------------------
with aba_prod:
    cats = grafo.categorias()
    a, b = st.columns([2, 1])
    termo = a.text_input("Título contém", key="g_termo", max_chars=60)
    cat = b.selectbox("Categoria", ["Todas", *(cats.dados or [])], key="g_cat")
    res = grafo.buscar_produtos(termo, None if cat == "Todas" else cat)
    if not cards.erro_resultado("Neo4j", res):
        cards.tabela([{**p, "preco": moeda(p["preco"])} for p in res.dados], {"titulo": "Produto", "preco": "Preço", "quantidade_disponivel": "Estoque", "id_categoria": "Categoria", "nome_loja": "Loja"}, "Nenhum produto encontrado.")

with aba_lojas:
    termo = st.text_input("Loja ou CNPJ contém", key="g_loja", max_chars=60)
    res = grafo.buscar_vendedores(termo)
    if not cards.erro_resultado("Neo4j", res):
        cards.tabela(res.dados, {"nome_loja": "Loja", "cnpj": "CNPJ", "status": "Status", "total_produtos": "Produtos"}, "Nenhuma loja encontrada.")

with aba_compras:
    st.write("Caminho percorrido: **Usuário → Compra → Produto ← Loja**.")
    if not logado:
        st.info("Faça login para explorar compras.")
    else:
        cpf = None
        if admin:
            us = grafo.buscar_usuarios(ator, None)
            if not cards.erro_resultado("Neo4j", us) and us.dados:
                u = st.selectbox("Usuário", us.dados, format_func=lambda x: f"{x['nome']} {x['sobrenome']} — {mascara_cpf(x['cpf'])}", key="g_user")
                cpf = u["cpf"]
        else:
            meu = grafo.cpf_do_proprio_usuario(ator)
            cpf = meu.dados if meu.ok else None
            if meu.ok and not cpf:
                st.info("Não há usuário no grafo vinculado ao e-mail da sua conta.")
        if cpf:
            res = grafo.compras(ator, cpf=cpf)
            if not cards.erro_resultado("Neo4j", res):
                cards.tabela(
                    [{"data": data_hora(c["data_compra"]), "usuario": c["nome_usuario"], "compra": f"{c['quantidade']}x {c['titulo']}", "loja": c["nome_loja"], "total": moeda(c["valor_total"])} for c in res.dados],
                    {"data": "Data", "usuario": "Usuário", "compra": "Compra → Produto", "loja": "Loja", "total": "Total"}, "Nenhuma compra para este usuário.",
                )

if admin:
    st.divider()
    if st.button("Carregar dados de demonstração (Neo4j)"):
        if resposta("Neo4j", grafo.carregar_demonstracao(ator), "Dados de demonstração carregados."):
            st.rerun()
