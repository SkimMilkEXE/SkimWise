"""Find recurring charges (subscriptions, bills) in transaction history, and manage confirmed ones."""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import pairwise
from statistics import median

from skimwise.db.recurring_repo import RecurringRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import MONTHLY, YEARLY, RecurringItem, Transaction
from skimwise.services.money import parse_cents
from skimwise.services.rules import suggest_pattern

# frequency -> (shortest gap, longest gap in days, fewest charges needed, "still active" window in days)
FREQUENCIES = {
    MONTHLY: (25, 35, 3, 45),
    YEARLY: (350, 380, 2, 400),
}
AMOUNT_TOLERANCE = 0.20  # every charge within 20% of the typical one (allows a price increase)


class RecurringError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


@dataclass(frozen=True)
class Candidate:
    """A merchant that looks recurring, waiting for the user to confirm or dismiss it."""

    name: str
    amount_cents: int  # the latest charge, positive
    frequency: str
    count: int  # charges seen
    last_date: date


def merchant(description: str) -> str:
    """Group key for a description: "NETFLIX.COM" stays, "SPOTIFY #88 NY" -> "SPOTIFY"."""
    return suggest_pattern(description).upper()


def detect(transactions: list[Transaction]) -> list[Candidate]:
    """Merchants charged at a steady monthly or yearly interval for a similar amount.
    "Still active" is judged against the newest transaction, not today, so old imports still work."""
    by_merchant: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        if tx.amount_cents < 0:
            by_merchant[merchant(tx.description)].append(tx)
    if not by_merchant:
        return []
    newest = max(tx.date for tx in transactions)

    found = []
    for name, txs in by_merchant.items():
        txs.sort(key=lambda t: t.date)
        gaps = [(b.date - a.date).days for a, b in pairwise(txs)]
        amounts = [-t.amount_cents for t in txs]
        typical = median(amounts)
        if any(abs(a - typical) > typical * AMOUNT_TOLERANCE for a in amounts):
            continue
        for frequency, (shortest, longest, fewest, active_days) in FREQUENCIES.items():
            if (
                len(txs) >= fewest
                and all(shortest <= g <= longest for g in gaps)
                and newest - txs[-1].date <= timedelta(days=active_days)
            ):
                found.append(Candidate(name, amounts[-1], frequency, len(txs), txs[-1].date))
                break
    return sorted(found, key=lambda c: c.name)


def totals(items: list[RecurringItem]) -> tuple[int, int]:
    """(per month, per year) in cents. A yearly charge counts as 1/12 per month."""
    yearly = sum(i.yearly_cents for i in items)
    return round(yearly / 12), yearly


class RecurringService:
    def __init__(self, recurring: RecurringRepository, transactions: TransactionRepository):
        self.recurring = recurring
        self.transactions = transactions

    def items(self) -> list[RecurringItem]:
        return self.recurring.confirmed()

    def suggestions(self) -> list[Candidate]:
        """Detected candidates the user hasn't already confirmed, added, or dismissed."""
        known = self.recurring.known_merchants()
        return [c for c in detect(self.transactions.list()) if c.name.upper() not in known]

    def confirm(self, c: Candidate) -> None:
        self.recurring.add(c.name, c.amount_cents, c.frequency, merchant=c.name)

    def dismiss(self, c: Candidate) -> None:
        self.recurring.add(c.name, c.amount_cents, c.frequency, dismissed=True, merchant=c.name)

    def dismissed_count(self) -> int:
        return self.recurring.dismissed_count()

    def redetect(self) -> int:
        """Undo every "Not recurring" so those merchants can be suggested again (if they still look
        recurring). Confirmed items are kept. Returns how many dismissals were cleared."""
        return self.recurring.clear_dismissed()

    def add(self, name: str, amount: str, frequency: str) -> None:
        self._save(None, name, amount, frequency)

    def update(self, item_id: int, name: str, amount: str, frequency: str) -> None:
        self._save(item_id, name, amount, frequency)

    def remove(self, item_id: int) -> None:
        self.recurring.delete(item_id)

    def _save(self, item_id: int | None, name: str, amount: str, frequency: str) -> None:
        name = " ".join(name.split())
        if not name:
            raise RecurringError("Enter a name.")
        try:
            cents = abs(parse_cents(amount))
        except ValueError:
            raise RecurringError("Enter an amount like 15.49.") from None
        if cents == 0:
            raise RecurringError("The amount must be more than zero.")
        if frequency not in FREQUENCIES:
            raise RecurringError("Choose monthly or yearly.")
        try:
            if item_id is None:
                self.recurring.add(name, cents, frequency)
            else:
                self.recurring.update(item_id, name, cents, frequency)
        except sqlite3.IntegrityError:
            raise RecurringError(f'"{name}" is already in your list (or was dismissed).') from None
