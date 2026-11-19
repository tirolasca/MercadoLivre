import pymongo.errors
import pytest

from mercadolivre import catalogo_dados, config
from web.auth.permissoes import VISITANTE
from web.services import catalogo, diagnostico, grafo, historico, resultado, sessoes
from web.services.resultado import Resultado, executar, sem_segredos


# ----------------------------------------------------------------------------
# Tratamento de erros / disjuntor
# ----------------------------------------------------------------------------
def test_erro_de_negocio_vira_mensagem_sem_marcar_servico_fora_do_ar():
    def op():
        raise catalogo_dados.ErroNegocio("Estoque insuficiente.")
    r = executar("MongoDB", op)
    assert not r.ok and r.erro == "Estoque insuficiente." and not r.indisponivel


def test_falha_de_infraestrutura_nao_expoe_detalhes_e_abre_o_disjuntor(caplog):
    chamadas = []

    def op():
        chamadas.append(1)
        raise pymongo.errors.ServerSelectionTimeoutError("mongodb+srv://usuario:SENHA-SECRETA@cluster0 timeout")
    r = executar("MongoDB", op)
    assert r.indisponivel and "SENHA-SECRETA" not in r.erro and "mongodb" not in r.erro.lower().replace("o mongodb", "")
    executar("MongoDB", op)  # disjuntor aberto: nem tenta de novo
    assert len(chamadas) == 1
    resultado.reiniciar_disjuntores()
    executar("MongoDB", op)
    assert len(chamadas) == 2


def test_disjuntor_e_por_banco():
    executar("Redis", lambda: (_ for _ in ()).throw(ConnectionError()))
    assert executar("MongoDB", lambda: 42).dados == 42


def test_configuracao_ausente_vira_servico_nao_configurado():
    r = executar("Neo4j", lambda: (_ for _ in ()).throw(RuntimeError("Defina NEO4J_URI e NEO4J_PASSWORD.")))
    assert r.indisponivel and "não está configurado" in r.erro


def test_erro_inesperado_e_registrado_mas_nao_derruba(caplog):
    r = executar("MongoDB", lambda: 1 / 0)
    assert not r.ok and not r.indisponivel and "inesperado" in r.erro
    assert "ZeroDivisionError" in caplog.text and "division" not in r.erro


def test_logs_nao_vazam_segredos(monkeypatch, caplog):
    monkeypatch.setenv("NEO4J_PASSWORD", "senha-super-secreta")
    assert "senha-super-secreta" not in sem_segredos("erro ao autenticar com senha-super-secreta")
    executar("Neo4j", lambda: (_ for _ in ()).throw(OSError("falha com senha-super-secreta")))
    assert "senha-super-secreta" not in caplog.text


# ----------------------------------------------------------------------------
# Permissões do serviço de catálogo (o servidor, não a tela, decide)
# ----------------------------------------------------------------------------
def test_visitante_e_usuario_comum_nao_escrevem(semeado, ator):
    for quem in (VISITANTE, ator("ana")):
        r = catalogo.criar_produto(quem, str(semeado["vendedor"]["_id"]), "Mouse", "x", "10,00", "1", "mlb1")
        assert not r.ok and r.erro
        assert not catalogo.excluir_produto(quem, str(semeado["produto"]["_id"])).ok
        assert not catalogo.criar_usuario(quem, "A", "B", "52998224725", "a@b.com").ok
        assert not catalogo.criar_vendedor(quem, "X", "11222333000181").ok
    assert catalogo_dados.colecao("produtos").count_documents({}) == 1


def test_admin_cria_edita_e_exclui_produto(semeado, ator):
    admin = ator("admin")
    criado = catalogo.criar_produto(admin, str(semeado["vendedor"]["_id"]), "Mouse", "sem fio", "80,00", "3", "mlb1649")
    assert criado.ok
    assert catalogo.atualizar_produto(admin, criado.dados, "Mouse Pro", "sem fio", "90,00", "0").dados is True
    prod = catalogo_dados.colecao("produtos").find_one({"titulo": "Mouse Pro"})
    assert prod["status"] == "pausado"  # estoque 0 pausa o anúncio (regra do núcleo)
    assert catalogo.excluir_produto(admin, criado.dados).ok


def test_entradas_invalidas_sao_rejeitadas_pelo_nucleo(semeado, ator):
    admin = ator("admin")
    assert "CPF" in catalogo.criar_usuario(admin, "A", "B", "11111111111", "a@b.com").erro
    assert "mail" in catalogo.criar_usuario(admin, "A", "B", "52998224725", "sem-arroba").erro.lower()
    assert not catalogo.criar_produto(admin, str(semeado["vendedor"]["_id"]), "X", "", "-5", "1", "mlb1").ok
    assert not catalogo.criar_produto(admin, "id-malformado", "X", "", "5", "1", "mlb1").ok
    assert not catalogo.criar_vendedor(admin, "Y", "123").ok


def test_exclusoes_protegidas_por_vinculos(semeado, ator):
    admin = ator("admin")
    pedido = catalogo.criar_pedido(admin, str(semeado["ana"]["_id"]), str(semeado["produto"]["_id"]), 1)
    assert pedido.ok
    assert "pedidos" in catalogo.excluir_usuario(admin, str(semeado["ana"]["_id"])).erro
    assert "histórico" in catalogo.excluir_produto(admin, str(semeado["produto"]["_id"])).erro
    assert "produtos vinculados" in catalogo.excluir_vendedor(admin, str(semeado["vendedor"]["_id"])).erro


# ----------------------------------------------------------------------------
# Pedidos: estoque atômico e isolamento entre usuários
# ----------------------------------------------------------------------------
def test_pedido_baixa_estoque_e_calcula_total(semeado, ator):
    r = catalogo.criar_pedido(ator("ana"), str(semeado["ana"]["_id"]), str(semeado["produto"]["_id"]), 2)
    assert r.ok and str(r.dados["total"]) == "300.00"
    prod = catalogo_dados.colecao("produtos").find_one({"_id": semeado["produto"]["_id"]})
    assert prod["quantidade_disponivel"] == 3 and prod["quantidade_vendida"] == 2


def test_pedido_nao_ultrapassa_o_estoque(semeado, ator):
    r = catalogo.criar_pedido(ator("ana"), str(semeado["ana"]["_id"]), str(semeado["produto"]["_id"]), 6)
    assert not r.ok
    assert catalogo_dados.colecao("produtos").find_one({"_id": semeado["produto"]["_id"]})["quantidade_disponivel"] == 5
    assert catalogo_dados.colecao("pedidos").count_documents({}) == 0


def test_usuario_comum_nao_compra_em_nome_de_outro(semeado, ator):
    r = catalogo.criar_pedido(ator("ana"), str(semeado["beto"]["_id"]), str(semeado["produto"]["_id"]), 1)
    assert not r.ok and "próprio nome" in r.erro
    assert catalogo_dados.colecao("pedidos").count_documents({}) == 0
    assert not catalogo.criar_pedido(VISITANTE, str(semeado["ana"]["_id"]), str(semeado["produto"]["_id"]), 1).ok


def test_cada_usuario_ve_so_os_proprios_pedidos_e_dados(semeado, ator):
    catalogo.criar_pedido(ator("ana"), str(semeado["ana"]["_id"]), str(semeado["produto"]["_id"]), 1)
    catalogo.criar_pedido(ator("beto"), str(semeado["beto"]["_id"]), str(semeado["produto"]["_id"]), 2)
    assert [p["total"] for p in catalogo.listar_pedidos(ator("ana")).dados] == [150]
    assert [p["total"] for p in catalogo.listar_pedidos(ator("beto")).dados] == [300]
    assert len(catalogo.listar_pedidos(ator("admin")).dados) == 2
    assert [u["email"] for u in catalogo.listar_usuarios(ator("ana")).dados] == ["ana@exemplo.com"]
    assert len(catalogo.listar_usuarios(ator("admin")).dados) == 2
    assert not catalogo.listar_usuarios(VISITANTE).ok and not catalogo.listar_pedidos(VISITANTE).ok


def test_ator_sem_cadastro_de_comprador_ve_listas_vazias(mongo, ator):
    assert catalogo.listar_usuarios(ator("ana")).dados == []
    assert catalogo.listar_pedidos(ator("ana")).dados == []


# ----------------------------------------------------------------------------
# Indicadores
# ----------------------------------------------------------------------------
def test_indicadores_vem_dos_dados_reais(semeado, ator):
    catalogo.criar_pedido(ator("ana"), str(semeado["ana"]["_id"]), str(semeado["produto"]["_id"]), 2)
    d = catalogo.indicadores().dados
    assert d["contagens"]["usuarios"] == 2 and d["contagens"]["pedidos"] == 1 and d["contagens"]["produtos"] == 1
    assert str(d["receita"]) == "300.00"
    assert d["mais_vendidos"] == [{"titulo": "Teclado", "vendidos": 2}]
    assert len(d["vendas_por_dia"]) == 1 and d["vendas_por_dia"][0]["pedidos"] == 1


def test_indicadores_sem_dados_nao_inventam_valores(mongo):
    d = catalogo.indicadores().dados
    assert d["mais_vendidos"] == [] and d["vendas_por_dia"] == [] and str(d["receita"]) == "0"


def test_mongo_fora_do_ar_retorna_indisponivel(monkeypatch):
    monkeypatch.setattr(catalogo_dados, "mongo_db", lambda: (_ for _ in ()).throw(pymongo.errors.ServerSelectionTimeoutError("timeout")))
    r = catalogo.indicadores()
    assert isinstance(r, Resultado) and not r.ok and r.indisponivel
    assert catalogo.listar_produtos().indisponivel


# ----------------------------------------------------------------------------
# Redis
# ----------------------------------------------------------------------------
def test_sessoes_ativas_mascaram_email_e_nunca_expoem_conteudo(redis_falso, ator):
    redis_falso.set("session:maria@exemplo.com", '{"usuario": "maria@exemplo.com", "segredo": "x"}', ex=60)
    visitante = sessoes.sessoes_ativas(VISITANTE).dados
    assert visitante[0]["chave"] == "session:m***@exemplo.com"
    admin = sessoes.sessoes_ativas(ator("admin")).dados
    assert any(s["chave"] == "session:maria@exemplo.com" for s in admin)
    assert all("segredo" not in str(s) for s in visitante + admin)


def test_sessao_de_login_web_so_aparece_para_admin(redis_falso, ator):
    ator("ana")
    assert all(s["tipo"] != "login (web)" for s in sessoes.sessoes_ativas(ator("ana")).dados)
    assert any(s["tipo"] == "login (web)" for s in sessoes.sessoes_ativas(ator("admin")).dados)


def test_sessao_de_demonstracao_exige_login_e_tem_ttl(redis_falso, ator):
    assert not sessoes.criar_sessao_demo(VISITANTE).ok
    r = sessoes.criar_sessao_demo(ator("ana"))
    assert r.ok and r.dados.startswith("demo_sessao:")
    assert 0 < sessoes.ttl_da_sessao(r.dados).dados <= 60
    assert sessoes.renovar_sessao_demo(ator("ana"), r.dados).dados is True
    assert sessoes.encerrar_sessao_demo(ator("ana"), r.dados).ok
    assert sessoes.ttl_da_sessao(r.dados).dados == 0


def test_demo_nao_mexe_em_chaves_que_nao_sao_de_demonstracao(redis_falso, ator):
    redis_falso.set("session:x@y.com", "{}", ex=60)
    sessoes.encerrar_sessao_demo(ator("ana"), "session:x@y.com")
    assert redis_falso.exists("session:x@y.com")
    assert sessoes.renovar_sessao_demo(ator("ana"), "session:x@y.com").dados is False


def test_limite_de_sessoes_de_demonstracao(redis_falso, ator):
    for _ in range(sessoes.MAX_DEMOS):
        assert sessoes.criar_sessao_demo(ator("ana")).ok
    assert not sessoes.criar_sessao_demo(ator("ana")).ok


def test_fluxo_mongo_redis_mongo_so_para_admin_e_nao_perde_itens(semeado, redis_falso, ator):
    assert not sessoes.executar_fluxo(ator("ana")).ok and not sessoes.executar_fluxo(VISITANTE).ok
    r = sessoes.executar_fluxo(ator("admin"))
    assert r.ok and any(e[0] == "titulo" for e in r.dados)
    assert catalogo_dados.colecao("produtos").count_documents({}) == 1  # tudo voltou
    assert redis_falso.keys("item_ml:*") == []


def test_tentativas_de_login_mascaradas_para_nao_admin(redis_falso, ator):
    redis_falso.set("web_login_falhas:fulano@exemplo.com", 3, ex=120)
    visitante = sessoes.tentativas_de_login(VISITANTE).dados
    assert visitante[0]["usuario"] == "f***@exemplo.com" and visitante[0]["tentativas"] == 3
    assert sessoes.tentativas_de_login(ator("admin")).dados[0]["usuario"] == "fulano@exemplo.com"


def test_redis_fora_do_ar_retorna_indisponivel(monkeypatch):
    from mercadolivre import sessoes_dados
    monkeypatch.setattr(sessoes_dados, "redis_cliente", lambda: (_ for _ in ()).throw(ConnectionError("fora")))
    assert sessoes.estado().indisponivel


# ----------------------------------------------------------------------------
# Cassandra e Neo4j: indisponibilidade e privacidade
# ----------------------------------------------------------------------------
def test_cassandra_e_neo4j_nao_configurados_nao_derrubam():
    for r in (historico.categorias(), grafo.resumo(), grafo.buscar_vendedores(None)):
        assert not r.ok and r.indisponivel


def test_historico_exige_login_para_compras(ator):
    assert not historico.compras_do_usuario(VISITANTE, "52998224725").ok
    assert not historico.usuarios(ator("ana")).ok  # listar todos os CPFs é só do admin


def test_grafo_visitante_recebe_apenas_a_parte_publica(monkeypatch, ator):
    chamadas = []
    monkeypatch.setattr(grafo.neo, "subgrafo", lambda cpf=None, com_pessoas=True, limite=150: chamadas.append((cpf, com_pessoas)) or ([], []))
    grafo.subgrafo(VISITANTE)
    grafo.subgrafo(ator("ana"))
    grafo.subgrafo(ator("admin"))
    assert chamadas == [(None, False), (None, False), (None, True)]


def test_grafo_arvore_de_outro_usuario_e_negada(monkeypatch, ator):
    monkeypatch.setattr(grafo.neo, "buscar_usuario", lambda cpf: {"email": "beto@exemplo.com"})
    assert "próprias compras" in grafo.subgrafo(ator("ana"), "11144477735").erro
    assert not grafo.subgrafo(VISITANTE, "11144477735").ok
    monkeypatch.setattr(grafo.neo, "subgrafo", lambda **k: ([], []))
    assert grafo.subgrafo(ator("admin"), "11144477735").ok


def test_grafo_nos_publicos_escondem_cpf_e_email():
    from mercadolivre.grafo import _descrever_no
    no = _descrever_no("1", "Usuario", {"cpf": "52998224725", "email": "a@b.com", "nome": "Ana", "sobrenome": "Lima"}, com_pessoas=False)
    assert "cpf" not in no["propriedades"] and "email" not in no["propriedades"]
    completo = _descrever_no("1", "Usuario", {"cpf": "52998224725", "nome": "Ana", "sobrenome": "Lima"}, com_pessoas=True)
    assert completo["propriedades"]["cpf"] == "52998224725" and completo["nome"] == "Ana Lima"


# ----------------------------------------------------------------------------
# Diagnóstico
# ----------------------------------------------------------------------------
def test_diagnostico_marca_nao_configurado_e_esconde_detalhe_de_nao_admin(mongo, redis_falso, monkeypatch, ator):
    monkeypatch.setattr(config, "bancos_configurados", lambda: {"MongoDB": True, "Redis": True, "Cassandra": False, "Neo4j": False})
    monkeypatch.setattr(diagnostico.diagnostico, "_mongo", lambda: "banco 'mercadolivre'")
    monkeypatch.setattr(diagnostico.diagnostico, "VERIFICACOES", [("MongoDB", lambda: "banco 'mercadolivre'"), ("Redis", lambda: (_ for _ in ()).throw(ConnectionError("tcp://segredo:6379"))), ("Cassandra (Astra DB)", lambda: ""), ("Neo4j (AuraDB)", lambda: "")])
    visitante = {l["servico"]: l for l in diagnostico.verificar(VISITANTE)}
    assert visitante["MongoDB"]["ok"] and visitante["MongoDB"]["detalhe"] == "Operando normalmente."
    assert not visitante["Redis"]["ok"] and "segredo" not in visitante["Redis"]["detalhe"]
    assert not visitante["Cassandra (Astra DB)"]["configurado"]
    admin = {l["servico"]: l for l in diagnostico.verificar(ator("admin"))}
    assert "mercadolivre" in admin["MongoDB"]["detalhe"]  # o admin vê o detalhe técnico
    assert "segredo" in admin["Redis"]["detalhe"] and "segredo" not in visitante["Redis"]["detalhe"]


def test_so_admin_reinicia_conexoes(monkeypatch, ator):
    chamadas = []
    monkeypatch.setattr(diagnostico.conexoes, "fechar_conexoes", lambda: chamadas.append(1))
    diagnostico.reiniciar_conexoes(ator("ana"))
    diagnostico.reiniciar_conexoes(VISITANTE)
    assert chamadas == []
    diagnostico.reiniciar_conexoes(ator("admin"))
    assert chamadas == [1]
