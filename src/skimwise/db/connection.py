import sqlite3
from pathlib import Path

# Each entry upgrades the schema by one version. Append new entries; never edit old ones.
# PRAGMA user_version records how many have been applied.
MIGRATIONS = [
    """
    CREATE TABLE categories (
        id   INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE
    );
    INSERT INTO categories (name) VALUES
        ('Groceries'), ('Dining'), ('Rent'), ('Utilities'),
        ('Transport'), ('Entertainment'), ('Subscriptions'), ('Income');
    """,
    """
    CREATE TABLE transactions (
        id           INTEGER PRIMARY KEY,
        date         TEXT NOT NULL,              -- YYYY-MM-DD
        description  TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,           -- negative = expense, positive = income
        category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL
    );
    CREATE INDEX idx_transactions_date ON transactions(date);
    """,
    """
    CREATE TABLE bank_profiles (
        id              INTEGER PRIMARY KEY,
        name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
        skip_rows       INTEGER NOT NULL DEFAULT 0,   -- rows above the header row
        date_col        TEXT NOT NULL,                -- columns are stored by header name
        description_col TEXT NOT NULL,
        amount_col      TEXT NOT NULL DEFAULT '',     -- '' when using debit/credit
        debit_col       TEXT NOT NULL DEFAULT '',
        credit_col      TEXT NOT NULL DEFAULT '',
        flip_sign       INTEGER NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE rules (
        id          INTEGER PRIMARY KEY,
        pattern     TEXT NOT NULL,                  -- matched case-insensitively, "contains"
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        priority    INTEGER NOT NULL                -- lower runs first; first match wins
    );
    """,
    """
    CREATE TABLE budgets (
        category_id INTEGER PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
        limit_cents INTEGER NOT NULL CHECK (limit_cents > 0)   -- per month, applies to every month
    );
    """,
    """
    CREATE TABLE recurring_items (
        id           INTEGER PRIMARY KEY,
        name         TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- detected items use the merchant name
        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
        frequency    TEXT NOT NULL CHECK (frequency IN ('monthly', 'yearly')),
        dismissed    INTEGER NOT NULL DEFAULT 0             -- 1 = "not recurring", hide from suggestions
    );
    """,
    """
    -- The detected merchant, kept separately so renaming an item doesn't make it get suggested again.
    ALTER TABLE recurring_items ADD COLUMN merchant TEXT;
    UPDATE recurring_items SET merchant = upper(name);
    """,
]


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database (":memory:" for tests) and bring its schema up to date."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = {i}; COMMIT;")
