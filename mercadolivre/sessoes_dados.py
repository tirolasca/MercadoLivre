"""Sessões, proteção contra tentativas inválidas e fluxo de cache no Redis, sem interface.

* Sessão: chave ``session:<email>`` com TTL (``SET ... EX``); cada ação renova o
  prazo (sessão deslizante) e o Redis apaga a chave sozinho ao expirar.
* Proteção contra força bruta: contador ``login_falhas:<email>`` com TTL.
* Cache: produtos do MongoDB são movidos para ``item_ml:<_id>``, manipulados no
  Redis e devolvidos ao MongoDB, serializados com ``bson.json_util``.

A CLI (``sessoes.py``) e a web chamam estas funções; aqui não há ``print``,
``rich`` ou ``streamlit``.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from bson import Decimal128, json_util

from .conexoes import mongo_db, redis_cliente

# Usuários de demonstração: SOMENTE para desenvolvimento/CLI. A web em produção não os usa.
USUARIOS_DEMO = {"aluno@fatec.sp.gov.br": "senha123", "vinicius@gmail.com": "123456"}

TTL = int(os.getenv("SESSION_EXPIRATION", 60))
MAX_FALHAS = 5
JANELA_FALHAS = 300  # segundos
LIMITE_SESSOES_LISTADAS = 100

para_redis = json_util.dumps
do_redis = json_util.loads


def r():
    return redis_cliente()


def colecao_produtos():
    return mongo_db()[os.getenv("MONGODB_COLLECTION", "produtos")]


# ----------------------------------------------------------------------------
# Sessão
# ----------------------------------------------------------------------------
def sessao_ativa(chave: str | None) -> bool:
    return bool(chave) and bool(r().exists(chave))


def ttl_restante(chave: str | None) -> int:
    """Segundos restantes da sessão (0 se não existir ou já expirou)."""
    if not chave:
        return 0
    return max(int(r().ttl(chave)), 0)


def renovar_sessao(chave: str | None) -> bool:
    """Sessão deslizante: cada ação válida reinicia o prazo."""
    if not sessao_ativa(chave):
        return False
    r().expire(chave, TTL)
    return True


def criar_sessao(chave: str, dados: Mapping[str, Any] | None = None, ttl: int | None = None) -> str:
    r().set(chave, para_redis(dict(dados or {})), ex=ttl or TTL)
    return chave


def logout(chave: str | None) -> None:
    if chave:
        r().delete(chave)


def listar_sessoes(prefixo: str = "session:") -> list[dict[str, Any]]:
    """Sessões ativas e o tempo restante. Nunca devolve o conteúdo guardado na sessão."""
    achadas = []
    for chave in r().scan_iter(match=f"{prefixo}*", count=100):
        achadas.append({"chave": chave, "ttl": ttl_restante(chave)})
        if len(achadas) >= LIMITE_SESSOES_LISTADAS:
            break
    return sorted(achadas, key=lambda s: s["chave"])


# ----------------------------------------------------------------------------
# Login e proteção contra tentativas inválidas
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class ResultadoLogin:
    ok: bool
    chave: str | None = None
    motivo: str = ""  # "ok", "bloqueado" ou "credenciais"
    espera: int = 0  # segundos até poder tentar de novo (quando bloqueado)


def falhas_de(email: str, prefixo: str = "login_falhas:") -> tuple[int, int]:
    """(tentativas inválidas na janela atual, segundos até o contador zerar)."""
    chave = f"{prefixo}{email.strip().lower()}"
    return int(r().get(chave) or 0), max(int(r().ttl(chave)), 0)


def bloqueado(email: str, prefixo: str = "login_falhas:") -> int:
    """Segundos de bloqueio restantes (0 se pode tentar)."""
    tentativas, restante = falhas_de(email, prefixo)
    return restante if tentativas >= MAX_FALHAS else 0


def registrar_falha(email: str, prefixo: str = "login_falhas:") -> None:
    chave = f"{prefixo}{email.strip().lower()}"
    if r().incr(chave) == 1:
        r().expire(chave, JANELA_FALHAS)


def limpar_falhas(email: str, prefixo: str = "login_falhas:") -> None:
    r().delete(f"{prefixo}{email.strip().lower()}")


def tentar_login(email: str, senha: str, usuarios: Mapping[str, str] | None = None) -> ResultadoLogin:
    """Valida credenciais com comparação em tempo constante, limitando tentativas por e-mail."""
    email = email.strip().lower()
    if espera := bloqueado(email):
        return ResultadoLogin(False, motivo="bloqueado", espera=espera)
    esperada = (USUARIOS_DEMO if usuarios is None else usuarios).get(email)
    if esperada is not None and hmac.compare_digest(esperada.encode(), senha.encode()):
        limpar_falhas(email)
        return ResultadoLogin(True, criar_sessao(f"session:{email}", {"usuario": email}), "ok")
    registrar_falha(email)
    return ResultadoLogin(False, motivo="credenciais")


# ----------------------------------------------------------------------------
# Fluxo MongoDB -> Redis -> MongoDB
# ----------------------------------------------------------------------------
Emitir = Callable[[str, str, Any], None]


def _mudo(etapa: str, mensagem: str, dados: Any = None) -> None:  # pragma: no cover - padrão sem saída
    return None


def devolver_ao_mongo(chaves: list[str], emitir: Emitir = _mudo) -> None:
    col = colecao_produtos()
    for chave in chaves:
        bruto = r().get(chave)
        if bruto is None:
            emitir("aviso", f"{chave} não existe mais no Redis (expirou ou foi removida).", None)
            continue
        dados = do_redis(bruto)
        col.replace_one({"_id": dados["_id"]}, dados, upsert=True)
        r().delete(chave)
        emitir("sucesso", f"Item {dados['_id']} devolvido ao MongoDB e removido do Redis.", None)


def executar_fluxo(emitir: Emitir = _mudo, limite: int = 2) -> list[str]:
    """Move itens do MongoDB para o Redis, faz um CRUD e devolve tudo ao MongoDB.

    ``emitir(etapa, mensagem, dados)`` recebe o andamento: ``etapa`` é ``titulo``,
    ``sucesso``, ``aviso`` ou ``json``. Devolve as chaves usadas. O bloco ``finally``
    devolve os itens ao MongoDB mesmo se algo falhar no meio: nenhum item se perde.
    """
    col = colecao_produtos()
    docs = list(col.find().limit(limite))
    if not docs:
        emitir("aviso", "Nenhum item na coleção do MongoDB. Cadastre produtos no catálogo primeiro.", None)
        return []

    chaves: list[str] = []
    try:
        emitir("titulo", "1. MongoDB -> Redis", None)
        for doc in docs:
            chave = f"item_ml:{doc['_id']}"
            r().set(chave, para_redis(doc))
            chaves.append(chave)  # registrado antes do delete: se algo falhar, o item volta
            col.delete_one({"_id": doc["_id"]})
            emitir("sucesso", f"{doc.get('titulo', chave)} movido para {chave}", None)

        emitir("titulo", "2. CRUD no Redis", None)
        primeira = chaves[0]
        item = do_redis(r().get(primeira))
        emitir("json", "READ", para_redis(item))

        item["preco_promocional"] = Decimal128("99.90")
        item["status_modificacao"] = "Atualizado no Redis"
        r().set(primeira, para_redis(item))
        emitir("json", "UPDATE", r().get(primeira))

        r().set("item_ml:temp", para_redis({"titulo": "Temp", "preco": Decimal128("1.00")}))
        emitir("sucesso", "CREATE item_ml:temp criado", None)
        r().delete("item_ml:temp")
        emitir("sucesso", "DELETE item_ml:temp excluído", None)
    finally:
        emitir("titulo", "3. Redis -> MongoDB", None)
        devolver_ao_mongo(chaves, emitir)
    return chaves
