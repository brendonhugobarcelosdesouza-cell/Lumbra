"""Qualidade de texto extraído — heurística barata e independente de idioma.

Vive em módulo próprio (e não em ``stages.extract``) porque tanto o
extrator de texto plano quanto o extrator de estrutura (``structure``)
precisam dela para escolher a melhor variante de leitura de um PDF, sem
que um estágio dependa do outro.
"""

from __future__ import annotations

import re


def legibilidade(texto: str) -> float:
    """Fração de tokens com tamanho de palavra plausível (2 a 18 letras).

    Extração boa produz prosa: a maioria dos tokens são palavras de
    comprimento normal. As DUAS formas de extração ruim caem fora dessa
    faixa e por isso pontuam baixo:

    * fragmentação — ``1 L anç a m ent o s`` — quase tudo vira token de
      1 caractere (abaixo do piso);
    * colagem — ``Totaldestafaturaanterior`` — várias palavras grudam num
      token gigante (acima do teto).

    Penalizar os dois extremos é o que faz a métrica escolher a extração
    com palavras separadas em vez da que só parece ter palavras. Barato e
    independente de idioma.
    """
    tokens = [t for t in re.split(r"\s+", texto) if t]
    if not tokens:
        return 0.0
    # números (7.016,60, R$, datas) não são "palavras": não contam contra
    # nem a favor, senão uma tabela financeira seria julgada ilegível
    palavras = [t for t in tokens if any(c.isalpha() for c in t)]
    if not palavras:
        return 0.0
    plausiveis = sum(1 for t in palavras if 2 <= len(t) <= 18)
    return plausiveis / len(palavras)


# canário anti-truncamento
