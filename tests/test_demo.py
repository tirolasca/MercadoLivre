from mercadolivre import catalogo, dados_demo, ui
from mercadolivre.validadores import cnpj_valido, cpf_valido


def test_dados_de_demonstracao_compartilhados_sao_validos():
    assert all(cpf_valido(cpf) for cpf, *_ in dados_demo.USUARIOS)
    assert all(cnpj_valido(cnpj) for cnpj, _ in dados_demo.LOJAS)
    cnpjs = {cnpj for cnpj, _ in dados_demo.LOJAS}
    assert all(p.cnpj in cnpjs for p in dados_demo.PRODUTOS)
    chaves = {p.chave for p in dados_demo.PRODUTOS}
    assert all(chave in chaves for _, chave, _ in dados_demo.COMPRAS)


def test_id_de_produto_demo_e_estavel():
    assert dados_demo.id_produto("mouse") == dados_demo.id_produto("mouse")
    assert dados_demo.id_produto("mouse") != dados_demo.id_produto("teclado")


def test_carregar_demonstracao_no_mongo_e_idempotente(banco):
    catalogo.carregar_demonstracao()
    catalogo.carregar_demonstracao()
    assert banco["usuarios"].count_documents({}) == 2
    assert banco["vendedores"].count_documents({}) == 2
    assert banco["produtos"].count_documents({}) == 4


def test_menu_compartilhado_executa_acao_e_sobrevive_a_erro(monkeypatch):
    escolhas = iter([lambda: (_ for _ in ()).throw(ValueError("falhou")), lambda: chamadas.append("ok"), None])
    chamadas = []
    monkeypatch.setattr(ui, "selecionar", lambda *a, **k: next(escolhas))
    ui.menu("TESTE", [("a", None)], raiz=True)
    assert chamadas == ["ok"]
