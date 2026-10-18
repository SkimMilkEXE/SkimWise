from __future__ import annotations  # our list() method shadows the builtin inside the class body

import sqlite3

from skimwise.db.category_repo import CategoryRepository
from skimwise.models import Category


class CategoryError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


class CategoryService:
    def __init__(self, repo: CategoryRepository):
        self.repo = repo

    def list(self) -> list[Category]:
        return self.repo.list()

    def add(self, name: str) -> Category:
        name = _clean(name)
        try:
            return self.repo.add(name)
        except sqlite3.IntegrityError:
            raise CategoryError(f'A category named "{name}" already exists.') from None

    def rename(self, category_id: int, name: str) -> None:
        name = _clean(name)
        try:
            self.repo.rename(category_id, name)
        except sqlite3.IntegrityError:
            raise CategoryError(f'A category named "{name}" already exists.') from None

    def delete(self, category_id: int) -> None:
        self.repo.delete(category_id)


def _clean(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise CategoryError("Category name can't be empty.")
    return name
