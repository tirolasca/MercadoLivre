import base64
import os
import subprocess
import sys

import pytest

from mercadolivre import config, conexoes


def test_producao_e_o_padrao_e_ambiente_invalido_vira_producao(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    assert config.ambiente() == "production" and config.em_producao()
    monkeypatch.setenv("APP_ENV", "qualquer-coisa")
    assert config.em_producao()
    monkeypatch.setenv("APP_ENV", "development")
    assert not config.em_producao()


def test_aplicar_secrets_nao_sobrescreve_e_so_copia_escalares_maiusculos(monkeypatch):
    monkeypatch.setenv("MONGODB_DATABASE", "do-ambiente")
    copiadas = config.aplicar_secrets({
        "MONGODB_DATABASE": "do-secrets",  # já existe: ambiente vence
        "REDIS_HOST": "host.exemplo",
        "auth": {"usuarios": []},  # tabela: ignorada
        "minuscula": "x",  # só chaves em MAIÚSCULAS
    })
    assert copiadas == ["REDIS_HOST"]
    assert os.environ["MONGODB_DATABASE"] == "do-ambiente"
    assert os.environ["REDIS_HOST"] == "host.exemplo"
    monkeypatch.delenv("REDIS_HOST")


def test_bancos_configurados_nao_conecta(monkeypatch):
    assert config.bancos_configurados() == {"MongoDB": False, "Redis": False, "Cassandra": False, "Neo4j": False}
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://x")
    monkeypatch.setenv("NEO4J_PASSWORD", "segredo-longo")
    monkeypatch.setenv("ASTRA_DB_TOKEN", "AstraCS:x")
    assert config.bancos_configurados()["Neo4j"] and not config.bancos_configurados()["Cassandra"]
    monkeypatch.setenv("ASTRA_SCB_B64", "eA==")
    assert config.bancos_configurados()["Cassandra"]


def test_modo_demo_liga_por_padrao_e_desliga(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert config.modo_demo()
    monkeypatch.setenv("DEMO_MODE", "false")
    assert not config.modo_demo()


def test_bundle_astra_em_base64_vira_arquivo_temporario_privado(monkeypatch):
    monkeypatch.delenv("ASTRA_SCB_PATH", raising=False)
    monkeypatch.setenv("ASTRA_SCB_B64", base64.b64encode(b"PK\x03\x04conteudo").decode())
    caminho = conexoes._caminho_bundle()
    assert open(caminho, "rb").read() == b"PK\x03\x04conteudo"
    assert oct(os.stat(caminho).st_mode)[-3:] == "600"
    os.remove(caminho)


def test_bundle_invalido_ou_ausente_levanta_erro_claro(monkeypatch):
    monkeypatch.delenv("ASTRA_SCB_PATH", raising=False)
    monkeypatch.setenv("ASTRA_SCB_B64", "isto não é base64!!")
    with pytest.raises(RuntimeError, match="base64"):
        conexoes._caminho_bundle()
    monkeypatch.delenv("ASTRA_SCB_B64")
    with pytest.raises(RuntimeError, match="ASTRA_SCB"):
        conexoes._caminho_bundle()


def test_limite_de_pool_aceita_numero_e_ignora_lixo(monkeypatch):
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "7")
    assert conexoes._limite_pool("REDIS_MAX_CONNECTIONS", 10) == 7
    monkeypatch.setenv("REDIS_MAX_CONNECTIONS", "abc")
    assert conexoes._limite_pool("REDIS_MAX_CONNECTIONS", 10) == 10


def test_cli_nao_importa_streamlit():
    """A CLI precisa funcionar sem o Streamlit: nenhum módulo do núcleo o importa."""
    codigo = "import sys, mercadolivre.cli, mercadolivre.catalogo, mercadolivre.sessoes, mercadolivre.historico, mercadolivre.grafo, mercadolivre.diagnostico; print('streamlit' in sys.modules)"
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True)
    assert saida.stdout.strip() == "False"
