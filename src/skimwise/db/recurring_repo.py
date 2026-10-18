import sqlite3

from skimwise.models import RecurringItem


class RecurringRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def confirmed(self) -> list[RecurringItem]:
        rows = self.conn.execute(
            "SELECT id, name, amount_cents, frequency FROM recurring_items "
            "WHERE dismissed = 0 ORDER BY name COLLATE NOCASE"
        )
        return [RecurringItem(*r) for r in rows]

    def known_merchants(self) -> set[str]:
        """Upper-cased merchant AND name of every item, confirmed or dismissed: a suggestion matching
        either isn't shown. (Matching names too means confirming one can never collide with an item
        the user renamed to that name.)"""
        rows = self.conn.execute(
            "SELECT upper(merchant) FROM recurring_items WHERE merchant IS NOT NULL "
            "UNION SELECT upper(name) FROM recurring_items"
        )
        return {r[0] for r in rows}

    def add(
        self, name: str, amount_cents: int, frequency: str, dismissed: bool = False, merchant: str | None = None
    ) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO recurring_items (name, amount_cents, frequency, dismissed, merchant) "
                "VALUES (?, ?, ?, ?, ?)",
                (name, amount_cents, frequency, dismissed, merchant),
            )

    def update(self, item_id: int, name: str, amount_cents: int, frequency: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE recurring_items SET name = ?, amount_cents = ?, frequency = ? WHERE id = ?",
                (name, amount_cents, frequency, item_id),
            )

    def dismissed_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM recurring_items WHERE dismissed = 1").fetchone()[0]

    def clear_dismissed(self) -> int:
        """Forget every "not recurring" choice. Returns how many were cleared."""
        with self.conn:
            return self.conn.execute("DELETE FROM recurring_items WHERE dismissed = 1").rowcount

    def delete(self, item_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM recurring_items WHERE id = ?", (item_id,))
