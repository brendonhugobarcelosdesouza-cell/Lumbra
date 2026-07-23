"""Diagnóstico de extração de PDF — roda LOCALMENTE no seu arquivo.

Testa vários modos de extrair texto de um PDF e mede qual separa melhor
as palavras (legibilidade), mostrando uma amostra ao redor de "total".
Objetivo: calibrar a extração da plataforma com dado real, não no escuro.

Uso:
    python scripts/diag_extract.py "C:\\caminho\\para\\Fatura.pdf"

Nada sai da sua máquina. É só leitura do PDF e impressão no terminal.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path


def legibilidade(texto: str) -> float:
    """Mesma métrica da plataforma: fração de 'palavras' (só letras) com
    tamanho plausível (2 a 18). Penaliza fragmentação E colagem."""
    tokens = [t for t in re.split(r"\s+", texto) if t]
    palavras = [t for t in tokens if any(c.isalpha() for c in t)]
    if not palavras:
        return 0.0
    plausiveis = sum(1 for t in palavras if 2 <= len(t) <= 18)
    return plausiveis / len(palavras)


def amostra(texto: str, termo: str = "total", janela: int = 160) -> str:
    """Trecho ao redor da primeira ocorrência de `termo` (sem acento/caixa)."""
    plano = texto.lower()
    pos = plano.find(termo)
    if pos < 0:
        return texto[:janela].replace("\n", " ⏎ ")
    ini = max(0, pos - 20)
    return texto[ini : ini + janela].replace("\n", " ⏎ ")


def _pypdf(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def _plumber(raw: bytes, **kwargs: object) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        return "\n".join(p.extract_text(**kwargs) or "" for p in pdf.pages)  # type: ignore[arg-type]


def _plumber_words(raw: bytes, x_tolerance: float) -> str:
    """Reconstrói o texto a partir de extract_words (agrupamento explícito
    por posição), inserindo espaço entre cada palavra detectada."""
    import pdfplumber

    linhas: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for pagina in pdf.pages:
            palavras = pagina.extract_words(x_tolerance=x_tolerance)
            linhas.append(" ".join(w["text"] for w in palavras))
    return "\n".join(linhas)


def main() -> int:
    if len(sys.argv) < 2:
        print('Uso: python scripts/diag_extract.py "C:\\caminho\\Fatura.pdf"')
        return 1
    caminho = Path(sys.argv[1])
    if not caminho.is_file():
        print(f"Arquivo não encontrado: {caminho}")
        return 1
    raw = caminho.read_bytes()

    metodos: list[tuple[str, object]] = [
        ("pypdf", lambda: _pypdf(raw)),
        ("plumber padrão", lambda: _plumber(raw)),
        ("plumber layout=True", lambda: _plumber(raw, layout=True)),
        ("plumber x_tol=2", lambda: _plumber(raw, x_tolerance=2)),
        ("plumber x_tol=1.5", lambda: _plumber(raw, x_tolerance=1.5)),
        ("plumber x_tol=1", lambda: _plumber(raw, x_tolerance=1)),
        ("words x_tol=3", lambda: _plumber_words(raw, 3)),
        ("words x_tol=1.5", lambda: _plumber_words(raw, 1.5)),
        ("words x_tol=1", lambda: _plumber_words(raw, 1)),
    ]

    print(f"\nArquivo: {caminho.name}\n")
    print(f"{'MÉTODO':<22} {'LEGIB.':>7}  AMOSTRA (ao redor de 'total')")
    print("-" * 100)
    resultados: list[tuple[str, float]] = []
    for nome, fn in metodos:
        try:
            texto = fn()  # type: ignore[operator]
            leg = legibilidade(texto)
            resultados.append((nome, leg))
            linha = f"{nome:<22} {leg:>7.3f}  {amostra(texto)}"
            print(linha.encode("ascii", "replace").decode("ascii"))
        except Exception as exc:  # noqa: BLE001
            print(f"{nome:<22} {'ERRO':>7}  {type(exc).__name__}: {exc}")

    if resultados:
        melhor = max(resultados, key=lambda r: r[1])
        print("-" * 100)
        print(f"\nMelhor separação de palavras: {melhor[0]} (legibilidade {melhor[1]:.3f})")
        print("Cole a saída acima na conversa que eu calibro a extração da plataforma.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
