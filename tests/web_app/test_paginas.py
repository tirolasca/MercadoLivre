from collections import namedtuple

import pymongo.errors
import pytest
from streamlit.testing.v1 import AppTest

from mercadolivre import catalogo_dados, sessoes_dados
from web import state
from web.services import grafo as svc_grafo
from web.services import historico as svc_historico

from .conftest import SENHA

PAGINAS = ["dashboard", "produtos", "vendedores", "usuarios", "pedidos", "sessoes", "historico", "grafo", "diagnostico"]


def por_rotulo(lista, rotulo, n=0):
    return [e for e in lista if e.label == rotulo][n]


def textos(at):
    avisos = [*at.info, *at.warning, *at.error, *at.success, *at.caption]
    return " ".join(m.value for m in at.markdown) + " " + " ".join(e.value for e in avisos)


# ----------------------------------------------------------------------------
# Todas as páginas abrem em todos os papéis, mesmo com Cassandra e Neo4j fora do ar
# ----------------------------------------------------------------------------
@pytest.mark.parametrize("pg", PAGINAS)
@pytest.mark.parametrize("quem", [None, "ana", "admin"])
def test_pagina_abre_sem_excecao(pagina, semeado, token, pg, quem):
    at = pagina(pg, token(quem) if quem else None)
    assert not at.exception, [e.value for e in at.exception]


def test_paginas_restritas_pedem_login_ao_visitante(pagina, semeado):
    for pg in ("usuarios", "pedidos"):
        at = pagina(pg)
        assert any("exige login" in w.value for w in at.warning)
        assert not at.tabs and not at.dataframe  # nada de dados atrás da trava


def test_cassandra_e_neo4j_fora_do_ar_aparecem_como_indisponiveis(pagina, semeado):
    assert "Cassandra indisponível" in textos(pagina("historico"))
    assert "Neo4j indisponível" in textos(pagina("grafo"))
    dash = textos(pagina("dashboard"))
    assert "Neo4j indisponível" in dash and "Cassandra indisponível" in dash
    assert "Usuários" in dash  # o resto do dashboard continua funcionando


def test_dashboard_com_mongo_fora_do_ar_mostra_indisponibilidade(pagina, monkeypatch):
    monkeypatch.setattr(catalogo_dados, "mongo_db", lambda: (_ for _ in ()).throw(pymongo.errors.ServerSelectionTimeoutError("timeout")))
    at = pagina("dashboard")
    assert not at.exception
    assert "MongoDB indisponível" in textos(at) and "Indisponível" in textos(at)
    assert "R$" not in " ".join(m.value for m in at.markdown if "ml-card" in m.value)  # nenhum valor inventado


def test_dashboard_usa_dados_reais(pagina, semeado, token):
    at = pagina("dashboard")
    html = " ".join(m.value for m in at.markdown if "ml-cards" in m.value)
    assert "R$ 450,00" in html  # valor em estoque (patch do mongomock)
    assert ">2<" in html  # 2 usuários


# ----------------------------------------------------------------------------
# Autorização: a tela não concede nada que o servidor não concedeu
# ----------------------------------------------------------------------------
def test_editar_o_session_state_nao_eleva_permissao(pagina, semeado):
    at = AppTest.from_file(str(state.__file__).replace("state.py", "pages/usuarios.py"), default_timeout=30)
    at.session_state["papel"] = "admin"
    at.session_state["ator"] = "admin"
    at.session_state[state.CHAVE_TOKEN] = "token-forjado"
    at.run()
    assert any("exige login" in w.value for w in at.warning)


def test_visitante_nao_ve_formularios_de_escrita(pagina, semeado):
    at = pagina("produtos")
    assert not at.tabs and "Cadastrar produto" not in [b.label for b in at.button]
    at = pagina("vendedores")
    assert not at.tabs


def test_usuario_comum_nao_ve_gestao_de_produtos_nem_usuarios_alheios(pagina, semeado, token):
    assert not pagina("produtos", token("ana")).tabs
    at = pagina("usuarios", token("ana"))
    tabela = at.dataframe[0].value
    assert list(tabela["E-mail"]) == ["ana@exemplo.com"]
    assert not at.tabs  # sem cadastrar/editar/excluir


def test_isolamento_entre_sessoes_o_admin_nao_vaza_para_o_visitante(pagina, semeado, token, redis_falso):
    redis_falso.set("session:maria@exemplo.com", "{}", ex=60)
    adm = pagina("sessoes", token("admin"))
    vis = pagina("sessoes")
    chaves_admin = " ".join(" ".join(df.value["Chave"]) for df in adm.dataframe if "Chave" in df.value)
    chaves_vis = " ".join(" ".join(df.value["Chave"]) for df in vis.dataframe if "Chave" in df.value)
    assert "session:maria@exemplo.com" in chaves_admin
    assert "maria@" not in chaves_vis and "session:m***@exemplo.com" in chaves_vis


# ----------------------------------------------------------------------------
# Operações reais pela interface
# ----------------------------------------------------------------------------
def test_admin_cadastra_produto_pelo_formulario(pagina, semeado, token):
    at = pagina("produtos", token("admin"))
    por_rotulo(at.text_input, "Título", 0).set_value("Mouse Gamer")
    por_rotulo(at.text_input, "Preço (R$)", 0).set_value("89,90")
    por_rotulo(at.number_input, "Estoque", 0).set_value(4)
    por_rotulo(at.text_input, "Categoria", 0).set_value("mlb1649")
    por_rotulo(at.button, "Cadastrar produto").click().run()
    assert not at.exception
    novo = catalogo_dados.colecao("produtos").find_one({"titulo": "Mouse Gamer"})
    assert novo and novo["quantidade_disponivel"] == 4 and novo["id_categoria"] == "MLB1649"


def test_formulario_de_produto_mostra_erro_de_validacao(pagina, semeado, token):
    at = pagina("produtos", token("admin"))
    por_rotulo(at.text_input, "Título", 0).set_value("Sem preço")
    por_rotulo(at.text_input, "Categoria", 0).set_value("mlb1")
    por_rotulo(at.button, "Cadastrar produto").click().run()
    assert at.error and catalogo_dados.colecao("produtos").count_documents({}) == 1


def test_exclusao_exige_confirmacao_explicita(pagina, semeado, token):
    at = pagina("produtos", token("admin"))
    botao = por_rotulo(at.button, "Excluir produto")
    assert botao.disabled  # sem marcar a confirmação, o botão não funciona
    at.checkbox[0].check().run()
    botao = por_rotulo(at.button, "Excluir produto")
    assert not botao.disabled
    botao.click().run()
    assert catalogo_dados.colecao("produtos").count_documents({}) == 0


def test_usuario_faz_pedido_apenas_em_seu_nome(pagina, semeado, token):
    at = pagina("pedidos", token("ana"))
    comprador = por_rotulo(at.selectbox, "Comprador")
    assert comprador.disabled and len(comprador.options) == 1
    por_rotulo(at.button, "Confirmar pedido").click().run()
    assert not at.exception
    pedido = catalogo_dados.colecao("pedidos").find_one()
    assert pedido["id_comprador"] == semeado["ana"]["_id"]
    assert catalogo_dados.colecao("produtos").find_one()["quantidade_disponivel"] == 4


def test_pagina_de_pedidos_informa_que_nao_ha_cancelamento(pagina, semeado, token):
    assert "cancelamento" in textos(pagina("pedidos", token("admin")))


def test_admin_cadastra_vendedor_e_usuario(pagina, semeado, token):
    at = pagina("vendedores", token("admin"))
    por_rotulo(at.text_input, "Nome da loja", 0).set_value("Outra Loja")
    por_rotulo(at.text_input, "CNPJ").set_value("11222333000181")
    por_rotulo(at.button, "Cadastrar vendedor").click().run()
    assert catalogo_dados.colecao("vendedores").find_one({"nome_loja": "Outra Loja"})
    at = pagina("usuarios", token("admin"))
    por_rotulo(at.text_input, "Nome", 0).set_value("Carla")
    por_rotulo(at.text_input, "Sobrenome", 0).set_value("Dias")
    por_rotulo(at.text_input, "CPF").set_value("390.533.447-05")
    por_rotulo(at.text_input, "E-mail", 0).set_value("carla@exemplo.com")
    por_rotulo(at.button, "Cadastrar usuário").click().run()
    assert catalogo_dados.colecao("usuarios").find_one({"email": "carla@exemplo.com"})


# ----------------------------------------------------------------------------
# Redis: demonstração do TTL
# ----------------------------------------------------------------------------
def test_sessao_de_demonstracao_pela_pagina(pagina, semeado, token, redis_falso):
    assert "Faça login" in textos(pagina("sessoes"))
    at = pagina("sessoes", token("ana"))
    por_rotulo(at.button, "Criar sessão de demonstração").click().run()
    assert not at.exception
    assert redis_falso.keys("demo_sessao:*")


def test_fluxo_de_cache_e_so_do_admin_na_pagina(pagina, semeado, token, redis_falso):
    ana = pagina("sessoes", token("ana"))
    assert "Executar fluxo" not in [b.label for b in ana.button]
    at = pagina("sessoes", token("admin"))
    botao = por_rotulo(at.button, "Executar fluxo")
    assert botao.disabled
    at.checkbox[0].check().run()
    por_rotulo(at.button, "Executar fluxo").click().run()
    assert not at.exception
    assert catalogo_dados.colecao("produtos").count_documents({}) == 1 and redis_falso.keys("item_ml:*") == []


# ----------------------------------------------------------------------------
# Cassandra e Neo4j com dados (serviços já testados; aqui, a página)
# ----------------------------------------------------------------------------
def test_historico_busca_por_categoria_e_prefixo(pagina, semeado, monkeypatch):
    Linha = namedtuple("Linha", "id_produto titulo preco")
    from mercadolivre import historico as cass
    monkeypatch.setattr(cass, "listar_categorias", lambda: ["MLB1648"])
    visto = []
    monkeypatch.setattr(cass, "listar_produtos_categoria", lambda c, p=None: visto.append((c, p)) or [Linha("abc", "Teclado Gamer", 220)])
    at = pagina("historico")
    por_rotulo(at.text_input, "Prefixo do título (diferencia maiúsculas)").set_value("Te").run()
    assert ("MLB1648", "Te") in visto
    assert any("Teclado Gamer" in str(df.value.values) for df in at.dataframe)
    assert "compra_por_usuario" in " ".join(str(df.value.values) for df in at.dataframe)  # modelagem exibida


def test_grafo_desenha_nos_e_arestas_reais(pagina, semeado, monkeypatch):
    from mercadolivre import grafo as neo
    monkeypatch.setattr(neo, "resumo_do_grafo", lambda: ([{"nome": "Produto", "total": 1}, {"nome": "Vendedor", "total": 1}], [{"nome": "VENDE", "total": 1}]))
    nos = [{"id": "1", "rotulo": "Vendedor", "nome": "Loja X", "propriedades": {"nome_loja": "Loja X"}}, {"id": "2", "rotulo": "Produto", "nome": "Mouse", "propriedades": {"titulo": "Mouse"}}]
    monkeypatch.setattr(neo, "subgrafo", lambda cpf=None, com_pessoas=True, limite=150: (nos, [{"origem": "1", "destino": "2", "tipo": "VENDE"}]))
    monkeypatch.setattr(neo, "listar_categorias", lambda: [])
    monkeypatch.setattr(neo, "buscar_produtos", lambda *a, **k: [])
    monkeypatch.setattr(neo, "buscar_vendedores", lambda *a, **k: [])
    at = pagina("grafo")
    assert not at.exception
    assert "Loja X" in " ".join(str(df.value.values) for df in at.dataframe) or at.selectbox
    assert any("VENDE" in str(df.value.values) for df in at.dataframe)


# ----------------------------------------------------------------------------
# Login pela barra lateral
# ----------------------------------------------------------------------------
def _sidebar():
    from web import state as s
    from web.components import sidebar
    sidebar.renderizar(s.ator_atual())


@pytest.fixture
def barra(monkeypatch, redis_falso, contas):
    monkeypatch.setattr(state, "contas_configuradas", lambda: contas)
    return lambda: AppTest.from_function(_sidebar, default_timeout=30).run()


def test_login_correto_guarda_token_e_mostra_o_papel(barra):
    at = barra()
    at.text_input[0].set_value("admin")
    at.text_input[1].set_value(SENHA)
    at.button[0].click().run()
    assert state.CHAVE_TOKEN in at.session_state
    assert any("Conectado como" in m.value and "admin" in m.value for m in [*at.sidebar.markdown, *at.markdown])


def test_login_incorreto_mostra_erro_generico_e_nao_cria_sessao(barra):
    at = barra()
    at.text_input[0].set_value("admin")
    at.text_input[1].set_value("senha-errada-123")
    at.button[0].click().run()
    assert state.CHAVE_TOKEN not in at.session_state
    assert any(e.value == "Usuário ou senha incorretos." for e in at.error)


def test_login_bloqueia_apos_tentativas_repetidas(barra):
    at = barra()
    for _ in range(sessoes_dados.MAX_FALHAS):
        at.text_input[0].set_value("ana")
        at.text_input[1].set_value("errada-errada-1")
        at.button[0].click().run()
    at.text_input[0].set_value("ana")
    at.text_input[1].set_value(SENHA)
    at.button[0].click().run()
    assert state.CHAVE_TOKEN not in at.session_state
    assert any("Tente novamente" in e.value for e in at.error)


def test_sem_contas_configuradas_o_login_e_desativado_com_aviso(monkeypatch, redis_falso):
    monkeypatch.setattr(state, "contas_configuradas", lambda: {})
    at = AppTest.from_function(_sidebar, default_timeout=30).run()
    assert any("Nenhuma conta configurada" in c.value for c in at.caption)


def test_admin_carrega_demonstracao_do_mongo_e_repetir_nao_duplica(pagina, mongo, token):
    for _ in range(2):
        at = pagina("produtos", token("admin"))
        por_rotulo(at.button, "Carregar dados de demonstração (MongoDB)").click().run()
        assert not at.exception
    assert catalogo_dados.colecao("produtos").count_documents({}) == 4
    assert catalogo_dados.colecao("usuarios").count_documents({}) == 2


def test_usuario_comum_nao_ve_o_botao_de_demonstracao(pagina, semeado, token):
    assert "Carregar dados de demonstração (MongoDB)" not in [b.label for b in pagina("produtos", token("ana")).button]
