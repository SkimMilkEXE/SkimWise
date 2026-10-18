from datetime import date

import pytest

from skimwise.db.category_repo import CategoryRepository
from skimwise.db.connection import connect
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import NO_CATEGORY
from skimwise.services.categories import CategoryService
from skimwise.services.money import format_cents, parse_cents
from skimwise.services.transactions import TransactionError, TransactionService


@pytest.mark.parametrize(
    "text, cents",
    [
        ("12.5", 1250),
        ("$1,234.56", 123456),
        ("-3", -300),
        ("(5.00)", -500),
        (" 0.01 ", 1),
        ("1,234", 123400),  # US thousands separator, not a decimal
        ("12,50", 1250),  # decimal comma (European)
        ("-4,5", -450),
        ("1.234,56", 123456),  # European thousands + decimal comma
        ("€12,50", 1250),
        ("£8", 800),
        ("5.00-", -500),  # trailing minus
        ("5.00 DR", -500),  # debit
        ("5.00CR", 500),  # credit
        ("1 234,56", 123456),  # space as thousands separator
        ("-5.00 DR", -500),  # two negative markers still mean negative, never positive
        ("(-5.00)", -500),
        ("12,345,678.90", 1234567890),
    ],
)
def test_parse_cents(text, cents):
    assert parse_cents(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "1.234", "nan", "inf", "$", "1,2,3", "12,34,5", "1,23,4.00"])
def test_parse_cents_rejects(text):
    with pytest.raises(ValueError):
        parse_cents(text)


def test_format_cents():
    assert format_cents(1234) == "$12.34"
    assert format_cents(-123456) == "-$1,234.56"
    assert format_cents(5) == "$0.05"
    assert parse_cents(format_cents(-123456)[1:]) == 123456  # formatted text parses back


@pytest.fixture
def db():
    conn = connect(":memory:")
    return TransactionService(TransactionRepository(conn)), CategoryService(CategoryRepository(conn))


def test_add_sets_sign_from_kind_and_filters(db):
    txs, cats = db
    groceries = next(c for c in cats.list() if c.name == "Groceries")
    txs.add(date(2026, 8, 3), "Kroger", "-45.10", True, groceries.id)  # sign in text is ignored
    txs.add(date(2026, 9, 1), "Paycheck", "2,000", False, None)
    txs.add(date(2026, 9, 5), "KROGER #12", "30", True, groceries.id)

    assert [t.amount_cents for t in txs.list()] == [-3000, 200000, -4510]  # newest first
    assert [t.description for t in txs.list(month="2026-09")] == ["KROGER #12", "Paycheck"]
    assert len(txs.list(category_id=groceries.id)) == 2
    assert len(txs.list(search=" kroger ")) == 2  # case-insensitive, trimmed
    assert len(txs.list(month="2026-09", category_id=groceries.id, search="kroger")) == 1
    assert txs.months() == ["2026-09", "2026-08"]


def test_update_delete_and_category_delete_uncategorizes(db):
    txs, cats = db
    pets = cats.add("Pets")
    tx = txs.add(date(2026, 9, 1), "Vet", "80", True, pets.id)
    txs.update(tx.id, date(2026, 9, 2), "Vet visit", "90", True, pets.id)
    assert txs.list()[0].description == "Vet visit" and txs.list()[0].amount_cents == -9000

    cats.delete(pets.id)
    assert txs.list()[0].category_id is None  # ON DELETE SET NULL (needs foreign_keys ON)

    txs.delete([tx.id])
    assert txs.list() == []


@pytest.mark.parametrize("description, amount", [("  ", "5"), ("Coffee", "abc"), ("Coffee", "0")])
def test_rejects_invalid(db, description, amount):
    with pytest.raises(TransactionError):
        db[0].add(date(2026, 9, 1), description, amount, True, None)


def test_filter_uncategorized(db):
    txs, cats = db
    txs.add(date(2026, 9, 1), "Mystery", "5", True, None)
    txs.add(date(2026, 9, 1), "Known", "5", True, cats.list()[0].id)
    assert [t.description for t in txs.list(category_id=NO_CATEGORY)] == ["Mystery"]
