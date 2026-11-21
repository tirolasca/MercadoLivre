"""Componentes visuais: ícones Lucide, cards, estados vazios e avisos que sobrevivem ao rerun."""

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from web.components import icones

RAIZ = Path(__file__).resolve().parents[2]


def _app(corpo: str) -> AppTest:
    return AppTest.from_string(
        f"import sys\nsys.path.insert(0, {str(RAIZ)!r})\n" + corpo
    ).run()


def _html(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_icone_lucide_e_decorativo_e_herda_a_cor():
    html = icones.svg("package", 20)
    assert (
        'stroke="currentColor"' in html
        and 'aria-hidden="true"' in html
        and 'width="20"' in html
    )


def test_icone_desconhecido_cai_num_circulo_sem_quebrar():
    assert "<circle" in icones.svg("nao-existe")
    assert not icones.existe("nao-existe")


def test_todo_icone_usado_nas_paginas_existe():
    codigo = " ".join(
        p.read_text(encoding="utf-8")
        for p in (RAIZ / "web").rglob("*.py")
    )

    usados = (
        set(re.findall(r'"icone": "([\w-]+)"', codigo))
        | set(re.findall(r'icone="([\w-]+)"', codigo))
    )

    usados |= set(
        re.findall(r'estado_vazio\([^)]*"([\w-]+)"\)', codigo)
    )

    faltando = {n for n in usados if not icones.existe(n)}
    assert not faltando, faltando


def test_cards_mostram_valor_icone_e_destaque():
    at = _app(
        'from web.components import cards\n'
        'cards.cards([{"rotulo": "Receita", "valor": "R$ 10,00", '
        '"icone": "wallet", "destaque": True}])'
    )

    html = _html(at)
    assert "R$ 10,00" in html
    assert "<svg" in html
    assert "destaque" in html


def test_card_sem_valor_vira_indisponivel_sem_numero():
    at = _app(
        'from web.components import cards\n'
        'cards.cards([{"rotulo": "Pedidos", "valor": None, '
        '"icone": "receipt-text"}])'
    )

    html = _html(at)
    assert "Indisponível" in html
    assert "indisponivel" in html


def test_estado_vazio_orienta_o_proximo_passo_e_escapa_html():
    at = _app(
        'from web.components import cards\n'
        'cards.estado_vazio("Nada aqui <b>", "Faça X.", "inbox")'
    )

    html = _html(at)
    assert "Faça X." in html
    assert "Nada aqui &lt;b&gt;" in html


def test_tabela_vazia_usa_estado_vazio():
    at = _app(
        'from web.components import cards\n'
        'cards.tabela([], {"a": "A"}, "Nenhum item.")'
    )

    html = _html(at)
    assert "Nenhum item." in html
    assert "ml-vazio" in html


def test_skeleton_dos_cards_declara_carregamento():
    at = _app(
        "from web.components import cards\n"
        "cards.cards_carregando(3)"
    )

    html = _html(at)
    assert html.count("ml-card skel") == 3
    assert 'aria-busy="true"' in html


def test_aviso_de_sucesso_sobrevive_ao_rerun():
    corpo = (
        "import streamlit as st\n"
        "from types import SimpleNamespace\n"
        "from web.components import feedback\n"
        "if st.button('ok'):\n"
        "    feedback.resposta('X', SimpleNamespace(ok=True), "
        "'Feito!', invalidar_cache=False)\n"
        "    st.rerun()\n"
        "feedback.exibir_pendentes()\n"
    )

    at = _app(corpo)
    at.button[0].click().run()

    assert [t.value for t in at.toast] == ["Feito!"]

    at.run()
    assert not at.toast


def test_aviso_imediato_quando_a_pagina_nao_recarrega():
    corpo = (
        "import streamlit as st\n"
        "from types import SimpleNamespace\n"
        "from web.components import feedback\n"
        "feedback.resposta('X', SimpleNamespace(ok=True), "
        "'Pronto', invalidar_cache=False, recarregar=False)\n"
    )

    assert [t.value for t in _app(corpo).toast] == ["Pronto"]


def test_css_tem_reducao_de_movimento_e_todas_as_variaveis_definidas():
    css = (
        RAIZ / "web" / "styles" / "app.css"
    ).read_text(encoding="utf-8")

    assert "prefers-reduced-motion: reduce" in css
    assert css.count("{") == css.count("}")

    variaveis_usadas = set(
        re.findall(r"var\((--[\w-]+)\)", css)
    )

    variaveis_definidas = set(
        re.findall(r"(--[\w-]+)\s*:", css)
    )

    assert variaveis_usadas <= variaveis_definidas


def test_nao_existe_pasta_pages_ao_lado_do_app():
    """Uma pasta `pages/` faria o Streamlit rodar páginas sem passar pelo app.py (ModuleNotFoundError em links diretos)."""
    assert not (RAIZ / "web" / "pages").exists()
    assert (RAIZ / "web" / "paginas" / "dashboard.py").exists()


_PAGINADOR = """
import streamlit as st
from web.components.paginacao import paginar

filtro = st.selectbox("filtro", ["a", "b"])
pagina, paginas, fatia = paginar(25, 10, "t", filtro)

st.text(f"P{pagina}/{paginas} inicio={fatia.start}")
"""


def _rotulo(at, rotulo):
    return next(b for b in at.button if b.label == rotulo)


def test_paginador_navega_respeita_limites_e_reinicia_com_o_filtro():
    at = _app(_PAGINADOR)

    assert at.text[0].value == "P1/3 inicio=0"
    assert _rotulo(at, "Anterior").disabled

    _rotulo(at, "Próxima").click().run()
    _rotulo(at, "Próxima").click().run()

    assert at.text[0].value == "P3/3 inicio=20"
    assert _rotulo(at, "Próxima").disabled

    at.selectbox[0].select("b").run()
    assert at.text[0].value == "P1/3 inicio=0"


def test_paginador_com_uma_pagina_nao_mostra_botoes():
    at = _app(_PAGINADOR.replace("paginar(25", "paginar(7"))

    assert at.text[0].value == "P1/1 inicio=0"
    assert not at.button
