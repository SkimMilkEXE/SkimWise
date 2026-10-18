from datetime import date
from pathlib import Path

import pytest

from skimwise.db.connection import connect
from skimwise.db.profile_repo import ProfileRepository
from skimwise.db.rule_repo import RuleRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import BankProfile
from skimwise.services.csv_import import (
    DUPLICATE,
    ERROR,
    NEW,
    CsvImportError,
    ImportService,
    detect_date_format,
    guess_header_row,
    guess_profile,
    header_of,
    parse,
    read_rows,
)

FIXTURES = Path(__file__).parent / "fixtures"


def guessed(rows):
    skip = guess_header_row(rows)
    return guess_profile(header_of(rows, skip), skip)


@pytest.fixture
def service():
    conn = connect(":memory:")
    return ImportService(TransactionRepository(conn), ProfileRepository(conn), RuleRepository(conn))


def test_checking_export_with_preamble_and_messy_amounts():
    rows = read_rows(FIXTURES / "checking.csv")
    p = guessed(rows)
    assert (p.skip_rows, p.date_col, p.description_col, p.amount_col) == (4, "Posting Date", "Description", "Amount")

    parsed = parse(rows, p)
    good = [r.tx for r in parsed if r.status == NEW]
    assert [t.amount_cents for t in good] == [215000, -450, -450, -1549, -12345, -150000]
    assert good[0].date == date(2026, 8, 1)
    assert good[3].description == "NETFLIX.COM STREAMING"  # whitespace collapsed
    assert [r.status for r in parsed].count(ERROR) == 1  # the "Total" row


def test_debit_credit_export_with_day_first_dates():
    rows = read_rows(FIXTURES / "credit_union.csv")
    p = guessed(rows)
    assert (p.amount_col, p.debit_col, p.credit_col, p.description_col) == ("", "Debit", "Credit", "Details")

    txs = [r.tx for r in parse(rows, p)]
    assert [t.date for t in txs] == [date(2026, 9, 2), date(2026, 9, 5), date(2026, 9, 14)]
    assert [t.amount_cents for t in txs] == [-380, 180000, -9210]  # debit sign ignored, always an expense


def test_flip_sign():
    rows = [["Date", "Desc", "Amount"], ["2026-09-01", "Card purchase", "12.00"], ["2026-09-02", "Payment", "-50"]]
    p = BankProfile(date_col="Date", description_col="Desc", amount_col="Amount", flip_sign=True)
    assert [r.tx.amount_cents for r in parse(rows, p)] == [-1200, 5000]


def test_detect_date_format_prefers_us_when_ambiguous():
    assert detect_date_format(["01/02/2026", "03/04/2026"]) == "%m/%d/%Y"
    assert detect_date_format(["01/02/2026", "25/04/2026"]) == "%d/%m/%Y"
    assert detect_date_format(["Total", ""]) is None


def test_bad_mapping_raises():
    rows = [["Date", "Desc", "Amount"]]
    with pytest.raises(CsvImportError):
        parse(rows, BankProfile(date_col="Date", description_col="Desc"))  # no amount column
    with pytest.raises(CsvImportError):
        parse(rows, BankProfile(date_col="Date", description_col="Nope", amount_col="Amount"))


def test_read_rows_handles_bom_and_cp1252(tmp_path):
    f = tmp_path / "a.csv"
    f.write_bytes("\ufeffDate,Desc\n".encode())  # \ufeff = byte-order mark
    assert read_rows(f) == [["Date", "Desc"]]
    f.write_bytes("Date,Desc\n2026-01-01,Caf\xe9\n".encode("cp1252"))
    assert read_rows(f)[1] == ["2026-01-01", "Café"]


def test_reimport_marks_duplicates_by_count(service):
    rows = read_rows(FIXTURES / "checking.csv")
    p = guessed(rows)
    assert service.commit(service.preview(rows, p)) == 6

    again = service.preview(rows, p)
    assert [r.status for r in again].count(DUPLICATE) == 6
    assert service.commit(again) == 0

    # DB has one $4.50 coffee on 08/03; a file with it twice imports exactly one more.
    service.transactions.delete([service.transactions.list(search="starbucks")[0].id])
    statuses = [r.status for r in service.preview(rows, p) if r.tx and "STARBUCKS" in r.tx.description]
    assert sorted(statuses) == [DUPLICATE, NEW]


def test_profiles_upsert_and_match(service):
    rows = read_rows(FIXTURES / "checking.csv")
    first = service.save_profile(BankProfile(name=" Chase  Checking ", **_cols(guessed(rows))))
    assert first.name == "Chase Checking"
    second = service.save_profile(BankProfile(name="chase checking", **_cols(guessed(rows)), flip_sign=True))
    assert first.id == second.id and len(service.list_profiles()) == 1  # same name (any case) overwrites

    assert service.matching_profile(rows).id == first.id
    assert service.matching_profile(read_rows(FIXTURES / "credit_union.csv")) is None
    with pytest.raises(CsvImportError):
        service.save_profile(BankProfile(name="  "))


def _cols(p: BankProfile) -> dict:
    return dict(skip_rows=p.skip_rows, date_col=p.date_col, description_col=p.description_col, amount_col=p.amount_col)


def test_profile_without_columns_matches_nothing(service):
    service.profiles.save(BankProfile(name="Broken"))
    assert service.matching_profile(read_rows(FIXTURES / "checking.csv")) is None


def test_semicolon_file_with_decimal_commas_and_times(tmp_path):
    """A typical European export: ";" separated, day-first dates with times, decimal commas."""
    f = tmp_path / "eu.csv"
    f.write_text(
        "Datum;Omschrijving;Bedrag\n"
        "02-09-2026 08:15;Albert Heijn;-12,50\n"
        "15-09-2026 17:40;Salaris;2.450,00\n"
        "25-09-2026 09:00;Huur;-950,00\n",
        encoding="utf-8",
    )
    rows = read_rows(f)
    assert rows[0] == ["Datum", "Omschrijving", "Bedrag"]
    p = BankProfile(date_col="Datum", description_col="Omschrijving", amount_col="Bedrag")
    txs = [r.tx for r in parse(rows, p)]
    assert [(t.date, t.amount_cents) for t in txs] == [
        (date(2026, 9, 2), -1250),
        (date(2026, 9, 15), 245000),
        (date(2026, 9, 25), -95000),
    ]


def test_tab_separated_file(tmp_path):
    f = tmp_path / "tabs.tsv"
    f.write_text("Date\tDescription\tAmount\n2026-09-01\tCoffee, large\t-4.50\n", encoding="utf-8")
    assert read_rows(f) == [["Date", "Description", "Amount"], ["2026-09-01", "Coffee, large", "-4.50"]]


def test_unreadable_rows_are_reported_not_imported():
    rows = [
        ["Date", "Desc", "Debit", "Credit"],
        ["2026-09-01", "", "5", ""],  # no description
        ["2026-09-02", "Nothing", "", ""],  # neither debit nor credit
        ["2026-09-03", "Garbage", "abc", ""],  # unreadable amount
        ["2026-09-04", "Zero", "0", ""],
        ["", "", "", ""],  # blank line: skipped silently
        ["2026-09-05", "Fine", "5", ""],
    ]
    p = BankProfile(date_col="Date", description_col="Desc", debit_col="Debit", credit_col="Credit")
    parsed = parse(rows, p)
    assert [(r.row_number, r.status, r.error) for r in parsed] == [
        (2, ERROR, "Missing description"),
        (3, ERROR, "Unreadable amount"),
        (4, ERROR, "Unreadable amount"),
        (5, ERROR, "Amount is zero"),
        (7, NEW, ""),
    ]


def test_guess_header_row_on_empty_file():
    assert guess_header_row([]) == 0
    assert guess_header_row([[], [""]]) == 0
