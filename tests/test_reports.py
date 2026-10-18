from datetime import date

import pytest

from skimwise.db.category_repo import CategoryRepository
from skimwise.db.connection import connect
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.services.reports import UNCATEGORIZED, ReportService, months_ending
from skimwise.services.transactions import TransactionService


@pytest.fixture
def app():
    conn = connect(":memory:")
    tx_repo, cat_repo = TransactionRepository(conn), CategoryRepository(conn)
    cats = {c.name: c.id for c in cat_repo.list()}
    return ReportService(tx_repo, cat_repo), TransactionService(tx_repo), cats


def test_months_ending_crosses_years():
    assert months_ending("2026-02", 4) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert months_ending("2026-09", 1) == ["2026-09"]


def test_spending_by_category_is_expenses_only_largest_first(app):
    reports, txs, cats = app
    txs.add(date(2026, 9, 1), "Rent", "1500", True, cats["Rent"])
    txs.add(date(2026, 9, 2), "Kroger", "80", True, cats["Groceries"])
    txs.add(date(2026, 9, 3), "Kroger", "20", True, cats["Groceries"])
    txs.add(date(2026, 9, 4), "Kroger refund", "10", False, cats["Groceries"])  # income doesn't offset
    txs.add(date(2026, 9, 5), "Mystery", "40", True, None)
    txs.add(date(2026, 9, 6), "Paycheck", "3000", False, cats["Income"])
    txs.add(date(2026, 8, 1), "Rent", "1500", True, cats["Rent"])  # other month

    assert reports.spending_by_category("2026-09") == [("Rent", 150000), ("Groceries", 10000), (UNCATEGORIZED, 4000)]
    assert reports.spending_by_category("2026-07") == []


def test_monthly_totals_fill_gaps_but_drop_leading_empty_months(app):
    reports, txs, _ = app
    txs.add(date(2026, 6, 1), "Paycheck", "3000", False, None)
    txs.add(date(2026, 6, 2), "Rent", "1500", True, None)
    txs.add(date(2026, 8, 2), "Rent", "1500", True, None)  # July has nothing

    rows = reports.monthly_totals("2026-09", 12)
    assert [(t.month, t.income_cents, t.expense_cents) for t in rows] == [
        ("2026-06", 300000, 150000),
        ("2026-07", 0, 0),  # a real gap stays, as zero
        ("2026-08", 0, 150000),
        ("2026-09", 0, 0),
    ]


def test_monthly_totals_with_no_data_is_just_the_last_month(app):
    reports, _, _ = app
    assert [t.month for t in reports.monthly_totals("2026-09", 12)] == ["2026-09"]
