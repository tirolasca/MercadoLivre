"""Favoritos moram DENTRO do documento do usuário (array ``favoritos``), como os endereços."""

import pytest
from bson import Decimal128, ObjectId

from mercadolivre import catalogo, catalogo_dados as dados


def _semear(banco):
    vendedor = dados.inserir_vendedor("Loja", "12345678000195")
    ana = dados.inserir_usuario("Ana", "Lima", "52998224725", "ana@x.com")
    teclado = dados.inserir_produto(vendedor["_id"], "Teclado", "ABNT2", "150,00", 5, "mlb1")
    mouse = dados.inserir_produto(vendedor["_id"], "Mouse", "", "50,00", 5, "mlb1")
    return ana, teclado, mouse


def test_favorito_fica_dentro_do_documento_do_usuario(banco):
    ana, teclado, _ = _semear(banco)
    assert dados.adicionar_favorito(ana["_id"], teclado["_id"]) is True
    doc = banco["usuarios"].find_one({"_id": ana["_id"]})
    assert [f["id_produto"] for f in doc["favoritos"]] == [teclado["_id"]]
    assert "favoritos" not in banco.list_collection_names()  # nenhuma coleção separada


def test_favoritar_duas_vezes_nao_duplica(banco):
    ana, teclado, _ = _semear(banco)
    assert dados.adicionar_favorito(ana["_id"], teclado["_id"]) is True
    assert dados.adicionar_favorito(str(ana["_id"]), str(teclado["_id"])) is False  # aceita texto (vem da web)
    assert len(banco["usuarios"].find_one()["favoritos"]) == 1


def test_listar_traz_produto_e_loja_em_ordem_alfabetica(banco):
    ana, teclado, mouse = _semear(banco)
    dados.adicionar_favorito(ana["_id"], teclado["_id"])
    dados.adicionar_favorito(ana["_id"], mouse["_id"])
    lista = dados.listar_favoritos(ana["_id"])
    assert [f["produto"]["titulo"] for f in lista] == ["Mouse", "Teclado"]
    assert lista[0]["vendedor"]["nome_loja"] == "Loja"


def test_remover_favorito(banco):
    ana, teclado, mouse = _semear(banco)
    dados.adicionar_favorito(ana["_id"], teclado["_id"])
    assert dados.remover_favorito(ana["_id"], teclado["_id"]) is True
    assert dados.remover_favorito(ana["_id"], teclado["_id"]) is False
    assert dados.remover_favorito(ana["_id"], mouse["_id"]) is False
    assert dados.listar_favoritos(ana["_id"]) == []


def test_favoritar_com_ids_inexistentes_ou_invalidos(banco):
    ana, teclado, _ = _semear(banco)
    with pytest.raises(dados.ErroNegocio, match="Produto não encontrado"):
        dados.adicionar_favorito(ana["_id"], ObjectId())
    with pytest.raises(dados.ErroNegocio, match="Usuário não encontrado"):
        dados.adicionar_favorito(ObjectId(), teclado["_id"])
    with pytest.raises(dados.ErroNegocio, match="Usuário não encontrado"):
        dados.remover_favorito(ObjectId(), teclado["_id"])
    with pytest.raises(dados.ErroNegocio, match="Identificador inválido"):
        dados.adicionar_favorito("xyz", teclado["_id"])


def test_excluir_produto_tira_dos_favoritos_de_todos(banco):
    ana, teclado, mouse = _semear(banco)
    beto = dados.inserir_usuario("Beto", "Souza", "11144477735", "beto@x.com")
    for u in (ana, beto):
        dados.adicionar_favorito(u["_id"], teclado["_id"])
    dados.adicionar_favorito(ana["_id"], mouse["_id"])
    dados.excluir_produto(teclado["_id"])
    assert [f["id_produto"] for f in banco["usuarios"].find_one({"_id": ana["_id"]})["favoritos"]] == [mouse["_id"]]
    assert banco["usuarios"].find_one({"_id": beto["_id"]})["favoritos"] == []


def test_excluir_usuario_leva_os_favoritos_junto(banco):
    ana, teclado, _ = _semear(banco)
    dados.adicionar_favorito(ana["_id"], teclado["_id"])
    dados.excluir_usuario(ana["_id"])
    assert dados.contar_favoritos() == 0 and banco["usuarios"].count_documents({}) == 0


def test_contagem_soma_os_favoritos_de_todos_os_usuarios(banco):
    ana, teclado, mouse = _semear(banco)
    beto = dados.inserir_usuario("Beto", "Souza", "11144477735", "beto@x.com")
    antigo = banco["usuarios"].insert_one({"nome": "Sem", "sobrenome": "Campo", "cpf": "1", "email": "s@x.com"})  # documento sem o campo
    dados.adicionar_favorito(ana["_id"], teclado["_id"])
    dados.adicionar_favorito(ana["_id"], mouse["_id"])
    dados.adicionar_favorito(beto["_id"], mouse["_id"])
    assert dados.contar_favoritos() == 3 and dados.contagens()["favoritos"] == 3
    assert dados.adicionar_favorito(antigo.inserted_id, mouse["_id"]) is True  # $push cria o campo que faltava


def test_migracao_do_modelo_antigo_e_idempotente(banco):
    ana, teclado, mouse = _semear(banco)
    fantasma = ObjectId()
    banco["favoritos"].insert_many([
        {"id_usuario": ana["_id"], "id_produto": teclado["_id"]},
        {"id_usuario": ana["_id"], "id_produto": mouse["_id"]},
        {"id_usuario": ana["_id"], "id_produto": mouse["_id"]},   # duplicado
        {"id_usuario": ObjectId(), "id_produto": mouse["_id"]},   # usuário que não existe
        {"id_usuario": ana["_id"], "id_produto": fantasma},       # produto que não existe
    ])
    assert dados.migrar_favoritos() == 2
    assert "favoritos" not in banco.list_collection_names()
    assert sorted(f["produto"]["titulo"] for f in dados.listar_favoritos(ana["_id"])) == ["Mouse", "Teclado"]
    assert dados.migrar_favoritos() == 0  # nada a fazer na segunda vez


def test_configurar_banco_dados_migra_sozinho(banco):
    ana, teclado, _ = _semear(banco)
    banco["favoritos"].insert_one({"id_usuario": ana["_id"], "id_produto": teclado["_id"]})
    dados.configurar_banco_dados()
    assert dados.contar_favoritos() == 1 and "favoritos" not in banco.list_collection_names()


def test_cli_adiciona_lista_e_remove(banco, respostas, capsys):
    ana, teclado, _ = _semear(banco)
    doc_ana, doc_teclado = banco["usuarios"].find_one(), banco["produtos"].find_one({"titulo": "Teclado"})
    respostas([], selecoes=[doc_ana, doc_teclado])
    catalogo.adicionar_favorito()
    assert len(banco["usuarios"].find_one()["favoritos"]) == 1
    respostas([], selecoes=[doc_ana, doc_teclado])
    catalogo.adicionar_favorito()  # já estava: avisa e não duplica
    assert len(banco["usuarios"].find_one()["favoritos"]) == 1
    item = dados.listar_favoritos(ana["_id"])[0]
    respostas([], selecoes=[doc_ana, item])
    catalogo.remover_favorito()
    assert banco["usuarios"].find_one()["favoritos"] == []
