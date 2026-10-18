from dataclasses import dataclass
from datetime import date

from skimwise.db.category_repo import CategoryRepository
from skimwise.db.transaction_repo import TransactionRepository

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class MonthTotals:
    month: str  # "YYYY-MM"
    income_cents: int
    expense_cents: int


def picker_months(transactions: TransactionRepository, today: date | None = None) -> list[str]:
    """Months to offer in a month picker, newest first: every month with transactions, plus this one."""
    current = (today or date.today()).strftime("%Y-%m")
    return sorted(set(transactions.months()) | {current}, reverse=True)


def months_ending(last: str, count: int) -> list[str]:
    """The `count` consecutive months ending at `last`, oldest first. ("2026-02", 3) -> Dec, Jan, Feb."""
    year, month = map(int, last.split("-"))
    index = year * 12 + month - 1  # months since year 0, so stepping back crosses years cleanly
    return [f"{i // 12:04d}-{i % 12 + 1:02d}" for i in range(index - count + 1, index + 1)]


class ReportService:
    def __init__(self, transactions: TransactionRepository, categories: CategoryRepository):
        self.transactions = transactions
        self.categories = categories

    def months(self, today: date | None = None) -> list[str]:
        return picker_months(self.transactions, today)

    def spending_by_category(self, month: str) -> list[tuple[str, int]]:
        """(category name, expenses in cents) for the month, largest first."""
        names = {c.id: c.name for c in self.categories.list()}
        totals = self.transactions.expenses_by_category(month)
        rows = [(names.get(cat_id, UNCATEGORIZED), cents) for cat_id, cents in totals.items()]
        return sorted(rows, key=lambda r: (-r[1], r[0]))

    def monthly_totals(self, last: str, count: int = 12) -> list[MonthTotals]:
        """Income and expenses for up to `count` months ending at `last`, oldest first.
        Empty months between others are included as zeros, so a chart's time axis has no silent
        gaps; empty months before the first transaction are dropped (they're "no data", not $0)."""
        months = months_ending(last, count)
        totals = self.transactions.monthly_totals(months[0], months[-1])
        rows = [MonthTotals(m, *totals.get(m, (0, 0))) for m in months]
        first = next((i for i, t in enumerate(rows) if t.income_cents or t.expense_cents), len(rows) - 1)
        return rows[first:]
