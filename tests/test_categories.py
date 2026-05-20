"""Sanity tests for the category enum."""
from core.categories import (
    CATEGORIES,
    category_names,
    is_income,
    is_valid,
    parent_subcategory,
    subcategories_of,
)


def test_required_categories_exist():
    for required in ("Housing", "Food", "Transport", "Education", "Income", "Debt Payments"):
        assert required in CATEGORIES


def test_cash_income_is_income_subcategory():
    assert "Cash Income" in subcategories_of("Income")


def test_coins_is_income_subcategory():
    assert "Coins" in subcategories_of("Income")


def test_tuition_is_education_subcategory():
    assert "Tuition Fees" in subcategories_of("Education")


def test_laundry_is_personal_subcategory():
    assert "Laundry" in subcategories_of("Personal")


def test_is_valid_accepts_known_pair():
    assert is_valid("Food", "Groceries")


def test_is_valid_rejects_mismatch():
    assert not is_valid("Food", "Tuition Fees")


def test_is_valid_rejects_unknown_category():
    assert not is_valid("BogusCategory", "Whatever")


def test_is_income():
    assert is_income("Income")
    assert not is_income("Housing")


def test_dropdown_order_starts_with_housing():
    # Insertion order matters: the first item is what appears at the top
    # of dropdowns and the user should see Housing first.
    assert category_names()[0] == "Housing"


def test_coins_rolls_up_to_cash_income():
    assert parent_subcategory("Coins") == "Cash Income"


def test_subcategory_without_mapping_returns_itself():
    assert parent_subcategory("Salary") == "Salary"
    assert parent_subcategory("Groceries") == "Groceries"
