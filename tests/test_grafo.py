import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from mercadolivre import grafo


class RegistroFalso:
    def __init__(self, dados):
        self._dados = dados

    def data(self):
        return self._dados


class ExecutorFalso:
    """Registra as consultas Cypher enviadas ao Neo4j e devolve resultados em fila."""

    def __init__(self, *resultados):
        self.chamadas = []
        self.fila = list(resultados)

    def __call__(self, cypher, parametros=None):
        self.chamadas.append((" ".join(cypher.split()), dict(parametros or {})))
        registros, nos_criados = self.fila.pop(0) if self.fila else ([], 0)
        contadores = SimpleNamespace(nodes_created=nos_criados)
        return SimpleNamespace(records=[RegistroFalso(r) for r in registros], summary=SimpleNamespace(counters=contadores))


def usar(monkeypatch, *resultados):
    executor = ExecutorFalso(*resultados)
    monkeypatch.setattr(grafo, "_executar", executor)
    return executor


PRODUTO = {"id_produto": str(uuid.uuid4()), "titulo": "Teclado", "descricao": "", "preco": 150.0,
           "quantidade_disponivel": 10, "id_categoria": "MLB1", "cnpj_vendedor": "1", "nome_loja": "Loja"}


# ---------------------------------------------------------------- insert
def test_inserir_usuario_usa_merge_e_informa_se_criou(monkeypatch):
    executor = usar(monkeypatch, ([], 1), ([], 0))
    assert grafo.inserir_usuario("52998224725", "Ana", "Souza", "a@x.com") is True
    assert grafo.inserir_usuario("52998224725", "Ana", "Souza", "a@x.com") is False
    cypher, params = executor.chamadas[0]
    assert cypher.startswith("MERGE (u:Usuario {cpf: $cpf}) ON CREATE SET")
    assert params["cpf"] == "52998224725"


def test_inserir_vendedor_recusa_nome_de_loja_repetido(monkeypatch):
    def levanta(*_a, **_k):
        raise grafo.ConstraintError("nome_loja duplicado")

    monkeypatch.setattr(grafo, "_executar", levanta)
    assert grafo.inserir_vendedor("12345678000195", "Loja") is False


def test_inserir_produto_liga_vendedor_e_categoria(monkeypatch):
    id_produto = uuid.uuid4()
    executor = usar(monkeypatch, ([{"id_produto": str(id_produto)}], 2))
    assert grafo.inserir_produto("12345678000195", "Mouse", "desc", Decimal("80.00"), 5, "MLB1649", id_produto) == id_produto
    cypher, params = executor.chamadas[0]
    assert "MATCH (v:Vendedor {cnpj: $cnpj, status: 'ativo'})" in cypher
    assert "MERGE (v)-[:VENDE]->(p)" in cypher and "MERGE (p)-[:PERTENCE_A]->(c)" in cypher
    assert params["preco"] == 80.0 and params["id_produto"] == str(id_produto)


def test_inserir_produto_de_vendedor_inexistente_devolve_none(monkeypatch):
    usar(monkeypatch, ([], 0))
    assert grafo.inserir_produto("00000000000000", "X", "", Decimal("1.00"), 1, "MLB1") is None


def test_inserir_compra_recusa_usuario_ou_produto_inexistente(monkeypatch):
    usar(monkeypatch, ([], 0))  # usuário não encontrado
    assert grafo.inserir_compra("52998224725", uuid.uuid4(), 1) is None
    usar(monkeypatch, ([{"cpf": "52998224725"}], 0), ([], 0))  # usuário ok, produto não
    assert grafo.inserir_compra("52998224725", uuid.uuid4(), 1) is None


def test_inserir_compra_calcula_total_e_cria_relacionamentos(monkeypatch):
    id_produto = uuid.uuid4()
    executor = usar(monkeypatch, ([{"cpf": "1"}], 0), ([PRODUTO], 0), ([{"id_compra": "x"}], 1))
    assert isinstance(grafo.inserir_compra("52998224725", id_produto, 3), uuid.UUID)
    cypher, params = executor.chamadas[-1]
    assert params["total"] == 450.0 and params["quantidade"] == 3
    assert "(u)-[:REALIZOU]->(c)" in cypher and "(c)-[:DE_PRODUTO]->(p)" in cypher
    assert "p.quantidade_disponivel >= $quantidade" in cypher  # baixa só se houver saldo


def test_inserir_compra_com_estoque_insuficiente_levanta_erro(monkeypatch):
    usar(monkeypatch, ([{"cpf": "1"}], 0), ([PRODUTO], 0), ([], 0))
    with pytest.raises(ValueError, match="Estoque insuficiente"):
        grafo.inserir_compra("52998224725", uuid.uuid4(), 99)


# ---------------------------------------------------------------- search
def test_buscar_usuarios_sem_termo_lista_todos(monkeypatch):
    executor = usar(monkeypatch, ([], 0))
    grafo.buscar_usuarios()
    params = executor.chamadas[0][1]
    assert params["termo"] is None and params["digitos"] == ""


def test_buscar_usuarios_normaliza_termo_e_extrai_digitos(monkeypatch):
    executor = usar(monkeypatch, ([], 0))
    grafo.buscar_usuarios("  Ana   SOUZA ")
    assert executor.chamadas[0][1]["termo"] == "ana souza"
    grafo.buscar_usuarios("529.982.247-25")
    assert executor.chamadas[1][1]["digitos"] == "52998224725"


def test_buscar_produtos_filtra_por_parametros_e_nao_interpola_valores(monkeypatch):
    executor = usar(monkeypatch, ([], 0))
    grafo.buscar_produtos("teclado'; MATCH (n) DETACH DELETE n //", "MLB1648", "123")
    cypher, params = executor.chamadas[0]
    assert "DETACH" not in cypher
    assert params["categoria"] == "MLB1648" and params["cnpj"] == "123"


def test_ordenacao_desconhecida_cai_no_titulo(monkeypatch):
    executor = usar(monkeypatch, ([], 0), ([], 0))
    grafo.buscar_produtos(ordenar="1; DROP")
    grafo.buscar_produtos(ordenar="maior_preco")
    assert "ORDER BY p.titulo ASC" in executor.chamadas[0][0]
    assert "ORDER BY p.preco DESC" in executor.chamadas[1][0]


def test_buscar_produto_converte_preco_em_decimal(monkeypatch):
    usar(monkeypatch, ([PRODUTO], 0))
    produto = grafo.buscar_produto(uuid.uuid4())
    assert produto["preco"] == Decimal("150.00") and isinstance(produto["preco"], Decimal)


def test_buscar_compra_devolve_none_quando_nao_existe(monkeypatch):
    usar(monkeypatch, ([], 0))
    assert grafo.buscar_compra(uuid.uuid4()) is None


def test_buscar_compras_converte_datas_e_valores(monkeypatch):
    quando = SimpleNamespace(to_native=lambda: datetime(2026, 11, 12, tzinfo=timezone.utc))
    usar(monkeypatch, ([{"data_compra": quando, "valor_total": 79.9}], 0))
    compra = grafo.buscar_compras(cpf="52998224725")[0]
    assert compra["data_compra"].year == 2026 and compra["valor_total"] == Decimal("79.90")


def test_buscar_compras_filtra_por_usuario_e_produto(monkeypatch):
    executor = usar(monkeypatch, ([], 0))
    grafo.buscar_compras(cpf="52998224725", id_produto="abc")
    params = executor.chamadas[0][1]
    assert params["cpf"] == "52998224725" and params["id_produto"] == "abc"


# ---------------------------------------------------------------- schema e dados
def test_schema_cria_restricao_de_unicidade_para_cada_no():
    for rotulo in ("Usuario", "Vendedor", "Categoria", "Produto", "Compra"):
        assert any(f":{rotulo})" in c and "IS UNIQUE" in c for c in grafo.SCHEMA)
    assert all("IF NOT EXISTS" in c for c in grafo.SCHEMA)  # idempotente


def test_criar_schema_envia_todas_as_instrucoes(monkeypatch):
    executor = usar(monkeypatch)
    grafo.criar_schema()
    assert len(executor.chamadas) == len(grafo.SCHEMA)


def test_dados_de_demonstracao_sao_validos():
    from mercadolivre.validadores import cnpj_valido, cpf_valido

    assert all(cpf_valido(c) for c in ("52998224725", "11144477735"))
    assert all(cnpj_valido(c) for c in ("12345678000195", "11222333000181"))


def test_conexao_exige_uri_e_senha(monkeypatch):
    from mercadolivre import conexoes

    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    conexoes.neo4j_driver.cache_clear()
    with pytest.raises(RuntimeError, match="NEO4J_URI"):
        conexoes.neo4j_driver()
