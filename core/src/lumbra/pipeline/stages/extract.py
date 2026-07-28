"""Estágio extract: bytes → texto E estrutura por tipo de documento.

Produz duas saídas complementares: o ``text`` plano (contrato estável,
consumido hoje pelo chunking) e os ``blocks`` estruturados (issue #10),
que preservam tabelas, cabeçalhos e listas para o chunking ciente de
estrutura. A extração de estrutura é aditiva e nunca falha o estágio.
"""

from __future__ import annotations

import io

from lumbra.domain.pipeline import PipelineError, ProcessingState, StageOutcome
from lumbra.pipeline.structure import extract_blocks
from lumbra.pipeline.text_quality import legibilidade as _legibilidade
from lumbra.ports.pipeline import PipelineStagePort, StageInput
from lumbra.shared.logging import get_logger

_log = get_logger("lumbra.pipeline.extract")

_TEXT_PREFIXES = ("text/",)
_TEXT_MIMES = {"application/json", "application/xml", "application/x-code"}

# abaixo disto, aciona os extratores alternativos (ver _legibilidade).
# 0.85 porque prosa normal pontua ~0.9+, enquanto PDF financeiro com
# palavras coladas fica na faixa 0.4 a 0.7 (medido em fatura real) e
# merece uma segunda tentativa com tolerância menor.
_LEGIBILIDADE_MINIMA = 0.85


class ExtractStage(PipelineStagePort):
    @property
    def name(self) -> str:
        return "extract"

    @property
    def state(self) -> ProcessingState:
        return ProcessingState.EXTRACTING

    async def run(self, payload: StageInput) -> StageOutcome:
        if payload.raw is None:
            raise PipelineError("conteúdo bruto indisponível para extração")
        mime = payload.document.mime_type or "application/octet-stream"

        if mime.startswith(_TEXT_PREFIXES) or mime in _TEXT_MIMES:
            text = payload.raw.decode("utf-8", errors="replace")
        elif mime == "application/pdf":
            text = _pdf_text(payload.raw)
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = _docx_text(payload.raw)
        else:
            raise PipelineError(f"tipo não suportado pelo extractor: {mime}")

        if not text.strip():
            raise PipelineError("extração produziu texto vazio")
        # estrutura (issue #10): aditiva ao texto plano, nunca falha o estágio
        blocks = extract_blocks(raw=payload.raw, mime=mime, text=text)
        context = payload.context.model_copy(update={"text": text, "blocks": blocks})
        return StageOutcome(
            context=context,
            message=f"{len(text)} caracteres, {len(blocks)} blocos extraídos",
            metrics={"chars": float(len(text)), "blocks": float(len(blocks))},
        )


def _pypdf_text(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _pdfplumber_variants(raw: bytes) -> list[str]:
    """Extração ciente de layout, em duas tolerâncias de agrupamento.

    Alguns PDFs (faturas de banco) têm camada de texto SEM espaços entre
    palavras — o pypdf e o pdfplumber padrão devolvem tudo grudado
    (``Totaldafaturaanterior``). Um ``x_tolerance`` menor faz o pdfplumber
    inserir espaço quando a distância entre caracteres sugere fronteira de
    palavra. O valor 1.5 foi o melhor ponto MEDIDO numa fatura real
    (script ``scripts/diag_extract.py``): separa ``Total da fatura
    anterior`` sem sobre-fragmentar. Mantemos também a variante padrão,
    e ``_pdf_text`` fica com a de maior legibilidade.

    Lista vazia se a biblioteca não estiver instalada — o extrator degrada
    para o pypdf sem quebrar."""
    try:
        import pdfplumber
    except ImportError:
        return []
    variantes: list[str] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        variantes.append("\n\n".join(p.extract_text(x_tolerance=1.5) or "" for p in pdf.pages))
        variantes.append("\n\n".join(p.extract_text() or "" for p in pdf.pages))
    return variantes


def _pdf_text(raw: bytes) -> str:
    """Extrai texto do PDF escolhendo a variante de maior legibilidade.

    O pypdf é rápido e resolve a maioria dos casos. Quando o resultado
    vem ilegível (fragmentado OU com palavras coladas), acionamos o
    pdfplumber em duas variantes e ficamos com a melhor de todas — nunca
    com uma pior que o pypdf. Assim o caso comum continua barato e a
    fatura de layout complexo deixa de virar lixo indexado (issues #6/#8)."""
    pypdf = _pypdf_text(raw)
    if _legibilidade(pypdf) >= _LEGIBILIDADE_MINIMA:
        return pypdf
    candidatos = [pypdf, *_pdfplumber_variants(raw)]
    melhor = max(candidatos, key=_legibilidade)
    if melhor is not pypdf:
        _log.info(
            "pdf_extracao_com_fallback",
            pypdf=round(_legibilidade(pypdf), 3),
            escolhido=round(_legibilidade(melhor), 3),
            variantes=len(candidatos),
        )
    return melhor


def _docx_text(raw: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(raw))
    return "\n\n".join(p.text for p in document.paragraphs)


# canário anti-truncamento
