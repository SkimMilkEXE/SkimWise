import sqlite3


class BudgetRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def limits(self) -> dict[int, int]:
        """category id -> monthly limit in cents."""
        return dict(self.conn.execute("SELECT category_id, limit_cents FROM budgets"))

    def set(self, category_id: int, limit_cents: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO budgets (category_id, limit_cents) VALUES (?, ?) "
                "ON CONFLICT(category_id) DO UPDATE SET limit_cents = excluded.limit_cents",
                (category_id, limit_cents),
            )

    def delete(self, category_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM budgets WHERE category_id = ?", (category_id,))
