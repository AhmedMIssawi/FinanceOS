"""Tests for core/coins_service.py — coin breakdown serialization + math."""
from decimal import Decimal

from core.coins_service import (
    COIN_DENOMINATIONS,
    breakdown_count,
    breakdown_summary,
    breakdown_total,
    parse_breakdown,
    serialize_breakdown,
)


def test_parse_breakdown_none():
    assert parse_breakdown(None) == {}


def test_parse_breakdown_empty_string():
    assert parse_breakdown("") == {}


def test_parse_breakdown_invalid_json():
    assert parse_breakdown("not-json") == {}


def test_parse_breakdown_valid():
    raw = '{"2.00": 4, "1.00": 5, "0.25": 3}'
    parsed = parse_breakdown(raw)
    assert parsed == {"2.00": 4, "1.00": 5, "0.25": 3}


def test_parse_breakdown_drops_negative():
    raw = '{"2.00": 4, "1.00": -3}'
    # Negative is dropped (treated as invalid via int conversion + filter)
    parsed = parse_breakdown(raw)
    assert parsed == {"2.00": 4}


def test_serialize_breakdown_strips_zeros():
    s = serialize_breakdown({"2.00": 4, "1.00": 0, "0.25": 3})
    assert s == '{"0.25": 3, "2.00": 4}'  # sorted, zero stripped


def test_serialize_breakdown_all_zero_returns_none():
    assert serialize_breakdown({"2.00": 0, "1.00": 0}) is None


def test_serialize_breakdown_empty_returns_none():
    assert serialize_breakdown({}) is None


def test_breakdown_total():
    # 4 toonies ($8) + 5 loonies ($5) + 4 quarters ($1) + 0 dimes + 0 nickels = $14
    counts = {"2.00": 4, "1.00": 5, "0.25": 4}
    assert breakdown_total(counts) == Decimal("14.00")


def test_breakdown_total_empty():
    assert breakdown_total({}) == Decimal("0")


def test_breakdown_summary_pluralizes():
    counts = {"2.00": 4, "1.00": 1, "0.25": 3}
    summary = breakdown_summary(counts)
    assert "4 toonies" in summary
    assert "1 loonie" in summary  # singular
    assert "3 quarters" in summary


def test_breakdown_summary_empty():
    assert breakdown_summary({}) == "(no breakdown set)"


def test_breakdown_count():
    counts = {"2.00": 4, "1.00": 5, "0.25": 3}
    assert breakdown_count(counts) == 12


def test_canonical_denominations_present():
    names = [short for short, _, _ in COIN_DENOMINATIONS]
    assert names == ["Toonie", "Loonie", "Quarter", "Dime", "Nickel"]


def test_roundtrip():
    original = {"2.00": 4, "1.00": 5, "0.25": 4}
    raw = serialize_breakdown(original)
    assert raw is not None
    parsed = parse_breakdown(raw)
    assert parsed == original
