from datetime import date

import pytest

from skimwise.db.budget_repo import BudgetRepository
from skimwise.db.category_repo import CategoryRepository
from skimwise.db.connection import connect
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.services.budgets import NEAR, OK, OVER, BudgetError, BudgetLine, BudgetService
from skimwise.services.categories import CategoryService
from skimwise.services.transactions import TransactionService


@pytest.fixture
def app():
    conn = connect(":memory:")
    tx_repo, cat_repo = TransactionRepository(conn), CategoryRepository(conn)
    cats = {c.name: c.id for c in cat_repo.list()}
    return BudgetService(BudgetRepository(conn), tx_repo, cat_repo), TransactionService(tx_repo), cats


@pytest.mark.parametrize(
    "spent, level", [(0, OK), (7999, OK), (8000, NEAR), (10000, NEAR), (10001, OVER)]
)  # limit is $100: 80% is "near", exactly at the limit is still "near"
def test_levels(spent, level):
    assert BudgetLine(1, "x", 10000, spent).level == level


def test_lines_net_spending_for_the_month(app):
    budgets, txs, cats = app
    g = cats["Groceries"]
    budgets.set_limit(g, "$400")
    budgets.set_limit(cats["Dining"], "100")
    txs.add(date(2026, 9, 3), "Kroger", "150", True, g)
    txs.add(date(2026, 9, 9), "Kroger", "60.50", True, g)
    txs.add(date(2026, 9, 12), "Kroger refund", "10.50", False, g)  # refunds reduce spending
    txs.add(date(2026, 8, 30), "Kroger", "999", True, g)  # other month
    txs.add(date(2026, 9, 5), "Mystery", "50", True, None)  # uncategorized

    lines = {line.category: line for line in budgets.lines("2026-09")}
    assert set(lines) == {"Dining", "Groceries"}  # only budgeted categories
    assert lines["Groceries"].spent_cents == 20000 and lines["Groceries"].left_cents == 20000
    assert lines["Dining"].spent_cents == 0 and lines["Dining"].level == OK


def test_refund_only_month_is_zero_not_negative(app):
    budgets, txs, cats = app
    budgets.set_limit(cats["Dining"], "100")
    txs.add(date(2026, 9, 1), "Refund", "20", False, cats["Dining"])
    assert budgets.lines("2026-09")[0].spent_cents == 0


def test_set_limit_updates_and_validates(app):
    budgets, _, cats = app
    budgets.set_limit(cats["Rent"], "1500")
    budgets.set_limit(cats["Rent"], "1,600.00")  # same category: updates, doesn't duplicate
    assert [(line.category, line.limit_cents) for line in budgets.lines("2026-09")] == [("Rent", 160000)]
    for bad in ("", "abc", "0"):
        with pytest.raises(BudgetError):
            budgets.set_limit(cats["Rent"], bad)
    with pytest.raises(BudgetError):
        budgets.set_limit(None, "100")

    budgets.remove(cats["Rent"])
    assert budgets.lines("2026-09") == []


def test_deleting_category_removes_its_budget(app):
    budgets, _, cats = app
    budgets.set_limit(cats["Dining"], "100")
    CategoryService(budgets.categories).delete(cats["Dining"])
    assert budgets.lines("2026-09") == []


def test_months_include_current_month(app):
    budgets, txs, _ = app
    txs.add(date(2026, 7, 1), "x", "1", True, None)
    assert budgets.months(today=date(2026, 9, 26)) == ["2026-09", "2026-07"]
