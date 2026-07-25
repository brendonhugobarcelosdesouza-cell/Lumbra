"""Testes do contrato do port: padrões de assinatura e validação de specs."""

import pytest

from lumbra.ports.event_bus import ConsumerSpec, InvalidSubscriptionError, pattern_matches


async def _noop(_event):
    return None


class TestPatternMatching:
    @pytest.mark.parametrize(
        ("pattern", "event_type", "expected"),
        [
            ("*", "chat.message_received", True),
            ("chat.*", "chat.message_received", True),
            ("chat.*", "health.dose_due", False),
            ("chat.message_received", "chat.message_received", True),
            ("chat.message_received", "chat.message_answered", False),
            ("chat.*", "chatx.message_received", False),  # prefixo não é substring
        ],
    )
    def test_matching(self, pattern, event_type, expected):
        assert pattern_matches(pattern, event_type) is expected


class TestConsumerSpec:
    def test_valid_spec(self):
        spec = ConsumerSpec(name="memory-agent", patterns=("chat.*", "*"), handler=_noop)
        assert spec.accepts("chat.message_received")
        assert spec.accepts("finance.categorized")  # via '*'

    @pytest.mark.parametrize("bad_name", ["Memory", "1agent", "agent_x", ""])
    def test_invalid_names(self, bad_name):
        with pytest.raises(InvalidSubscriptionError):
            ConsumerSpec(name=bad_name, patterns=("*",), handler=_noop)

    @pytest.mark.parametrize("bad_pattern", ["chat.", "*.received", "Chat.*", "a.b.c", ""])
    def test_invalid_patterns(self, bad_pattern):
        with pytest.raises(InvalidSubscriptionError):
            ConsumerSpec(name="a", patterns=(bad_pattern,), handler=_noop)

    def test_empty_patterns_rejected(self):
        with pytest.raises(InvalidSubscriptionError):
            ConsumerSpec(name="a", patterns=(), handler=_noop)

    def test_max_attempts_bounds(self):
        with pytest.raises(InvalidSubscriptionError):
            ConsumerSpec(name="a", patterns=("*",), handler=_noop, max_attempts=0)
