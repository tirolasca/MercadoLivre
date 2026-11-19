from types import SimpleNamespace

from mercadolivre import historico


class ExecutorFalso:
    """Registra as consultas enviadas ao Cassandra e devolve um resultado fixo."""

    def __init__(self, resultado=None):
        self.chamadas = []
        self.resultado = SimpleNamespace(was_applied=True) if resultado is None else resultado

    def __call__(self, cql, parametros=()):
        self.chamadas.append((" ".join(cql.split()), tuple(parametros)))
        return self.resultado


def test_atualizar_usuario_so_altera_campos_informados(monkeypatch):
    executor = ExecutorFalso()
    monkeypatch.setattr(historico, "_executar", executor)
    assert historico.atualizar_usuario("52998224725", email="novo@x.com") is True
    cql, params = executor.chamadas[0]
    assert cql == "UPDATE usuario SET email = ?, atualizado_em = ? WHERE cpf = ? IF EXISTS"
    assert params[0] == "novo@x.com" and params[-1] == "52998224725"


def test_atualizar_usuario_sem_campos_nao_consulta_o_banco(monkeypatch):
    executor = ExecutorFalso()
    monkeypatch.setattr(historico, "_executar", executor)
    assert historico.atualizar_usuario("52998224725") is None
    assert executor.chamadas == []


def test_busca_por_prefixo_usa_faixa_na_clustering_key(monkeypatch):
    executor = ExecutorFalso(resultado=[])
    monkeypatch.setattr(historico, "_executar", executor)
    historico.listar_produtos_categoria("MLB1648", prefixo="Teclado G")
    cql, params = executor.chamadas[0]
    assert "titulo >= ? AND titulo < ?" in cql
    assert params == ("MLB1648", "Teclado G", "Teclado H")


def test_busca_sem_prefixo_lista_a_categoria_inteira(monkeypatch):
    executor = ExecutorFalso(resultado=[])
    monkeypatch.setattr(historico, "_executar", executor)
    historico.listar_produtos_categoria("MLB1648")
    assert "titulo >=" not in executor.chamadas[0][0]


def test_inserir_compra_recusa_usuario_inexistente(monkeypatch):
    monkeypatch.setattr(historico, "_executar", ExecutorFalso(resultado=SimpleNamespace(one=lambda: None)))
    assert historico.inserir_compra("52998224725", object(), 1) is None


def test_dados_de_demonstracao_sao_validos():
    from mercadolivre.validadores import cnpj_valido, cpf_valido

    assert cpf_valido("52998224725") and cnpj_valido("12345678000195")
