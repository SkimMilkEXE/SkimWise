from __future__ import annotations  # our list() methods shadow the builtin inside class bodies

import sqlite3
from dataclasses import replace
from datetime import date

from budget_tracker.models import EXPENSE, INCOME, NO_CATEGORY, Transaction

_COLUMNS = "id, date, description, amount_cents, category_id"


def _row(row) -> Transaction:
    id_, iso, description, cents, category_id = row
    return Transaction(id_, date.fromisoformat(iso), description, cents, category_id)


class TransactionRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list(
        self, month: str | None = None, category_id: int | None = None, search: str = "", kind: str | None = None
    ) -> list[Transaction]:
        """month is "YYYY-MM"; None/empty arguments mean "don't filter on this"."""
        where, params = [], []
        if kind == INCOME:
            where.append("amount_cents > 0")
        elif kind == EXPENSE:
            where.append("amount_cents < 0")
        if month:
            where.append("substr(date, 1, 7) = ?")
            params.append(month)
        if category_id == NO_CATEGORY:
            where.append("category_id IS NULL")
        elif category_id is not None:
            where.append("category_id = ?")
            params.append(category_id)
        if search:
            where.append("instr(lower(description), lower(?)) > 0")
            params.append(search)
        sql = f"SELECT {_COLUMNS} FROM transactions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY date DESC, id DESC"
        return [_row(r) for r in self.conn.execute(sql, params)]

    def months(self) -> list[str]:
        """Every "YYYY-MM" that has at least one transaction, newest first."""
        rows = self.conn.execute("SELECT DISTINCT substr(date, 1, 7) FROM transactions ORDER BY 1 DESC")
        return [r[0] for r in rows]

    def spending_by_category(self, month: str) -> dict[int, int]:
        """category id -> net spending in cents for "YYYY-MM" (expenses minus refunds)."""
        rows = self.conn.execute(
            "SELECT category_id, -SUM(amount_cents) FROM transactions "
            "WHERE substr(date, 1, 7) = ? AND category_id IS NOT NULL GROUP BY category_id",
            (month,),
        )
        return dict(rows)

    def expenses_by_category(self, month: str) -> dict[int | None, int]:
        """category id (None = uncategorized) -> total expenses in cents for "YYYY-MM".
        Expenses only: income and refunds don't offset it."""
        rows = self.conn.execute(
            "SELECT category_id, -SUM(amount_cents) FROM transactions "
            "WHERE substr(date, 1, 7) = ? AND amount_cents < 0 GROUP BY category_id",
            (month,),
        )
        return dict(rows)

    def monthly_totals(self, first: str, last: str) -> dict[str, tuple[int, int]]:
        """ "YYYY-MM" -> (income, expenses) in cents, both positive, for months in [first, last]
        that have transactions."""
        rows = self.conn.execute(
            "SELECT substr(date, 1, 7) AS m, "
            "SUM(CASE WHEN amount_cents > 0 THEN amount_cents ELSE 0 END), "
            "SUM(CASE WHEN amount_cents < 0 THEN -amount_cents ELSE 0 END) "
            "FROM transactions WHERE m BETWEEN ? AND ? GROUP BY m",
            (first, last),
        )
        return {m: (income, expenses) for m, income, expenses in rows}

    def add(self, tx: Transaction) -> Transaction:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO transactions (date, description, amount_cents, category_id) VALUES (?, ?, ?, ?)",
                (tx.date.isoformat(), tx.description, tx.amount_cents, tx.category_id),
            )
        return replace(tx, id=cur.lastrowid)

    def add_many(self, txs: list[Transaction]) -> None:
        with self.conn:  # one database transaction: all rows are saved, or none
            self.conn.executemany(
                "INSERT INTO transactions (date, description, amount_cents, category_id) VALUES (?, ?, ?, ?)",
                [(t.date.isoformat(), t.description, t.amount_cents, t.category_id) for t in txs],
            )

    def keys_between(self, start: date, end: date) -> list[tuple[date, str, int]]:
        """(date, description, amount_cents) of every transaction in [start, end], for duplicate checks."""
        rows = self.conn.execute(
            "SELECT date, description, amount_cents FROM transactions WHERE date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        )
        return [(date.fromisoformat(d), desc, cents) for d, desc, cents in rows]

    def update(self, tx: Transaction) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE transactions SET date = ?, description = ?, amount_cents = ?, category_id = ? WHERE id = ?",
                (tx.date.isoformat(), tx.description, tx.amount_cents, tx.category_id, tx.id),
            )

    def set_categories(self, changes: list[tuple[int, int | None]]) -> None:
        """Apply (transaction id, category id) pairs in one database transaction."""
        with self.conn:
            self.conn.executemany("UPDATE transactions SET category_id = ? WHERE id = ?", [(c, t) for t, c in changes])

    def delete(self, tx_ids: list[int]) -> None:
        with self.conn:  # one database transaction: all are deleted, or none
            self.conn.executemany("DELETE FROM transactions WHERE id = ?", [(i,) for i in tx_ids])
