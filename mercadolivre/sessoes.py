"""Sessões de login com expiração e cache temporário de produtos no Redis.

* Sessão: chave ``session:<email>`` com TTL (``SET ... EX``); cada ação renova o
  prazo (sessão deslizante) e o Redis apaga a chave sozinho ao expirar.
* Proteção contra força bruta: contador ``login_falhas:<email>`` com TTL.
* Cache: produtos do MongoDB são movidos para ``item_ml:<_id>``, manipulados no
  Redis e devolvidos ao MongoDB. Os documentos são serializados com
  ``bson.json_util``, que preserva ``ObjectId``, ``Decimal128`` e ``datetime``.
"""

from __future__ import annotations

import time

from redis.exceptions import RedisError
from pymongo.errors import PyMongoError
from rich.json import JSON
from rich.progress import BarColumn, Progress, TextColumn

from . import ui
from . import sessoes_dados as dados
from .conexoes import fechar_conexoes, mongo_db, redis_cliente
from .sessoes_dados import (  # noqa: F401 - reexportados: a CLI e os testes usam estes nomes
    JANELA_FALHAS,
    MAX_FALHAS,
    TTL,
    USUARIOS_DEMO as USUARIOS,
    colecao_produtos,
    do_redis,
    para_redis,
    r,
    sessao_ativa,
)

RESUMO = [
    "Guarda pares CHAVE -> VALOR na memória, por isso é muito rápido.",
    "Aqui: sessão de login (session:<email>) que EXPIRA sozinha com TTL, e contador de tentativas de senha.",
    "Cache: o item sai do MongoDB, vira uma chave no Redis (CRUD) e volta ao MongoDB.",
    "Comandos usados: SET ... EX, GET, EXPIRE, TTL, INCR, DEL.",
]

# ----------------------------------------------------------------------------
# Sessão
# ----------------------------------------------------------------------------
def checar_sessao(chave: str | None, renovar: bool = True) -> bool:
    if not sessao_ativa(chave):
        ui.aviso("Sessão inválida ou expirada. Faça login.")
        return False
    if renovar:
        dados.renovar_sessao(chave)  # sessão deslizante
    ui.info(f"Sessão ativa. Restam {dados.ttl_restante(chave)}s.")
    return True


def login() -> str | None:
    email = ui.perguntar("E-mail:").lower()
    if espera := dados.bloqueado(email):
        ui.erro(f"Muitas tentativas. Tente novamente em {espera}s.")
        return None
    senha = ui.perguntar("Senha:", senha=True)
    resultado = dados.tentar_login(email, senha)
    if resultado.ok:
        ui.sucesso(f"Login realizado. A sessão expira em {TTL}s sem atividade.")
        return resultado.chave
    ui.erro("Credenciais incorretas.")
    return None


def logout(chave: str | None) -> None:
    dados.logout(chave)
    ui.sucesso("Logout concluído.")


def monitorar_sessao(chave: str) -> None:
    """Contagem regressiva ao vivo do TTL. Ctrl+C volta ao menu."""
    if not sessao_ativa(chave):
        ui.aviso("Sessão inválida ou expirada.")
        return
    ui.info("Acompanhando a sessão (não renova o prazo). Ctrl+C para voltar.")
    progresso = Progress(
        TextColumn("[bold]Sessão[/]"),
        BarColumn(bar_width=30),
        TextColumn("[bold]{task.completed:.0f}s[/] restantes"),
        console=ui.console,
    )
    try:
        with progresso:
            tarefa = progresso.add_task("sessao", total=TTL)
            while (restante := r().ttl(chave)) and restante > 0:
                progresso.update(tarefa, completed=restante, total=max(TTL, restante))
                time.sleep(0.5)
    except KeyboardInterrupt:
        return
    ui.aviso("A sessão expirou.")


# ----------------------------------------------------------------------------
# Fluxo MongoDB -> Redis -> MongoDB
# ----------------------------------------------------------------------------
def _emitir(etapa: str, mensagem: str, conteudo=None) -> None:
    """Mostra no terminal o andamento do fluxo (a lógica está em ``sessoes_dados``)."""
    if etapa == "titulo":
        ui.titulo(mensagem)
    elif etapa == "json":
        ui.console.print(f"[bold]{mensagem}[/]")
        ui.console.print(JSON(conteudo))
    elif etapa == "aviso":
        ui.aviso(mensagem)
    else:
        ui.sucesso(mensagem)


def fluxo_itens() -> None:
    dados.executar_fluxo(_emitir)


# ----------------------------------------------------------------------------
# Menu
# ----------------------------------------------------------------------------
def testar_conexoes() -> bool:
    try:
        with ui.processando("Conectando ao MongoDB e ao Redis..."):
            mongo_db().client.admin.command("ping")
            r().ping()
        return True
    except (PyMongoError, RedisError) as exc:
        ui.erro(f"Falha de conexão: {exc}\nConfira o arquivo .env (MongoDB e Redis).")
        return False


def menu() -> None:
    sessao: str | None = None
    while True:
        ativa = sessao_ativa(sessao)
        ui.titulo(f"SESSÕES E CACHE (Redis)  |  {'sessão ativa' if ativa else 'sem sessão'}")
        if ativa:
            opcoes = [
                ("Executar fluxo MongoDB -> Redis -> MongoDB", "fluxo"),
                ("Acompanhar sessão ao vivo", "monitor"),
                ("Status da sessão", "status"),
                ("Logout", "logout"),
            ]
        else:
            opcoes = [("Login", "login")]
        try:
            escolha = ui.selecionar("Escolha uma opção", opcoes, voltar="Sair")
            if escolha is None:
                break
            if escolha == "login":
                sessao = login()
            elif escolha == "fluxo" and checar_sessao(sessao):
                fluxo_itens()
            elif escolha == "monitor":
                monitorar_sessao(sessao)  # type: ignore[arg-type]
            elif escolha == "status":
                checar_sessao(sessao, renovar=False)
            elif escolha == "logout":
                logout(sessao)
                sessao = None
        except ui.Cancelado:
            ui.aviso("Operação cancelada.")
        except (PyMongoError, RedisError) as exc:
            ui.erro(str(exc))


def main() -> None:
    if testar_conexoes():
        ui.apresentar("Redis", "banco chave-valor", RESUMO)
        menu()


if __name__ == "__main__":
    try:
        main()
    finally:
        fechar_conexoes()
