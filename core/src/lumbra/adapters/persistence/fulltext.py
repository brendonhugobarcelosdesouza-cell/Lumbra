"""Busca textual em Postgres — decisões compartilhadas entre adaptadores.

Mora aqui, e não dentro de um adapter, porque a semântica de recuperação é
uma decisão da PLATAFORMA: qualquer coisa que se recupere por texto (chunks,
playbooks, o que vier) tem de casar do mesmo jeito. Duplicar isso seria
duplicar a decisão, e um dos dois ficaria para trás.
"""

from __future__ import annotations

import re

_PALAVRA = re.compile(r"\w+", re.UNICODE)


def tsquery_or(query: str) -> str:
    """Monta um tsquery TOLERANTE: termos unidos por OR, não AND.

    ``websearch_to_tsquery`` exige TODOS os termos (AND), então uma
    pergunta natural como "total desta fatura" falha se UMA palavra
    ("desta") não está no documento — mesmo com "total" e "fatura"
    presentes. Numa busca de recuperação queremos o oposto: qualquer termo
    conta, e o ``ts_rank`` ordena por quantos/quão bem casam. Extraímos as
    palavras e as unimos por ``|``; a config ``portuguese`` do
    ``to_tsquery`` ainda faz o stemming e remove stopwords de cada uma.
    """
    return " | ".join(_PALAVRA.findall(query))


# canário anti-truncamento
