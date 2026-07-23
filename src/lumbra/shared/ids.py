"""Geração de identificadores UUIDv7 (RFC 9562).

UUIDv7 é ordenável por tempo (prefixo de 48 bits em milissegundos Unix),
o que melhora localidade de índices B-tree/HNSW e permite ordenação
cronológica natural de eventos e entidades.

Nota: unicidade é garantida pelos 74 bits aleatórios; monotonicidade
estrita dentro do mesmo milissegundo NÃO é garantida (não é requisito
do sistema — ordenação fina usa relógios lógicos no Sync Engine).
"""

from __future__ import annotations

import secrets
import time
import uuid

__all__ = ["uuid7"]

_UNIX_TS_MS_MASK = (1 << 48) - 1


def uuid7() -> uuid.UUID:
    """Gera um UUID versão 7 conforme RFC 9562."""
    timestamp_ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)

    value = (timestamp_ms & _UNIX_TS_MS_MASK) << 80
    value |= 0x7 << 76  # version = 7
    value |= rand_a << 64
    value |= 0b10 << 62  # variant = RFC 4122/9562
    value |= rand_b
    return uuid.UUID(int=value)
