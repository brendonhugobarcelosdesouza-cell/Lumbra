"""Testes de lumbra.shared.ids (UUIDv7, RFC 9562)."""

import time

from lumbra.shared.ids import uuid7


def test_version_is_7():
    assert uuid7().version == 7


def test_variant_is_rfc():
    # bits 62-63 do bloco final devem ser 0b10
    value = uuid7().int
    assert (value >> 62) & 0b11 == 0b10


def test_uniqueness_in_burst():
    ids = {uuid7() for _ in range(10_000)}
    assert len(ids) == 10_000


def test_time_ordering_across_milliseconds():
    first = uuid7()
    time.sleep(0.002)  # > 1 ms
    second = uuid7()
    assert first.int < second.int


def test_timestamp_prefix_matches_wall_clock():
    before_ms = time.time_ns() // 1_000_000
    generated = uuid7()
    after_ms = time.time_ns() // 1_000_000
    embedded_ms = generated.int >> 80
    assert before_ms <= embedded_ms <= after_ms
