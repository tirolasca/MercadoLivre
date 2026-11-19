"""Sessões e cache: demonstração do Redis (TTL, tentativas de login e fluxo de cache)."""

from __future__ import annotations

import streamlit as st

from web.auth.permissoes import Papel, tem
from web.components import cards
from web.components.feedback import resposta
from web.components.layout import abrir_pagina
from web.services import sessoes

ator = abrir_pagina("Sessões e cache", "Redis: chave-valor em memória com expiração automática (TTL).")
admin, logado = tem(ator, Papel.ADMIN), tem(ator, Papel.USUARIO)

estado = sessoes.estado()
if cards.erro_resultado("Redis", estado):
    st.info("A autenticação continua funcionando com armazenamento temporário em memória enquanto o Redis estiver fora do ar.")
    st.stop()
e = estado.dados
cards.cards([
    {"rotulo": "Conexão", "valor": "Online", "nota": f"memória usada: {e['memoria_usada']}"},
    {"rotulo": "Sessões de login (web)", "valor": e["sessoes_login"]},
    {"rotulo": "Sessões de demonstração", "valor": e["sessoes_demo"], "nota": f"TTL padrão: {e['ttl_padrao']} s"},
    {"rotulo": "Limite de tentativas", "valor": e["max_falhas"], "nota": f"janela de {e['janela_falhas']} s"},
])

aba_ttl, aba_ativas, aba_tent, aba_fluxo = st.tabs(["Demonstração do TTL", "Sessões ativas", "Tentativas de login", "Fluxo MongoDB → Redis → MongoDB"])

# ----------------------------------------------------------------------------
with aba_ttl:
    st.write("Uma sessão é uma chave com prazo de validade (`SET chave valor EX segundos`). Cada ação renova o prazo (sessão deslizante) e o Redis apaga a chave sozinho ao expirar.")
    if not logado:
        st.info("Faça login para criar uma sessão de demonstração.")
    else:
        if st.button("Criar sessão de demonstração", type="primary"):
            r = sessoes.criar_sessao_demo(ator)
            if resposta("Redis", r, invalidar_cache=True):
                st.session_state["demo_chave"] = r.dados
        chave = st.session_state.get("demo_chave")
        if chave:
            @st.fragment(run_every=1)
            def contagem() -> None:
                ttl = sessoes.ttl_da_sessao(chave)
                restante = ttl.dados if ttl.ok else 0
                if restante > 0:
                    st.progress(min(restante / e["ttl_padrao"], 1.0), text=f"Sessão ativa: {restante} s restantes")
                else:
                    st.warning("A sessão expirou: o Redis removeu a chave sozinho.")
            contagem()
            a, b = st.columns(2)
            if a.button("Renovar prazo (ação do usuário)"):
                resposta("Redis", sessoes.renovar_sessao_demo(ator, chave), "Prazo renovado.", invalidar_cache=False)
            if b.button("Encerrar sessão (logout)"):
                resposta("Redis", sessoes.encerrar_sessao_demo(ator, chave), "Sessão encerrada.", invalidar_cache=False)
                st.session_state.pop("demo_chave", None)

# ----------------------------------------------------------------------------
with aba_ativas:
    st.caption("O conteúdo das sessões nunca é exibido; só a chave e o tempo restante." + ("" if admin else " E-mails aparecem mascarados."))
    res = sessoes.sessoes_ativas(ator)
    if not cards.erro_resultado("Redis", res):
        cards.tabela(res.dados, {"chave": "Chave", "tipo": "Tipo", "ttl": "Expira em (s)"}, "Nenhuma sessão ativa agora.")

with aba_tent:
    st.write(f"Após {e['max_falhas']} tentativas inválidas, o usuário fica bloqueado até o contador expirar (`INCR` + `EXPIRE`).")
    res = sessoes.tentativas_de_login(ator)
    if not cards.erro_resultado("Redis", res):
        cards.tabela(res.dados, {"usuario": "Usuário", "tentativas": "Tentativas", "limite": "Limite", "bloqueado": "Bloqueado", "reinicia_em": "Zera em (s)"}, "Nenhuma tentativa inválida registrada.")

with aba_fluxo:
    st.write("Move 2 produtos do MongoDB para o Redis, faz um CRUD neles e os devolve ao MongoDB. Se algo falhar no meio, os itens são devolvidos mesmo assim.")
    if not admin:
        st.info("Esta demonstração altera temporariamente o catálogo e é restrita a administradores.")
    else:
        ok = st.checkbox("Entendo que os produtos ficam fora do catálogo durante a execução")
        if st.button("Executar fluxo", type="primary", disabled=not ok):
            with st.status("Executando...", expanded=True) as status:
                r = sessoes.executar_fluxo(ator)
                if r.ok:
                    for etapa, msg, dados in r.dados:
                        if etapa == "titulo":
                            st.markdown(f"**{msg}**")
                        elif etapa == "json":
                            st.caption(msg)
                            st.code(dados, language="json")
                        elif etapa == "aviso":
                            st.warning(msg)
                        else:
                            st.write(f"✔ {msg}")
                    status.update(label="Fluxo concluído", state="complete")
                else:
                    status.update(label="Falhou", state="error")
                    cards.erro_resultado("Redis/MongoDB", r)
