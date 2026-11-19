import json

import pytest

from mercadolivre import sessoes_dados
from web.auth import sessao
from web.auth.permissoes import VISITANTE, Ator, Papel, PermissaoNegada, exigir, tem
from web.auth.senhas import gerar_hash, verificar
from web.auth.usuarios import carregar_contas

from .conftest import SENHA


# ----------------------------------------------------------------------------
# Senhas
# ----------------------------------------------------------------------------
def test_hash_de_senha_verifica_e_rejeita_errada():
    h = gerar_hash(SENHA, iteracoes=1000)
    assert h.startswith("pbkdf2_sha256$1000$") and SENHA not in h
    assert verificar(SENHA, h)
    assert not verificar("outra-senha-qualquer", h)
    assert gerar_hash(SENHA, 1000) != h  # sal aleatório


def test_senha_curta_e_hash_malformado_sao_recusados():
    with pytest.raises(ValueError):
        gerar_hash("curta")
    assert not verificar(SENHA, None)
    assert not verificar(SENHA, "lixo")
    assert not verificar(SENHA, "md5$1$a$b")


# ----------------------------------------------------------------------------
# Contas por ambiente
# ----------------------------------------------------------------------------
def test_producao_nunca_carrega_contas_de_demonstracao(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert carregar_contas() == {}
    assert "aluno@fatec.sp.gov.br" not in carregar_contas()


def test_desenvolvimento_carrega_contas_descartaveis(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    contas = carregar_contas()
    assert contas["admin"].papel == Papel.ADMIN
    assert "aluno@fatec.sp.gov.br" in contas


def test_contas_vem_da_configuracao_e_invalidas_sao_ignoradas(monkeypatch):
    h = gerar_hash(SENHA, 1000)
    monkeypatch.setenv("AUTH_USUARIOS", json.dumps([
        {"usuario": "Maria", "papel": "admin", "senha_hash": h, "email": "M@x.com"},
        {"usuario": "semhash", "papel": "admin"},
        {"usuario": "papelruim", "papel": "root", "senha_hash": h},
        {"usuario": "visitante", "papel": "visitante", "senha_hash": h},
    ]))
    contas = carregar_contas()
    assert list(contas) == ["maria"] and contas["maria"].email == "m@x.com"


def test_auth_usuarios_com_json_quebrado_nao_derruba(monkeypatch):
    monkeypatch.setenv("AUTH_USUARIOS", "{nao e json")
    assert carregar_contas() == {}


# ----------------------------------------------------------------------------
# Papéis
# ----------------------------------------------------------------------------
def test_hierarquia_de_papeis():
    admin, usuario = Ator("a", Papel.ADMIN), Ator("u", Papel.USUARIO)
    assert tem(admin, Papel.USUARIO) and tem(admin, Papel.ADMIN)
    assert tem(usuario, Papel.USUARIO) and not tem(usuario, Papel.ADMIN)
    assert not tem(VISITANTE, Papel.USUARIO)
    with pytest.raises(PermissaoNegada, match="login"):
        exigir(VISITANTE, Papel.USUARIO)
    with pytest.raises(PermissaoNegada, match="permissão"):
        exigir(usuario, Papel.ADMIN)


# ----------------------------------------------------------------------------
# Sessão no servidor
# ----------------------------------------------------------------------------
def test_login_valido_cria_sessao_com_papel_do_servidor(redis_falso, contas):
    r = sessao.entrar("Admin", SENHA, contas)  # maiúsculas são normalizadas
    assert r.ok
    ator = sessao.ator_do_token(r.token)
    assert ator == Ator("admin", Papel.ADMIN, "admin@exemplo.com")
    assert 0 < redis_falso.ttl(sessao._id(r.token)) <= sessao.ttl_sessao()


def test_redis_guarda_apenas_o_hash_do_token(redis_falso, contas):
    r = sessao.entrar("ana", SENHA, contas)
    chaves = redis_falso.keys("*")
    assert all(r.token not in c for c in chaves)
    assert all(r.token not in (redis_falso.get(c) or "") for c in chaves)


def test_credenciais_erradas_nao_diferenciam_usuario_inexistente(redis_falso, contas):
    a = sessao.entrar("ana", "senha-errada-xxxx", contas)
    b = sessao.entrar("fantasma", "senha-errada-xxxx", contas)
    assert not a.ok and not b.ok and a.mensagem == b.mensagem == "Usuário ou senha incorretos."
    assert not sessao.entrar("", "", contas).ok


def test_bloqueio_apos_varias_tentativas_mesmo_com_senha_certa(redis_falso, contas):
    for _ in range(sessoes_dados.MAX_FALHAS):
        assert not sessao.entrar("ana", "errada-errada-1", contas).ok
    r = sessao.entrar("ana", SENHA, contas)
    assert not r.ok and "Tente novamente" in r.mensagem
    assert sessao.entrar("beto", SENHA, contas).ok  # outro usuário não é afetado


def test_logout_e_expiracao_derrubam_a_sessao(redis_falso, contas):
    t = sessao.entrar("ana", SENHA, contas).token
    assert sessao.ator_do_token(t).papel == Papel.USUARIO
    sessao.sair(t)
    assert sessao.ator_do_token(t) == VISITANTE
    t2 = sessao.entrar("ana", SENHA, contas).token
    redis_falso.delete(sessao._id(t2))  # equivale a expirar
    assert sessao.ator_do_token(t2) == VISITANTE


def test_token_forjado_ou_vazio_e_visitante(redis_falso):
    assert sessao.ator_do_token(None) == VISITANTE
    assert sessao.ator_do_token("") == VISITANTE
    assert sessao.ator_do_token("token-inventado") == VISITANTE


def test_sessoes_de_usuarios_diferentes_sao_isoladas(redis_falso, contas):
    ta, tb = (sessao.entrar(u, SENHA, contas).token for u in ("admin", "ana"))
    assert ta != tb
    assert sessao.ator_do_token(ta).papel == Papel.ADMIN
    assert sessao.ator_do_token(tb).papel == Papel.USUARIO
    sessao.sair(ta)
    assert sessao.ator_do_token(tb).papel == Papel.USUARIO  # sair de uma não afeta a outra


def test_sessao_desliza_renovando_o_prazo(redis_falso, contas):
    t = sessao.entrar("ana", SENHA, contas).token
    redis_falso.expire(sessao._id(t), 5)
    sessao.ator_do_token(t)
    assert redis_falso.ttl(sessao._id(t)) > 5
    redis_falso.expire(sessao._id(t), 5)
    sessao.ator_do_token(t, renovar=False)
    assert redis_falso.ttl(sessao._id(t)) <= 5


def test_com_redis_fora_do_ar_o_login_continua_em_memoria(monkeypatch, contas):
    def falha():
        raise ConnectionError("redis fora do ar")
    monkeypatch.setattr(sessoes_dados, "redis_cliente", falha)
    r = sessao.entrar("admin", SENHA, contas)
    assert r.ok
    assert sessao.ator_do_token(r.token).papel == Papel.ADMIN
    sessao.sair(r.token)
    assert sessao.ator_do_token(r.token) == VISITANTE


def test_bloqueio_tambem_funciona_em_memoria(monkeypatch, contas):
    monkeypatch.setattr(sessoes_dados, "redis_cliente", lambda: (_ for _ in ()).throw(ConnectionError()))
    for _ in range(sessoes_dados.MAX_FALHAS):
        assert not sessao.entrar("ana", "errada-errada-1", contas).ok
    assert "Tente novamente" in sessao.entrar("ana", SENHA, contas).mensagem
