"""Camada de apresentação: tabelas, painéis, menus e perguntas interativas.

Usa ``rich`` para a saída (tabelas, painéis, barras, spinners) e ``questionary``
para a entrada (menus navegáveis por setas, busca com filtro, autocompletar,
senha oculta e confirmação). Os demais módulos não imprimem nem leem nada
diretamente: tudo passa por aqui.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import questionary
from questionary import Choice, Style
from rich import box
from rich.bar import Bar
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

console = Console()

TEMA = Style(
    [
        ("qmark", "fg:#ffcc00 bold"),
        ("question", "bold"),
        ("answer", "fg:#2d8cff bold"),
        ("pointer", "fg:#ffcc00 bold"),
        ("highlighted", "fg:#ffcc00 bold"),
        ("selected", "fg:#2d8cff"),
        ("instruction", "fg:#808080"),
        ("text", ""),
    ]
)

_VOLTAR = object()


class Cancelado(Exception):
    """O usuário interrompeu a pergunta (Ctrl+C)."""


# ----------------------------------------------------------------------------
# Mensagens
# ----------------------------------------------------------------------------
def sucesso(msg: str) -> None:
    console.print(f"[bold green]OK[/]     {escape(msg)}")


def erro(msg: str) -> None:
    console.print(f"[bold red]ERRO[/]   {escape(msg)}")


def aviso(msg: str) -> None:
    console.print(f"[bold yellow]AVISO[/]  {escape(msg)}")


def info(msg: str) -> None:
    console.print(f"[bold cyan]INFO[/]   {escape(msg)}")


def titulo(texto: str) -> None:
    console.print()
    console.print(Rule(f"[bold]{escape(texto)}[/]", style="yellow", align="left"))


def banner(nome: str, descricao: str = "") -> None:
    corpo = Text(nome, style="bold yellow", justify="center")
    if descricao:
        corpo.append(f"\n{descricao}", style="dim")
    console.print(Panel(corpo, box=box.DOUBLE, border_style="yellow", padding=(1, 4)))


def painel(titulo_painel: str, conteudo: Any, cor: str = "cyan") -> Panel:
    return Panel(conteudo, title=f"[bold]{escape(titulo_painel)}[/]", border_style=cor, box=box.ROUNDED)


def apresentar(banco: str, tipo: str, linhas: Sequence[str]) -> None:
    """Painel curto exibido ao abrir cada módulo: o que é o banco e por que ele está aqui."""
    corpo = "\n".join(f"• {escape(l)}" for l in linhas)
    console.print(Panel(corpo, title=f"[bold]{escape(banco)}[/]  [dim]{escape(tipo)}[/]", border_style="yellow", box=box.ROUNDED))


def processando(msg: str):
    """Spinner: ``with ui.processando("Consultando..."):``"""
    return console.status(f"[cyan]{escape(msg)}[/]", spinner="dots")


# ----------------------------------------------------------------------------
# Tabelas e gráficos
# ----------------------------------------------------------------------------
def tabela(
    titulo_tabela: str,
    colunas: Sequence[str | tuple[str, str]],
    linhas: Sequence[Sequence[Any]],
    vazio: str = "Nenhum registro encontrado.",
) -> None:
    """Imprime uma tabela. ``colunas``: nome ou ``(nome, alinhamento)``.

    Células ``str`` são escapadas (dados do usuário não são interpretados como
    marcação do rich); passe ``Text`` para células estilizadas.
    """
    if not linhas:
        aviso(vazio)
        return
    tab = Table(title=f"[bold]{escape(titulo_tabela)}[/]", box=box.SIMPLE_HEAVY, header_style="bold yellow", title_justify="left")
    for col in colunas:
        nome, alinhamento = (col, "left") if isinstance(col, str) else col
        tab.add_column(nome, justify=alinhamento)  # type: ignore[arg-type]
    for linha in linhas:
        tab.add_row(*[escape(str(c)) if isinstance(c, str) else c for c in linha])
    tab.caption = f"{len(linhas)} registro(s)"
    console.print(tab)


def barra(valor: float, maximo: float, largura: int = 24, cor: str = "yellow") -> Bar:
    return Bar(size=max(maximo, 1), begin=0, end=valor, width=largura, color=cor)


def status_texto(status: str) -> Text:
    cores = {"ativo": "green", "pago": "green", "pausado": "yellow", "inativo": "red"}
    return Text(status, style=cores.get(status, "white"))


# ----------------------------------------------------------------------------
# Entrada
# ----------------------------------------------------------------------------
def _resposta(pergunta: questionary.Question) -> Any:
    try:
        resposta = pergunta.unsafe_ask()
    except KeyboardInterrupt:
        raise Cancelado from None
    if resposta is None:
        raise Cancelado
    return resposta


def perguntar(
    rotulo: str,
    validador: Callable[[str], Any] = str,
    obrigatorio: bool = True,
    padrao: str = "",
    senha: bool = False,
    sugestoes: Sequence[str] | None = None,
) -> Any:
    """Lê um texto validado e devolve o valor convertido pelo ``validador``.

    * ``obrigatorio=False``: Enter em branco devolve ``None``.
    * ``padrao``: texto já preenchido (útil em edições).
    * ``sugestoes``: ativa autocompletar enquanto digita.
    """

    def validar(texto: str) -> bool | str:
        texto = texto.strip()
        if not texto:
            return True if not obrigatorio else "Campo obrigatório."
        try:
            validador(texto)
        except Exception as exc:  # noqa: BLE001 - qualquer erro vira mensagem
            return str(exc) or "Valor inválido."
        return True

    if senha:
        pergunta = questionary.password(rotulo, validate=validar, style=TEMA)
    elif sugestoes:
        pergunta = questionary.autocomplete(
            rotulo, choices=list(sugestoes), default=padrao, validate=validar, match_middle=True, style=TEMA
        )
    else:
        pergunta = questionary.text(rotulo, default=padrao, validate=validar, style=TEMA)

    bruto = str(_resposta(pergunta)).strip()
    return validador(bruto) if bruto else None


def confirmar(msg: str, padrao: bool = False) -> bool:
    return bool(_resposta(questionary.confirm(msg, default=padrao, style=TEMA)))


def selecionar(
    mensagem: str,
    opcoes: Sequence[tuple[str, Any]],
    voltar: str | None = "Voltar",
    filtro: bool = False,
    padrao: Any = None,
) -> Any:
    """Menu por setas. Devolve o valor da opção, ou ``None`` se escolher voltar.

    ``filtro=True`` permite digitar para filtrar listas longas.
    """
    escolhas = [Choice(titulo_opcao, value=valor) for titulo_opcao, valor in opcoes]
    if voltar:
        escolhas.append(Choice(f"<- {voltar}", value=_VOLTAR))
    inicial = next((c for c in escolhas if padrao is not None and c.value == padrao), None)
    pergunta = questionary.select(
        mensagem,
        choices=escolhas,
        default=inicial,
        style=TEMA,
        use_search_filter=filtro,
        use_jk_keys=not filtro,
        instruction="(setas para navegar, Enter para escolher)" if not filtro else "(digite para filtrar)",
    )
    resposta = _resposta(pergunta)
    return None if resposta is _VOLTAR else resposta


def menu(titulo_menu: str, acoes: Sequence[tuple[str, Callable[[], None]]], raiz: bool = False) -> None:
    """Laço de menu usado por todos os módulos: executa a ação escolhida e trata erros sem fechar o programa."""
    while True:
        titulo(titulo_menu)
        try:
            acao = selecionar("Escolha uma opção", list(acoes), voltar="Sair" if raiz else "Voltar")
        except Cancelado:
            return
        if acao is None:
            return
        try:
            acao()
        except Cancelado:
            aviso("Operação cancelada.")
        except Exception as exc:  # noqa: BLE001 - erro de banco/validação não derruba o menu
            erro(f"{type(exc).__name__}: {exc}")
