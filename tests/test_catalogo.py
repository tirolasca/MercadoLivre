from decimal import Decimal

from bson import Decimal128, ObjectId

from mercadolivre import catalogo


def _semear(banco):
    vendedor = {"_id": ObjectId(), "nome_loja": "Loja", "cnpj": "12345678000195", "avaliacao": Decimal128("0.00"), "status": "ativo"}
    usuario = {"_id": ObjectId(), "nome": "Ana", "sobrenome": "Lima", "cpf": "52998224725", "email": "ana@x.com", "enderecos": []}
    produto = {
        "_id": ObjectId(), "titulo": "Teclado", "preco": Decimal128("150.00"), "quantidade_disponivel": 3,
        "quantidade_vendida": 0, "id_categoria": "MLB1", "id_vendedor": vendedor["_id"], "status": "ativo",
    }
    banco["vendedores"].insert_one(vendedor)
    banco["usuarios"].insert_one(usuario)
    banco["produtos"].insert_one(produto)
    return vendedor, usuario, produto


def test_criar_pedido_baixa_estoque_e_registra_total(banco, respostas):
    _, usuario, produto = _semear(banco)
    respostas(["2"], selecoes=[usuario, produto], confirmacoes=[True])

    catalogo.criar_pedido()

    atual = banco["produtos"].find_one({"_id": produto["_id"]})
    assert atual["quantidade_disponivel"] == 1 and atual["quantidade_vendida"] == 2
    pedido = banco["pedidos"].find_one()
    assert pedido["valor_total"].to_decimal() == Decimal("300.00")


def test_criar_pedido_cancelado_nao_altera_estoque(banco, respostas):
    _, usuario, produto = _semear(banco)
    respostas(["1"], selecoes=[usuario, produto], confirmacoes=[False])
    catalogo.criar_pedido()
    assert banco["produtos"].find_one()["quantidade_disponivel"] == 3
    assert banco["pedidos"].count_documents({}) == 0


def test_estoque_zero_e_aceito_na_atualizacao(banco, respostas):
    """Regressão: 0 é falsy e antes era ignorado, deixando o anúncio ativo."""
    _, _, produto = _semear(banco)
    respostas(["Teclado", "", "150,00", "0"], selecoes=[produto])
    catalogo.atualizar_produto()
    atual = banco["produtos"].find_one()
    assert atual["quantidade_disponivel"] == 0 and atual["status"] == "pausado"


def test_excluir_usuario_com_pedidos_e_bloqueado(banco, respostas):
    _, usuario, produto = _semear(banco)
    banco["pedidos"].insert_one({"id_comprador": usuario["_id"], "itens": [{"id_produto": produto["_id"]}]})
    respostas([], selecoes=[usuario], confirmacoes=[True])
    catalogo.excluir_usuario()
    assert banco["usuarios"].count_documents({}) == 1


def test_exportar_csv(banco, tmp_path, monkeypatch):
    _semear(banco)
    monkeypatch.setattr(catalogo, "PASTA_EXPORTACOES", tmp_path)
    catalogo.exportar_produtos_csv()
    arquivos = list(tmp_path.glob("produtos_*.csv"))
    assert len(arquivos) == 1
    assert "Teclado" in arquivos[0].read_text(encoding="utf-8-sig")


def test_painel_executa_com_e_sem_dados(banco, monkeypatch):
    catalogo.painel()  # banco vazio
    _semear(banco)
    # o mongomock não suporta $multiply com Decimal128 (o MongoDB real suporta)
    monkeypatch.setattr(catalogo, "valor_em_estoque", lambda: Decimal("450.00"))
    catalogo.painel()


def test_consultar_cep_trata_falha_de_rede(monkeypatch):
    import requests

    def falha(*a, **k):
        raise requests.ConnectionError

    monkeypatch.setattr(catalogo.requests, "get", falha)
    assert catalogo.consultar_cep("12235000") is None
