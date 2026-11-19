from bson import Decimal128, ObjectId

from mercadolivre import sessoes, sessoes_dados


def test_login_cria_sessao_com_ttl(redis_falso, respostas):
    respostas(["aluno@fatec.sp.gov.br", "senha123"])
    chave = sessoes.login()
    assert chave == "session:aluno@fatec.sp.gov.br"
    assert 0 < redis_falso.ttl(chave) <= sessoes.TTL
    assert sessoes.sessao_ativa(chave)


def test_login_bloqueia_apos_varias_falhas(redis_falso, respostas):
    respostas(["aluno@fatec.sp.gov.br", "errada"] * sessoes.MAX_FALHAS + ["aluno@fatec.sp.gov.br"])
    for _ in range(sessoes.MAX_FALHAS):
        assert sessoes.login() is None
    # a próxima tentativa nem chega a pedir a senha
    assert sessoes.login() is None
    assert int(redis_falso.get("login_falhas:aluno@fatec.sp.gov.br")) == sessoes.MAX_FALHAS


def test_checar_sessao_renova_ttl(redis_falso):
    redis_falso.set("session:x", "{}", ex=5)
    assert sessoes.checar_sessao("session:x")
    assert redis_falso.ttl("session:x") > 5
    assert not sessoes.checar_sessao("session:nao-existe")


def test_fluxo_move_e_devolve_itens_com_tipos_preservados(banco, redis_falso):
    col = banco["produtos"]
    ids = [ObjectId(), ObjectId(), ObjectId()]
    for i, _id in enumerate(ids):
        col.insert_one({"_id": _id, "titulo": f"Produto {i}", "preco": Decimal128("10.50")})

    sessoes.fluxo_itens()

    assert col.count_documents({}) == 3  # nada se perdeu
    assert redis_falso.keys("item_ml:*") == []  # Redis limpo
    atualizado = col.find_one({"_id": ids[0]})
    assert atualizado["status_modificacao"] == "Atualizado no Redis"
    assert isinstance(atualizado["preco"], Decimal128)
    assert isinstance(atualizado["_id"], ObjectId)


def test_fluxo_devolve_itens_mesmo_com_falha(banco, redis_falso, monkeypatch):
    col = banco["produtos"]
    col.insert_one({"_id": ObjectId(), "titulo": "A", "preco": Decimal128("1.00")})
    monkeypatch.setattr(sessoes_dados, "para_redis", lambda doc: (_ for _ in ()).throw(RuntimeError("falha")) if "preco_promocional" in doc else __import__("bson").json_util.dumps(doc))
    try:
        sessoes.fluxo_itens()
    except RuntimeError:
        pass
    assert col.count_documents({}) == 1
    assert redis_falso.keys("item_ml:*") == []
