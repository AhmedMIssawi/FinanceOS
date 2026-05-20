"""Currency exchange rates — manual entry + optional internet fetch.

The app remains offline-first: rates are stored locally in the
`exchange_rates` table. Two ways to populate them:

1. Manual entry in Settings (works fully offline).
2. One-click fetch from open.er-api.com — a free, no-auth third-party
   service that returns daily rates for most currencies including EGP.
   Requires an internet connection AT FETCH TIME ONLY; once stored,
   the rates are available offline.

`get_rate()` auto-derives the inverse (enter CAD->EGP, EGP->CAD comes for free).

Conversion is a deliberate read-only feature for v1.3: stored transaction
amounts are NOT re-denominated when the display currency changes. The
currency converter widget in Settings uses these rates for one-off
"what's X CAD in EGP" calculations.
"""
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import ExchangeRate
from core.money import CURRENCIES

# Free, no-API-key endpoint. Updates daily. Documented at
# https://www.exchangerate-api.com/docs/free
API_URL_TEMPLATE = "https://open.er-api.com/v6/latest/{base}"
USER_AGENT = "FinanceOS/1.3 (personal finance app)"

# Auto-update fires after each of these wall-clock hours. To change the
# schedule, edit this tuple — values are 24h ints (0–23).
SCHEDULED_HOURS: tuple[int, ...] = (9, 13, 17, 21)

LOGGER = logging.getLogger(__name__)


def get_rate(
    session: Session, from_code: str, to_code: str
) -> Optional[Decimal]:
    """Return the stored rate for from -> to, deriving the inverse if needed.

    Returns Decimal('1') for same-currency. Returns None if neither
    direction is stored.
    """
    if from_code == to_code:
        return Decimal("1")

    direct = session.scalar(
        select(ExchangeRate).where(
            ExchangeRate.from_currency == from_code,
            ExchangeRate.to_currency == to_code,
        )
    )
    if direct is not None:
        return direct.rate

    inverse = session.scalar(
        select(ExchangeRate).where(
            ExchangeRate.from_currency == to_code,
            ExchangeRate.to_currency == from_code,
        )
    )
    if inverse is not None and inverse.rate > Decimal("0"):
        return Decimal("1") / inverse.rate

    return None


def set_rate(
    session: Session, from_code: str, to_code: str, rate: Decimal
) -> None:
    """Persist a rate. Overwrites if a row for this pair already exists."""
    if from_code not in CURRENCIES:
        raise ValueError(f"Unsupported source currency: {from_code}")
    if to_code not in CURRENCIES:
        raise ValueError(f"Unsupported target currency: {to_code}")
    if from_code == to_code:
        raise ValueError("Source and target must differ.")
    if rate <= Decimal("0"):
        raise ValueError("Rate must be positive.")

    existing = session.scalar(
        select(ExchangeRate).where(
            ExchangeRate.from_currency == from_code,
            ExchangeRate.to_currency == to_code,
        )
    )
    if existing is not None:
        existing.rate = rate
        existing.updated_at = datetime.now()
    else:
        session.add(
            ExchangeRate(
                from_currency=from_code,
                to_currency=to_code,
                rate=rate,
                updated_at=datetime.now(),
            )
        )
    session.commit()


def convert(
    amount: Decimal, from_code: str, to_code: str, session: Session
) -> Optional[Decimal]:
    """Convert `amount` from one currency to another. None if no rate stored."""
    rate = get_rate(session, from_code, to_code)
    if rate is None:
        return None
    return amount * rate


def fetch_rates_from_api(base_code: str = "CAD") -> dict[str, Decimal]:
    """Fetch latest rates from open.er-api.com.

    Returns {currency_code: rate} for every supported currency != base.
    Raises urllib.error.URLError on network failure, RuntimeError on bad
    response. Caller decides whether to persist via `set_rate`.
    """
    if base_code not in CURRENCIES:
        raise ValueError(f"Unsupported base currency: {base_code}")

    url = API_URL_TEMPLATE.format(base=base_code)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("result") != "success":
        raise RuntimeError(
            f"API returned non-success: {data.get('error-type', 'unknown')}"
        )

    rates_raw = data.get("rates", {})
    return {
        code: Decimal(str(rates_raw[code]))
        for code in CURRENCIES
        if code != base_code and code in rates_raw
    }


def update_rates_from_api(session: Session, base_code: str = "CAD") -> int:
    """Fetch + persist in one call. Returns the count saved."""
    rates = fetch_rates_from_api(base_code)
    for code, rate in rates.items():
        set_rate(session, base_code, code, rate)
    return len(rates)


def all_rates(session: Session) -> list[ExchangeRate]:
    """All stored rate rows, ordered for stable display."""
    return list(
        session.scalars(
            select(ExchangeRate).order_by(
                ExchangeRate.from_currency, ExchangeRate.to_currency
            )
        ).all()
    )


# --- Scheduled auto-update -------------------------------------------------


def last_scheduled_slot(now: Optional[datetime] = None) -> datetime:
    """Return the most recent SCHEDULED_HOURS slot that has already passed.

    Example: with SCHEDULED_HOURS = (9, 13, 17, 21) and now=14:30 today,
    returns today at 13:00. If now is before today's first slot (e.g.
    06:00), returns yesterday at the LAST slot (21:00).
    """
    if now is None:
        now = datetime.now()
    today_slots = sorted(
        now.replace(hour=h, minute=0, second=0, microsecond=0)
        for h in SCHEDULED_HOURS
    )
    past = [s for s in today_slots if s <= now]
    if past:
        return past[-1]
    yesterday = now - timedelta(days=1)
    return yesterday.replace(
        hour=max(SCHEDULED_HOURS), minute=0, second=0, microsecond=0
    )


def needs_update(
    session: Session, base_code: str, now: Optional[datetime] = None
) -> bool:
    """True if no rates are stored OR the newest stored rate is older
    than the most recent scheduled-update slot."""
    rates = all_rates(session)
    if not rates:
        return True
    newest = max(r.updated_at for r in rates)
    return newest < last_scheduled_slot(now)


def auto_update_if_needed(session: Session, base_code: str) -> bool:
    """If rates are stale per the schedule, fetch + persist. Returns True
    if a successful update happened, False otherwise (already fresh or
    fetch failed). Failures are logged at WARNING level — never raised —
    so the rest of the app keeps working when offline."""
    if not needs_update(session, base_code):
        return False
    try:
        update_rates_from_api(session, base_code)
        return True
    except Exception as e:
        LOGGER.warning(f"Auto rate update failed (base={base_code}): {e}")
        return False


# --- Background updater thread --------------------------------------------

_UPDATER_THREAD: Optional[threading.Thread] = None
_UPDATER_LOCK = threading.Lock()
_UPDATER_INTERVAL_SECONDS = 60 * 15  # check every 15 minutes


def start_auto_updater_thread() -> None:
    """Spawn a daemon thread that periodically calls auto_update_if_needed.

    Idempotent — calling twice is a no-op. Daemon=True so the thread
    dies when the Streamlit process exits (no orphaned workers).
    """
    global _UPDATER_THREAD
    with _UPDATER_LOCK:
        if _UPDATER_THREAD is not None and _UPDATER_THREAD.is_alive():
            return
        _UPDATER_THREAD = threading.Thread(
            target=_updater_loop,
            daemon=True,
            name="exchange-rate-updater",
        )
        _UPDATER_THREAD.start()


def _updater_loop() -> None:
    """Loop that wakes every _UPDATER_INTERVAL_SECONDS and checks if a
    scheduled-update slot has passed since the last successful fetch."""
    # Imported lazily to avoid a circular import at module load time.
    from core.db import SessionLocal
    from core.money import active_currency_code

    while True:
        try:
            with SessionLocal() as session:
                auto_update_if_needed(session, active_currency_code())
        except Exception as e:
            LOGGER.warning(f"Background rate updater iteration failed: {e}")
        time.sleep(_UPDATER_INTERVAL_SECONDS)
