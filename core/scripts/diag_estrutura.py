"""Diagnóstico da ESTRUTURA extraída de um PDF (issue #10) — roda LOCAL.

Usa o MESMO código da plataforma (extract_blocks + chunk_blocks) para mostrar:
  - quais blocos a extração estruturada encontrou (tabelas, cabeçalhos, prosa);
  - se cada valor procurado caiu numa TABELA (bom) ou se diluiu na prosa (ruim);
  - o chunk exato onde cada valor está.

Uso (rode de dentro de core/, com o mesmo Python do Nó):
    python scripts/diag_estrutura.py "C:\\caminho\\Fatura.pdf" 7.016,60 6.314,94

Nada sai da sua máquina — só lê o PDF e imprime no terminal.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from lumbra.adapters.chunking.basic import default_chunker_registry
from lumbra.adapters.chunking.structural import chunk_blocks
from lumbra.domain.document_structure import BlockType
from lumbra.pipeline.stages.extract import _pdf_text
from lumbra.pipeline.structure import extract_blocks


def _probe_estrategias(raw: bytes, alvos: list[str]) -> None:
    """Testa estratégias de detecção de tabela do pdfplumber na fatura real,
    e mostra em qual delas cada valor procurado cai DENTRO de uma tabela
    (com seu rótulo na mesma linha). É o que decide a correção."""
    import pdfplumber

    estrategias: dict[str, dict[str, object]] = {
        "lines (padrao/atual)": {},
        "text (alinhamento)": {"vertical_strategy": "text", "horizontal_strategy": "text"},
        "v=text h=lines": {"vertical_strategy": "text", "horizontal_strategy": "lines"},
        "lines snap=4": {"snap_tolerance": 4},
    }
    print("\n== PROBE: estrategias de deteccao de tabela ==")
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for nome, cfg in estrategias.items():
            n_tab = 0
            achou = dict.fromkeys(alvos, False)
            linhas_alvo: list[str] = []
            for pi, page in enumerate(pdf.pages, 1):
                try:
                    tabelas = page.find_tables(table_settings=cfg) if cfg else page.find_tables()
                except Exception as exc:
                    linhas_alvo.append(f"    p{pi} ERRO: {type(exc).__name__}: {exc}")
                    continue
                for t in tabelas:
                    n_tab += 1
                    for row in t.extract():
                        celulas = [(c or "").strip() for c in row]
                        linha = " | ".join(celulas)
                        for a in alvos:
                            if a in linha:
                                achou[a] = True
                                linhas_alvo.append(f"    p{pi} [{a}] {linha[:140]!r}")
            print(f"\n### {nome}: {n_tab} tabela(s) | alvos em tabela: {achou}")
            for s in linhas_alvo[:10]:
                print(s)


def main() -> int:
    if len(sys.argv) < 2:
        print('Uso: python scripts/diag_estrutura.py "C:\\...\\Fatura.pdf" [valor1 valor2 ...]')
        return 1
    caminho = Path(sys.argv[1])
    if not caminho.is_file():
        print(f"Arquivo nao encontrado: {caminho}")
        return 1
    alvos = sys.argv[2:] or ["7.016,60", "6.314,94"]

    raw = caminho.read_bytes()
    texto = _pdf_text(raw)
    blocos = extract_blocks(raw=raw, mime="application/pdf", text=texto)
    tabelas = [b for b in blocos if b.type is BlockType.TABLE]

    print(f"\n== {caminho.name} ==")
    print(f"blocos: {len(blocos)} | tabelas detectadas: {len(tabelas)}")

    print("\n-- BLOCOS (na ordem do documento) --")
    for i, b in enumerate(blocos):
        if b.type is BlockType.TABLE:
            print(f"[{i}] TABLE p{b.page} ({len(b.rows)} linhas):")
            for linha in b.rows:
                print("       | " + " | ".join(linha))
        else:
            amostra = b.text[:90].replace("\n", " / ")
            print(f"[{i}] {b.type.value} p{b.page}: {amostra!r}")

    # como a plataforma realmente chunka este documento
    if tabelas:
        textos, metas = chunk_blocks(blocos)
        origem = "ESTRUTURAL (tem tabela)"
    else:
        chunker = default_chunker_registry().for_mime("application/pdf")
        textos = chunker.chunk(texto)
        metas = [None] * len(textos)
        origem = "LEGADO (nenhuma tabela detectada -> #10 volta)"

    print(f"\n-- CHUNKS via {origem}: {len(textos)} no total --")
    for alvo in alvos:
        encontrou = False
        for t, m in zip(textos, metas, strict=True):
            if alvo in t:
                encontrou = True
                tipo = m.block_type.value if (m and m.block_type) else "prosa/legado"
                print(f"  [{tipo}] contem {alvo}:")
                print(f"       {t[:160]!r}")
        if not encontrou:
            print(f"  {alvo}: NAO esta em nenhum chunk (no texto plano cru? {alvo in texto})")

    _probe_estrategias(raw, alvos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
