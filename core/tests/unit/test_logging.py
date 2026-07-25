"""Testes de logging estruturado: redação e correlação."""

import json

import structlog

from lumbra.shared.logging import bind_correlation_id, configure_logging, get_logger


def _capture_log(**kwargs) -> dict:
    """Configura logging JSON e captura uma linha emitida."""
    configure_logging(level="INFO", json_output=True)
    captured: list[str] = []
    structlog.configure(
        processors=structlog.get_config()["processors"],
        wrapper_class=structlog.get_config()["wrapper_class"],
        logger_factory=lambda *a: structlog.PrintLogger(file=_Sink(captured)),
        cache_logger_on_first_use=False,
    )
    get_logger("test").info("evento_teste", **kwargs)
    return json.loads(captured[0])


class _Sink:
    def __init__(self, captured: list[str]) -> None:
        self.captured = captured

    def write(self, message: str) -> None:
        self.captured.append(message)

    def flush(self) -> None:  # pragma: no cover
        pass


def test_sensitive_keys_are_redacted():
    entry = _capture_log(password="hunter2", token="jwt-abc", content="segredo do usuário")
    assert entry["password"] == "[REDACTED]"
    assert entry["token"] == "[REDACTED]"
    assert entry["content"] == "[REDACTED]"
    assert "hunter2" not in json.dumps(entry)


def test_normal_keys_pass_through():
    entry = _capture_log(document_id="doc-1", chunks=3)
    assert entry["document_id"] == "doc-1"
    assert entry["chunks"] == 3


def test_correlation_id_bound_to_context():
    structlog.contextvars.clear_contextvars()
    bind_correlation_id("corr-42")
    entry = _capture_log()
    assert entry["correlation_id"] == "corr-42"
    structlog.contextvars.clear_contextvars()
