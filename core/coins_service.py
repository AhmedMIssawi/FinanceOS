"""Per-account coin-denomination breakdown.

Informational only — these counts NEVER affect the Account.balance,
they're a separate tracking field so the user can record exactly how
many toonies/loonies/quarters/dimes/nickels live in a given Coins jar.
Useful for inventory and reconciliation; intentionally NOT used by
budget, dashboard, or debt analytics.

Stored on Account.coin_breakdown as a JSON string keyed by the
denomination value (e.g. {"2.00": 4, "1.00": 5}). Zero/missing keys
mean "none of that denomination".
"""
import json
from decimal import Decimal
from typing import Optional

# Canonical Canadian coin denominations (post-2013 penny phase-out).
# Each row: (short name, symbol, value).
COIN_DENOMINATIONS: list[tuple[str, str, Decimal]] = [
    ("Toonie",  "$2",  Decimal("2.00")),
    ("Loonie",  "$1",  Decimal("1.00")),
    ("Quarter", "25¢", Decimal("0.25")),
    ("Dime",    "10¢", Decimal("0.10")),
    ("Nickel",  "5¢",  Decimal("0.05")),
]


def parse_breakdown(raw: Optional[str]) -> dict[str, int]:
    """Parse the stored JSON. Returns {} on missing or malformed input."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return {str(k): int(v) for k, v in data.items() if int(v) >= 0}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}


def serialize_breakdown(counts: dict[str, int]) -> Optional[str]:
    """Encode counts to JSON. Drops zero/negative entries. Returns None
    when nothing remains (so the DB column stays NULL instead of '{}')."""
    cleaned = {str(k): int(v) for k, v in counts.items() if int(v) > 0}
    if not cleaned:
        return None
    return json.dumps(cleaned, sort_keys=True)


def breakdown_total(counts: dict[str, int]) -> Decimal:
    """Sum the dollar value implied by a breakdown. Purely informational —
    the caller can compare it to Account.balance for reconciliation."""
    total = Decimal("0")
    for _, _, value in COIN_DENOMINATIONS:
        count = counts.get(str(value), 0)
        total += value * Decimal(count)
    return total


def breakdown_summary(counts: dict[str, int]) -> str:
    """Compact, human-readable line: '4 toonies, 5 loonies, 4 quarters'.

    Used in the Coins-accounts table so each row shows what's inside
    without needing to click into the editor.
    """
    parts: list[str] = []
    for short, _, value in COIN_DENOMINATIONS:
        count = counts.get(str(value), 0)
        if count > 0:
            name = short.lower() + ("s" if count != 1 else "")
            parts.append(f"{count} {name}")
    return ", ".join(parts) if parts else "(no breakdown set)"


def breakdown_count(counts: dict[str, int]) -> int:
    """Total number of coins (regardless of denomination)."""
    return sum(int(counts.get(str(value), 0)) for _, _, value in COIN_DENOMINATIONS)
