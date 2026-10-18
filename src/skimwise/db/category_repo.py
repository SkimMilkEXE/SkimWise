from __future__ import annotations  # our list() method shadows the builtin inside the class body

import sqlite3

from skimwise.models import Category


class CategoryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list(self) -> list[Category]:
        rows = self.conn.execute("SELECT id, name FROM categories ORDER BY name COLLATE NOCASE")
        return [Category(*row) for row in rows]

    def add(self, name: str) -> Category:
        with self.conn:
            cur = self.conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        return Category(cur.lastrowid, name)

    def rename(self, category_id: int, name: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))

    def delete(self, category_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
