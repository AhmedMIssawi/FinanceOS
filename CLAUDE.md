# FinanceOS — context for Claude Code

Offline personal finance app for a solo user. Goal: track expenses,
manage debt payoff, reach $20k+/yr savings.

## Stack

- Python 3.11+
- Streamlit (UI, multi-page via `pages/` auto-discovery)
- SQLAlchemy 2.x ORM + plain SQLite (no encryption)
- Plotly (charts)
- pandas (analytics)
- `Decimal` for all money — from strings only, stored as TEXT, `ROUND_HALF_EVEN`

## Privacy / runtime

- Bound to `127.0.0.1:8501` only. Never exposed to network.
- DB lives in `data/finance.db` (gitignored). Move to `%APPDATA%\FinanceOS\`
  in Phase 7 polish.
- No login screen. Windows user account is the security boundary.

## Currency

Multi-currency display in v1.2 — USD, CAD, EUR, EGP. The active currency
is a module-level variable in `core/money.py` (`_active_currency_code`)
synced from the `currency_code` setting at every `init_db()` call.

`format_money(amount, code=None)` is the canonical formatter; if `code`
is None it uses the active currency. `format_cad()` survives as a
backwards-compatible alias that just delegates to `format_money`.

**Important:** switching the DISPLAY currency only changes the symbol
used to render KPI totals — it doesn't reach inside stored amounts.
The Settings page resets `savings_target` to `DEFAULT_SAVINGS_TARGET`
on display-currency change because the old number was denominated in
the old currency.

**Per-account currency (v1.4):** `Account.currency` is a 3-letter ISO
code, default `"CAD"`. Each account's `balance` is denominated in that
currency. KPI helpers in `core/dashboard_service.py`
(`net_worth`, `total_debt`, `cash_available`, `savings_total`,
`coins_total`) convert each account to the active display currency via
`_to_active` → `exchange_service.get_rate`. Accounts whose rate is
missing are silently skipped from totals; `accounts_with_missing_rates`
surfaces them so the page can warn the user. Coins-type accounts are
forced to CAD in the Add/Edit form (denomination grid is Canadian).
Transaction-level analytics (cash flow, spending pie, budgets) do NOT
yet currency-convert — that's deferred to v2 since it requires
per-transaction currency handling.

Currency, savings target, and developer password all live in
`core/settings_service.py` under their respective `KEY_*` constants.

## Exchange rates (v1.3, auto-update added)

`core/exchange_service.py` handles currency conversion.

**Storage:** `exchange_rates` table (from_currency, to_currency, rate,
updated_at). `RateType` in `models.py` is like `MoneyType` but without
2dp quantization (rates need precision — CAD->EGP ~22.4567).

**Inverse derivation:** `get_rate(session, from, to)` auto-derives the
inverse — if you saved CAD->EGP, querying EGP->CAD returns 1/rate.

**API:** `fetch_rates_from_api(base_code)` hits
`https://open.er-api.com/v6/latest/{base}` via `urllib.request` (stdlib).
Free, no API key, supports EGP. Failures raise; callers (auto-updater,
Settings button) catch and log warnings.

**Auto-update schedule:** `SCHEDULED_HOURS = (9, 13, 17, 21)`.
`last_scheduled_slot(now=None)` returns the most recent slot that has
passed. `needs_update(session, base)` returns True if no rates exist OR
the newest stored rate is older than that slot. `auto_update_if_needed`
combines both and never raises.

**Two trigger paths:**
1. **`init_db()`** calls `auto_update_if_needed` on first-process-run
   (bootstrap if no rates exist) and `start_auto_updater_thread()`.
2. **Background thread** (daemon=True, naïve `time.sleep(15 min)` loop)
   calls `auto_update_if_needed` continuously while the app is running.

The Settings page's "Refresh rates now" button is a third manual path.

**Conversion is opt-in:** the app does NOT auto-convert stored
transaction amounts when active currency changes. Rates power the
Calculator's currency tab. Future v2 work could add per-account currency
+ auto-conversion, but that's a larger refactor.

## Developer password & true privacy wipe

`KEY_DEV_PASSWORD` setting (default `"0000"`) gates the
"Developer settings" section in `pages/5_Settings.py` — that's where
the DB path and backup directory are shown. The password is stored as
plain text in the `settings` table because the app is local-only and
Windows file permissions are the real security boundary; the password
just hides implementation details from casual testers.

`core/backup_service.py` has `delete_all_backups()` which the Settings
page wires up via a checkbox alongside Reset. Ticking the checkbox runs
both `reset_database()` (which creates a pre-reset backup first) AND
`delete_all_backups()` (which then deletes that backup along with all
others) — a true wipe with no recovery, for handoff privacy.

## Categories (fixed enums, dropdown-only)

Housing, Food, Transport, Health, Personal (incl. Laundry),
Subscriptions, Education (incl. Tuition Fees), Debt Payments, Savings,
Income (incl. Cash Income, Coins), Other. Defined once in
`core/categories.py` (Phase 1) — never free text.

`SUBCATEGORY_PARENTS` in the same file maps refinement subcategories to
their parent for rollups (currently `Coins -> Cash Income`). Dropdowns
still show Coins as its own item (so the user can track coin income
distinctly), but `parent_subcategory()` should be used by reports and
the Dashboard to aggregate Coins into Cash Income totals.

## Phases

0. Setup + skeleton — **DONE**
1. DB + models + categories + money helpers + tests — **DONE**
2. Accounts + Transactions screens (with transfers) — **DONE**
3. Budgets screen — **DONE**
4. Debts + payoff calc (snowball + avalanche) — **DONE**
5. Dashboard + charts + recent-transactions widget — **DONE**
6. Settings + daily backup + reset + user guide — **DONE — v1 feature complete**

## Settings, backups, reset

User-configurable settings live in the `settings` key/value table.
`core/settings_service.py` provides typed accessors (e.g.
`get_savings_target`, `set_savings_target`). New settings should add a
`KEY_*` constant + getter/setter pair there.

Backups live in `data/backups/` with filenames
`finance_<YYYY-MM-DD>_<HH-MM-SS>[_<label>].db`. `core/backup_service.py`
exposes: `create_backup`, `list_backups`, `restore_backup`,
`daily_backup_if_needed`, `prune_old_backups`, `reset_database`.

Startup tasks (daily backup + 14-day prune) run inside `init_db()`,
guarded by a module-level `_app_started` flag so they execute at most
once per Python process even though Streamlit calls `init_db()` from
every page on every rerun.

`reset_database()` drops AND recreates all tables (wiping every row),
auto-creating a `pre-reset` backup first. The Settings page requires
the user to type `RESET` (uppercase) before the button fires.

## User guide

`FinanceOS.md` at the project root is the user-facing guide for
non-developer testers. Keep it in sync with feature changes.

## Dashboard

All data aggregation lives in `core/dashboard_service.py` (pure
read-only functions, fully tested). The Dashboard page is presentation
only — it shouldn't run inline DB queries.

Conventions:
- Transfers are excluded everywhere (they net to zero on cash flow).
- Spending magnitudes are `abs(amount)` — humans want positive dollars.
- `LIQUID_TYPES = (chequing, savings, cash)` for "Cash Available" —
  intentionally does NOT include "coins". Coins are their own KPI so
  the user can see physical-coin holdings distinctly.
- `DEBT_TYPES = (credit, financing, overdraft, loan)` mirrored from
  `pages/4_Debts.py`.
- `SAVINGS_TARGET = $20,000` is hardcoded in `Dashboard.py` for v1.
  Move to the Settings page (Phase 6) when user-editable goals land.

## Coin breakdown (per Coins account)

`core/coins_service.py` exposes `COIN_DENOMINATIONS` and helpers
(`parse_breakdown`, `serialize_breakdown`, `breakdown_total`,
`breakdown_summary`, `breakdown_count`). Per-account counts live in the
new `Account.coin_breakdown` column (TEXT, JSON-encoded; e.g.
`{"2.00": 4, "1.00": 5}`). Migration adds the column to existing DBs.

This data is **informational only** — it never feeds into balance math,
budget calculations, or analytics. The Accounts page renders:
1. A new "Coins accounts" table with `breakdown_summary` per row
2. An inline Plotly bar chart above the edit form when a coins-type
   account is selected (uses SAVED data, not WIP form values)
3. A denomination-grid editor inside the form (5 number_inputs for
   toonie/loonie/quarter/dime/nickel)

Save path: serialize the inputs via `serialize_breakdown` (which strips
zeros and returns None when empty so the column stays NULL). Switching
an account away from type=coins clears `coin_breakdown` automatically.

## Coins (account type)

The `coins` account type lets the user track physical coins separately
from bills (`cash`). Both are liquid, but coins behave differently:
the user receives them as income (e.g. summer laundry work), then
periodically transfers them to a `cash` account or deposits into a
bank account (via account-to-account Transfer). Coins are surfaced as
their own KPI on the Dashboard.

## Debt payment history

`core/debts_service.py` exposes `payments_to_account()` and
`payment_history()`. A "payment toward a debt" is detected as a
positive transfer leg on the debt account (kind="transfer", amount > 0).
Charges on a credit card are NOT payments — they're expenses (negative
amount, kind="expense") and don't count toward `payments_to_account`.

The Debts page surfaces this as a per-debt status table (Min/Paid this
month/Status vs min/Months to payoff) plus a 6-month per-debt history
chart with green bars when the user met or exceeded the minimum and
orange bars when they fell short.

## Debts

A "debt" is any Account whose type is in `DEBT_TYPES = ("credit",
"financing", "overdraft", "loan")` AND whose balance is negative.
This means debts are auto-detected — there's no separate debts table
the user has to maintain (despite the `Debt` model existing in
`models.py` as a future extension point).

`core/debt_engine.py` contains the simulator: a pure function that
takes a list of `Debt` dataclass inputs + extra_payment + strategy
("snowball" or "avalanche") and returns a `SimulationResult` with
months-to-debt-free, total interest paid, payoff month per debt, and
month-by-month total debt history (for the Plotly chart on the Debts page).

Interest is simple monthly compounding (`annual_rate / 100 / 12`).
Real credit card APR with fees and daily compounding will differ
slightly — good enough for planning, not a replacement for the
issuer's actual statements.

The Debts page also owns minimum-payment editing — `min_payment` lives
on the Account model so it persists across debt accounts, but the
Accounts page intentionally doesn't expose it (less form clutter).

## Budgets

Budgets are scoped per `(year, month, category)`. Setting a budget to 0
deletes its record. Income is not budgetable (you grow income, you don't
cap it). Transfers don't count toward any budget — `kind == "transfer"`
is excluded by `get_spent_by_category`. `copy_budgets` is non-destructive:
it skips categories already set in the destination month.

All budget queries and mutations live in `core/budgets_service.py`. The
page calls into the service; no inline DB queries in the page.

## Editing UX: click-to-edit via row selection

The Transactions and Accounts pages use `st.dataframe(on_select="rerun",
selection_mode="single-row")` for editing. Clicking a row sets the
selection; the inline edit form for that row renders below the table.
Transfers are displayed in the transactions table but can only be
deleted (not edited) — the inline UI swaps to a delete-only panel when
a transfer row is clicked.

If you add a new editable list, follow the same pattern: render the
table with selection enabled, capture the event, and render the edit
form for `items[event.selection.rows[0]]` below.

## Transaction-balance invariant

Every add/update/delete of a Transaction MUST also adjust the linked
Account.balance — and both writes MUST commit in the same DB transaction.
`core/transactions_service.py` is the only place that's allowed to mutate
balances via transactions. Pages call into that service. Tests in
`tests/test_transactions_service.py` lock the invariant.

The user enters a positive magnitude in the UI; sign is applied by
category (Income → +, everything else → -). This is a deliberate UX
choice — never ask the user to remember signs.

## Account-to-account transfers

A transfer is **two** Transaction rows sharing a `transfer_id` (UUID hex):
- source leg: `amount < 0`, `kind="transfer"`
- destination leg: `amount > 0`, `kind="transfer"`

Both rows are inserted and both account balances updated in a single
DB commit (`core.transactions_service.add_transfer`). Deleting either
leg via `delete_transaction()` cascades to both. Transfers are NOT
editable — UI excludes them from the regular edit dropdown; users
delete-and-recreate to change one. The transfer category constants
(`TRANSFER_CATEGORY`, `TRANSFER_SUBCATEGORY`) live in `core/categories.py`
but are intentionally absent from the `CATEGORIES` dict so they don't
show up in the regular transaction-entry dropdowns.

## Auto-archive for one-and-done debts

`core/archive_service.py` exposes `reconcile_archive(session, account)`
which is called from `add_transfer` (after commit) and `delete_transaction`
(for each affected account) in `core/transactions_service.py`.

Rules:
- `AUTO_ARCHIVE_TYPES = ("loan", "financing")`. Credit cards and overdraft
  are intentionally excluded — they're revolving facilities the user
  keeps using.
- If the account is in AUTO_ARCHIVE_TYPES, balance == $0, and not yet
  archived → set `archived=True`, `archived_at=now`, append a closing
  summary block to `notes` (open date, days, total paid, payment count).
- If archived and balance != $0 (e.g. user deleted the final payment) →
  un-archive. No summary cleanup; the historical block stays in notes.

Page-level filtering: `~Account.archived` is added to load_accounts in
pages/1_Accounts.py, pages/2_Transactions.py, and load_debts in
pages/4_Debts.py. Dashboard service queries don't need the filter
because archived debt accounts have balance==0 and contribute zero to
all sums (net_worth, total_debt with `< ZERO`, cash_available with
`> ZERO`, etc.).

The Settings page (`pages/5_Settings.py`) has an "Archived accounts"
section that lists archived accounts with their notes visible and an
Unarchive button per account.

The Transactions page surfaces a one-shot flash message via
`st.session_state["flash"]` so the 🎉 celebration on auto-archive
survives the `st.rerun()` that follows the payment.

## Loan accounts (between you and a friend)

Account type `loan` covers both directions in a single type. The Add
Account form (type=loan) collects: friend's name, amount outstanding,
and a "This loan is TO ME (I'm borrowing)" checkbox. The page composes
the account name automatically (`Loan to <name>` or `Loan from <name>`)
and applies the sign:
- Checked (TO ME): negative balance → counted as a liability.
- Unchecked (TO FRIEND): positive balance → counted as an asset.

Future lending/repayment events between the same parties are recorded
as transfers between the loan account and a real account (chequing, etc).
Multiple loans to the same person should be a single account with a
running balance — don't create a new account per loan event.

## Credit card accounts

Credit cards (type="credit") have a `credit_limit` field. The UI hides
the negative-balance input and instead asks for **credit limit** and
**available funds now**. The app stores `balance = available - limit`
(negative or zero) so the existing balance-aggregation logic keeps
working — `Net Worth = sum(all balances)` still adds credit cards as
liabilities automatically. Display derives: `owed = -balance`,
`available = credit_limit + balance`, `utilization% = owed/limit*100`.

## Schema migrations

Additive column changes use the tiny `_migrate()` function in
`core/db.py` (plain ALTER TABLE). It runs on every `init_db()` and is
idempotent. For renames, drops, or anything destructive, introduce
Alembic before touching the schema.

## Testing

```powershell
.\.venv\Scripts\Activate.ps1
pytest -v
```

Money helpers (`core/money.py`) carry full unit coverage — they are
the correctness backbone of the app. New money math anywhere must
add tests.

Build one phase at a time. Don't scaffold future phases.

## Money rules (non-negotiable)

- `Decimal("19.99")` — never `Decimal(19.99)` (string only)
- Stored as TEXT in SQLite, never REAL/FLOAT
- Rounding: `ROUND_HALF_EVEN` (banker's rounding)
- Helpers live in `core/money.py` (Phase 1)

## Run

First time:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

After that: double-click `run.bat`.
