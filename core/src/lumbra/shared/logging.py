"""Logging estruturado (structlog).

Regras de plataforma:

* Logs em JSON em produção; console legível em desenvolvimento.
* ``correlation_id`` propagado via contextvars — atravessa request →
  comando → eventos → workers (doc 16).
* Redação automática de chaves sensíveis: conteúdo do usuário e
  segredos NUNCA aparecem em logs (doc 18).
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Callable, MutableMapping
from typing import Any

import structlog

_TAPS: list[Callable[[MutableMapping[str, Any]], None]] = []


def install_log_tap(callback: Callable[[MutableMapping[str, Any]], None]) -> None:
    """Registra um observador de logs estruturados (Developer Console)."""
    _TAPS.append(callback)


def _tap_processor(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for tap in _TAPS:
        with contextlib.suppress(Exception):  # tap nunca afeta o logging
            tap(event_dict)
    return event_dict


_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "secret",
        "authorization",
        "jwt",
        "api_key",
        "content",  # conteúdo de memórias/mensagens/documentos
        "payload",  # payloads de eventos podem conter conteúdo do usuário
    }
)


def _redact_sensitive(
    _logger: object, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    """Configura logging global do processo. Idempotente."""
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,  # correlation_id etc.
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_sensitive,
            _tap_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


def bind_correlation_id(correlation_id: str) -> None:
    """Vincula o correlation_id ao contexto corrente (request/worker)."""
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
