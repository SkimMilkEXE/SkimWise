from __future__ import annotations  # our list() method shadows the builtin inside the class body

import sqlite3
from dataclasses import replace

from skimwise.models import BankProfile

_FIELDS = ["name", "skip_rows", "date_col", "description_col", "amount_col", "debit_col", "credit_col", "flip_sign"]


class ProfileRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list(self) -> list[BankProfile]:
        rows = self.conn.execute(f"SELECT {', '.join(_FIELDS)}, id FROM bank_profiles ORDER BY name COLLATE NOCASE")
        return [BankProfile(*r[:7], flip_sign=bool(r[7]), id=r[8]) for r in rows]

    def save(self, p: BankProfile) -> BankProfile:
        """Insert, or overwrite the profile with the same name."""
        updates = ", ".join(f"{f} = excluded.{f}" for f in _FIELDS[1:])
        with self.conn:
            row = self.conn.execute(
                f"INSERT INTO bank_profiles ({', '.join(_FIELDS)}) VALUES ({', '.join('?' * len(_FIELDS))}) "
                f"ON CONFLICT(name) DO UPDATE SET {updates} RETURNING id",
                [getattr(p, f) for f in _FIELDS],
            ).fetchone()
        return replace(p, id=row[0])
