"""Calculator — arithmetic + currency conversion + Canadian cash counter.

All three live outside the financial-data pipeline (Accounts / Transactions /
Budgets). Nothing here writes to the database — they're pure utilities so
you don't have to alt-tab to Calculator.exe or open a browser tab.

Arithmetic uses Python's `ast` module to evaluate expressions safely
(no `eval()` exposure), and Decimal everywhere so 0.1 + 0.2 == 0.3.
Currency conversion uses the rates auto-updated via Settings → Exchange rates.
Cash counter is hardcoded to Canadian denominations (the user's primary currency).
"""
import ast
from decimal import Decimal, InvalidOperation

import streamlit as st

from core.db import SessionLocal, init_db
from core.exchange_service import convert, get_rate
from core.money import CURRENCIES, active_currency_code, format_money

init_db()

st.set_page_config(page_title="Calculator | FinanceOS", layout="wide")
st.title("Calculator")
st.caption(
    "Arithmetic, currency conversion, and a Canadian cash counter — all "
    "separate from your accounts and transactions. Nothing here writes "
    "to the database."
)


# --- Safe arithmetic evaluator --------------------------------------------

_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
}
_ALLOWED_UNARYOPS = {
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: a,
}


def _eval_node(node):
    """Walk an AST, allowing only numeric constants, parens, + - * /, and unary +/-."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand))
    raise ValueError(f"Unsupported expression element: {type(node).__name__}")


def safe_arithmetic(expr: str) -> Decimal:
    """Evaluate a numeric expression with Decimal precision."""
    if not expr.strip():
        raise ValueError("Empty expression.")
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)


# --- Canadian cash denominations -----------------------------------------

# Bills currently in circulation: $5, $10, $20, $50, $100
# Coins in circulation post-2013 penny phase-out: $2, $1, $0.25, $0.10, $0.05
CAD_BILLS = [
    ("$100", Decimal("100")),
    ("$50",  Decimal("50")),
    ("$20",  Decimal("20")),
    ("$10",  Decimal("10")),
    ("$5",   Decimal("5")),
]
CAD_COINS = [
    ("$2 (toonie)",     Decimal("2")),
    ("$1 (loonie)",     Decimal("1")),
    ("25¢ (quarter)",   Decimal("0.25")),
    ("10¢ (dime)",      Decimal("0.10")),
    ("5¢ (nickel)",     Decimal("0.05")),
]


# --- Three tabs -----------------------------------------------------------

tab_calc, tab_currency, tab_cash = st.tabs(
    ["Calculator", "Currency converter", "Cash counter"]
)

with tab_calc:
    st.subheader("Calculator")
    st.caption(
        "Supports `+ − × ÷` and parentheses. Uses Decimal precision so "
        "`0.1 + 0.2` is exactly `0.3` (no float drift). Function calls "
        "and variables are blocked for safety."
    )
    expr = st.text_input(
        "Expression",
        value="",
        placeholder="e.g. (100 + 25.50) * 1.05",
        key="calc_expr",
    )
    if expr.strip():
        try:
            result = safe_arithmetic(expr)
            st.success(f"### = {result}")
        except ZeroDivisionError:
            st.error("Division by zero.")
        except (SyntaxError, ValueError, InvalidOperation) as e:
            st.error(f"Couldn't evaluate: {e}")
        except Exception as e:
            st.error(f"Couldn't evaluate: {e}")
    else:
        st.caption(":grey[Type an expression above and press Enter.]")

    st.divider()
    st.markdown("**Examples**")
    st.markdown(
        "- Split a $124.50 dinner four ways: `124.50 / 4`\n"
        "- Tax on $200 at 13%: `200 * 0.13`\n"
        "- Total with tip + tax: `(85 + 11.05) * 1.15`\n"
        "- Compound monthly: `1000 * (1 + 0.05/12)`"
    )

with tab_currency:
    st.subheader("Currency converter")
    st.caption(
        "Uses rates auto-updated via **Settings → Exchange rates** (every "
        "few hours from open.er-api.com). Click 'Refresh rates now' in "
        "Settings if you need the very latest."
    )

    cc1, cc2, cc3 = st.columns([2, 1, 1])
    with cc1:
        cc_amount = st.text_input("Amount", value="100.00", key="cc_amount")
    with cc2:
        cur_list = list(CURRENCIES.keys())
        cc_from = st.selectbox(
            "From",
            cur_list,
            key="cc_from",
            index=cur_list.index(active_currency_code()),
        )
    with cc3:
        default_target = "EGP" if active_currency_code() != "EGP" else "USD"
        cc_to = st.selectbox(
            "To",
            cur_list,
            key="cc_to",
            index=cur_list.index(default_target),
        )

    try:
        amt = Decimal(cc_amount.strip())
    except (InvalidOperation, ValueError):
        st.caption(":grey[Enter a valid amount.]")
    else:
        if amt <= Decimal("0"):
            st.caption(":grey[Enter a positive amount.]")
        else:
            with SessionLocal() as session:
                result = convert(amt, cc_from, cc_to, session)
                rate = get_rate(session, cc_from, cc_to)
            if result is not None and rate is not None:
                quantized = result.quantize(Decimal("0.01"))
                cur_to_symbol = CURRENCIES[cc_to]["symbol"]
                cur_from_symbol = CURRENCIES[cc_from]["symbol"]
                st.info(
                    f"### **{cur_from_symbol}{amt} {cc_from}  =  "
                    f"{cur_to_symbol}{quantized} {cc_to}**"
                )
                st.caption(
                    f"Rate used: 1 {cc_from} = {rate} {cc_to} "
                    f"(stored locally — open Settings to refresh)"
                )
            else:
                st.warning(
                    f"No rate stored for **{cc_from} → {cc_to}** (or its inverse). "
                    "Open **Settings → Exchange rates** to add one — either "
                    "manually, or click 'Refresh rates now' for an internet fetch."
                )

with tab_cash:
    st.subheader("Cash counter (CAD)")
    st.caption(
        "Enter how many of each Canadian bill and coin you have on hand. "
        "Each row shows its subtotal beside the count; the three totals "
        "below update live. Bills and coins are kept separate so the "
        "subtotals match your **Cash** and **Coins** account balances cleanly."
    )

    # Reset trick: bumping this token forces fresh widget instances with
    # value=0. Streamlit doesn't let you mutate the value of a widget that
    # already rendered this run, so a fresh-key approach is the clean fix.
    if "cash_reset_token" not in st.session_state:
        st.session_state["cash_reset_token"] = 0

    rcol1, _ = st.columns([1, 4])
    with rcol1:
        if st.button("Clear all counts", key="cash_clear_all"):
            st.session_state["cash_reset_token"] += 1
            st.rerun()

    reset_suffix = st.session_state["cash_reset_token"]

    def _row(category: str, label: str, value: Decimal) -> int:
        """Render one denomination row: input on the left, live subtotal on the right.

        `category` is "bill" or "coin"; it just keeps widget keys unique."""
        count_key = f"{category}_{value}_{reset_suffix}"
        icol, scol = st.columns([3, 2], vertical_alignment="center")
        with icol:
            count = st.number_input(
                label,
                min_value=0,
                value=0,
                step=1,
                key=count_key,
            )
        with scol:
            subtotal = Decimal(count) * value
            if count > 0:
                st.markdown(f"= **{format_money(subtotal, 'CAD')}**")
            else:
                st.markdown(":grey[—]")
        return count

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**Bills**")
        bill_counts: dict[Decimal, int] = {}
        for label, value in CAD_BILLS:
            bill_counts[value] = _row("bill", label, value)

    with c2:
        st.markdown("**Coins**")
        coin_counts: dict[Decimal, int] = {}
        for label, value in CAD_COINS:
            coin_counts[value] = _row("coin", label, value)

    bills_total = sum(
        (Decimal(bill_counts[v]) * v for _, v in CAD_BILLS),
        Decimal("0"),
    )
    coins_total = sum(
        (Decimal(coin_counts[v]) * v for _, v in CAD_COINS),
        Decimal("0"),
    )
    grand_total = bills_total + coins_total

    st.divider()
    tc1, tc2, tc3 = st.columns(3)
    tc1.metric("Bills total", format_money(bills_total, "CAD"))
    tc2.metric("Coins total", format_money(coins_total, "CAD"))
    tc3.metric("Grand total", format_money(grand_total, "CAD"))

    if grand_total > Decimal("0"):
        st.caption(
            "💡 The **Bills total** can match your *Cash* account balance, "
            "and **Coins total** can match your *Coins* account balance "
            "in the Accounts page. Use this counter before depositing or "
            "before reconciling what you physically have on hand."
        )
