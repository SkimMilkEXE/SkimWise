from __future__ import annotations  # our list() methods shadow the builtin inside class bodies

from dataclasses import dataclass
from datetime import date

from budget_tracker.db.transaction_repo import TransactionRepository
from budget_tracker.models import Transaction
from budget_tracker.services.money import parse_cents


class TransactionError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


class TransactionService:
    def __init__(self, repo: TransactionRepository):
        self.repo = repo

    def list(
        self, month: str | None = None, category_id: int | None = None, search: str = "", kind: str | None = None
    ) -> list[Transaction]:
        return self.repo.list(month, category_id, search.strip(), kind)

    def months(self) -> list[str]:
        return self.repo.months()

    def add(self, when: date, description: str, amount: str, is_expense: bool, category_id: int | None) -> Transaction:
        return self.repo.add(_build(None, when, description, amount, is_expense, category_id))

    def update(
        self, tx_id: int, when: date, description: str, amount: str, is_expense: bool, category_id: int | None
    ) -> None:
        self.repo.update(_build(tx_id, when, description, amount, is_expense, category_id))

    def delete(self, tx_ids: list[int]) -> None:
        self.repo.delete(tx_ids)

    def set_category(self, tx_ids: list[int], category_id: int | None) -> None:
        """Give several transactions the same category (None = uncategorized)."""
        self.repo.set_categories([(i, category_id) for i in tx_ids])


@dataclass(frozen=True)
class Totals:
    count: int
    income_cents: int  # positive
    expense_cents: int  # positive

    @property
    def net_cents(self) -> int:
        return self.income_cents - self.expense_cents


def totals(txs: list[Transaction]) -> Totals:
    return Totals(
        len(txs),
        sum(t.amount_cents for t in txs if t.amount_cents > 0),
        -sum(t.amount_cents for t in txs if t.amount_cents < 0),
    )


def _build(tx_id, when, description, amount, is_expense, category_id) -> Transaction:
    description = " ".join(description.split())
    if not description:
        raise TransactionError("Description can't be empty.")
    try:
        cents = abs(parse_cents(amount))  # the sign comes from is_expense, not the text
    except ValueError:
        raise TransactionError("Enter an amount like 12.34.") from None
    if cents == 0:
        raise TransactionError("Amount can't be zero.")
    return Transaction(tx_id, when, description, -cents if is_expense else cents, category_id)
