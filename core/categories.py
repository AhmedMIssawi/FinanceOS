"""Fixed category and subcategory enums for transactions.

Categories are dropdown-only (not free text) so that statistical
analysis stays clean. To add a new category or subcategory, edit
CATEGORIES below. Renaming after data exists is a breaking change —
write a migration when the time comes.
"""

# Insertion order drives dropdown order.
CATEGORIES: dict[str, list[str]] = {
    "Housing": ["Rent", "Utilities", "Internet", "Maintenance"],
    "Food": ["Groceries", "Restaurants", "Coffee", "Takeout"],
    "Transport": ["Gas", "Transit", "Parking", "Car Insurance", "Car Maintenance"],
    "Health": ["Pharmacy", "Dental", "Insurance", "Gym"],
    "Personal": ["Clothing", "Haircut", "Laundry", "Hobbies"],
    "Subscriptions": ["Streaming", "Software", "Phone"],
    "Education": ["Tuition Fees", "Books", "Supplies", "Student Fees"],
    "Debt Payments": ["Credit Card", "Loan", "Line of Credit"],
    "Savings": ["Emergency Fund", "Goal Contribution"],
    "Income": ["Salary", "Cash Income", "Coins", "Bonus", "Refund", "Other"],
    "Other": ["Gift", "Travel", "Misc"],
}

# Income flows positive; everything else flows negative when persisted.
INCOME_CATEGORY = "Income"

# Internal category for account-to-account transfers. NOT in CATEGORIES
# so it doesn't appear in regular transaction dropdowns — transfers are
# created through their own UI path (core.transactions_service.add_transfer).
TRANSFER_CATEGORY = "Transfer"
TRANSFER_SUBCATEGORY = "Account Transfer"

# Subcategory -> parent subcategory, for analytics rollups.
# Example: "Coins" remains a distinct entry in dropdowns so you can track
# coin income explicitly, but in summaries it rolls into "Cash Income".
SUBCATEGORY_PARENTS: dict[str, str] = {
    "Coins": "Cash Income",
}


def parent_subcategory(name: str) -> str:
    """Return the parent subcategory for rollups, or the name itself if none."""
    return SUBCATEGORY_PARENTS.get(name, name)


def category_names() -> list[str]:
    return list(CATEGORIES.keys())


def subcategories_of(category: str) -> list[str]:
    return CATEGORIES.get(category, [])


def is_valid(category: str, subcategory: str) -> bool:
    return subcategory in CATEGORIES.get(category, [])


def is_income(category: str) -> bool:
    return category == INCOME_CATEGORY
