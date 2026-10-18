from __future__ import annotations  # our list() method shadows the builtin inside the class body

import sqlite3

from skimwise.models import Rule


class RuleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list(self) -> list[Rule]:
        """In priority order: the order rules are tried in."""
        rows = self.conn.execute("SELECT id, pattern, category_id, priority FROM rules ORDER BY priority, id")
        return [Rule(*r) for r in rows]

    def add(self, pattern: str, category_id: int) -> Rule:
        """New rules go last."""
        with self.conn:
            priority = self.conn.execute("SELECT COALESCE(MAX(priority), 0) + 1 FROM rules").fetchone()[0]
            cur = self.conn.execute(
                "INSERT INTO rules (pattern, category_id, priority) VALUES (?, ?, ?)", (pattern, category_id, priority)
            )
        return Rule(cur.lastrowid, pattern, category_id, priority)

    def update(self, rule_id: int, pattern: str, category_id: int) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE rules SET pattern = ?, category_id = ? WHERE id = ?", (pattern, category_id, rule_id)
            )

    def swap_priority(self, a: Rule, b: Rule) -> None:
        with self.conn:
            self.conn.execute("UPDATE rules SET priority = ? WHERE id = ?", (b.priority, a.id))
            self.conn.execute("UPDATE rules SET priority = ? WHERE id = ?", (a.priority, b.id))

    def delete(self, rule_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
