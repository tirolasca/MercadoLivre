"""Hash de senhas com PBKDF2-HMAC-SHA256 (biblioteca padrão, sem dependências extras)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

ALGORITMO = "pbkdf2_sha256"
ITERACOES = 600_000  # recomendação OWASP para PBKDF2-HMAC-SHA256


def _derivar(senha: str, sal: bytes, iteracoes: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, iteracoes)


def gerar_hash(senha: str, iteracoes: int = ITERACOES) -> str:
    if len(senha) < 10:
        raise ValueError("Use uma senha com pelo menos 10 caracteres.")
    sal = secrets.token_bytes(16)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"{ALGORITMO}${iteracoes}${b64(sal)}${b64(_derivar(senha, sal, iteracoes))}"


def verificar(senha: str, armazenado: str | None) -> bool:
    """Compara em tempo constante. Hash ausente/inválido gasta tempo parecido e devolve ``False``."""
    try:
        algoritmo, iteracoes, sal_b64, hash_b64 = (armazenado or "").split("$")
        if algoritmo != ALGORITMO:
            raise ValueError
        sal, esperado, n = base64.b64decode(sal_b64), base64.b64decode(hash_b64), int(iteracoes)
    except (ValueError, TypeError):
        _derivar(senha, b"0" * 16, ITERACOES)  # equaliza o tempo de resposta
        return False
    return hmac.compare_digest(_derivar(senha, sal, n), esperado)


if __name__ == "__main__":  # python -m web.auth.senhas
    import getpass

    print(gerar_hash(getpass.getpass("Senha (não aparece na tela): ")))
