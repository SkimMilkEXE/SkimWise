from datetime import date

import pytest
from fpdf import FPDF

from skimwise.db.connection import connect
from skimwise.services.app_services import build_services
from skimwise.services.csv_import import DUPLICATE, NEW, CsvImportError, guess_header_row, guess_profile
from skimwise.services.pdf_import import read_statement, statement_rows

# Modelled on a typical US checking statement (M&T-style): dates without a year, a statement
# period in the header, separate deposit/withdrawal sections, and a daily balance table.
MT_STATEMENT = """\
M&T Bank
MyChoice Checking   Account number ****1234
Statement period 12/13/2025 - 01/12/2026
Beginning balance on 12/13/2025 1,500.00
DEPOSITS AND OTHER CREDITS
Date Description Amount
12/19 PAYROLL ACME CORP 1,625.00
01/02 ZELLE FROM JANE DOE 40.00
WITHDRAWALS AND OTHER DEBITS
12/15 12/14 POS DEBIT WEGMANS #12 BUFFALO NY 84.21
12/31 NETFLIX.COM 15.49
01/05 CHECK 1043 150.00
DAILY BALANCE
12/15 1,415.79 12/19 3,040.79
Ending balance on 01/12/2026 2,915.30
"""


def rows(text, today=None):
    return statement_rows(text.splitlines(), today)[1:]  # drop the header row


def make_pdf(path, text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for line in text.splitlines():
        pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))
    return path


def test_sections_set_the_sign_and_years_roll_over():
    assert rows(MT_STATEMENT) == [
        ["2025-12-19", "PAYROLL ACME CORP", "1625.00"],
        ["2026-01-02", "ZELLE FROM JANE DOE", "40.00"],
        ["2025-12-15", "POS DEBIT WEGMANS #12 BUFFALO NY", "-84.21"],  # second (effective) date dropped
        ["2025-12-31", "NETFLIX.COM", "-15.49"],  # December line on a January statement
        ["2026-01-05", "CHECK 1043", "-150.00"],
    ]  # balances, the daily balance table and the column header are all skipped


def test_running_balance_decides_the_sign_without_section_headings():
    text = """Statement Period: January 1, 2026 through January 31, 2026
Previous balance 1,000.00
01/03 COFFEE SHOP 4.50 995.50
01/05 PAYCHECK 2,000.00 2,995.50
01/09 RENT 1,450.00 1,545.50"""
    assert [r[2] for r in rows(text)] == ["-4.50", "2000.00", "-1450.00"]


def test_explicit_negatives_and_full_dates():
    text = """ACCOUNT ACTIVITY
01/03/2026 REFUND ACME 12.00
01/04/2026 CARD PURCHASE -8.25
01/05/2026 FEE (2.00)"""
    assert rows(text) == [
        ["2026-01-03", "REFUND ACME", "-12.00"],  # no heading or balance says otherwise: money out
        ["2026-01-04", "CARD PURCHASE", "-8.25"],
        ["2026-01-05", "FEE", "-2.00"],
    ]


def test_without_a_statement_date_the_year_comes_from_today():
    text = "WITHDRAWALS\n11/20 GROCERY 50.00\n02/01 GAS 30.00"
    assert [r[0] for r in rows(text, today=date(2026, 3, 1))] == ["2025-11-20", "2026-02-01"]


def test_real_pdf_goes_through_the_normal_import(tmp_path):
    pdf = make_pdf(tmp_path / "statement.pdf", MT_STATEMENT)
    table = read_statement(pdf)
    assert table[0] == ["Date", "Description", "Amount"] and len(table) == 6

    services = build_services(connect(":memory:"))
    profile = guess_profile(table[guess_header_row(table)], guess_header_row(table))
    preview = services.importer.preview(table, profile)
    assert [r.status for r in preview] == [NEW] * 5
    services.importer.commit(preview)
    assert [r.status for r in services.importer.preview(table, profile)] == [DUPLICATE] * 5  # re-import is safe


def test_unreadable_pdfs_give_clear_errors(tmp_path):
    blank = FPDF()
    blank.add_page()  # a page with no text, like a scanned image
    blank.output(str(tmp_path / "scan.pdf"))
    with pytest.raises(CsvImportError, match="scanned"):
        read_statement(tmp_path / "scan.pdf")

    (tmp_path / "fake.pdf").write_text("not really a pdf")
    with pytest.raises(CsvImportError, match="Couldn't read"):
        read_statement(tmp_path / "fake.pdf")

    make_pdf(tmp_path / "letter.pdf", "Dear customer,\nThank you for banking with us.")
    with pytest.raises(CsvImportError, match="No transactions found"):
        read_statement(tmp_path / "letter.pdf")


def test_mt_checking_with_serial_numbers_and_two_balance_columns():
    # M&T "Account Activity": amount, then daily balance (sometimes blank) and ledger balance
    text = """Account Activity
Serial Deposits & Checks & Daily Ledger
Posting Date Transaction Description Number Other Credits (+) Other Debits (-) Balance Balance
08/26/2026 Beginning Balance $920.29
08/28/2026 OCEAN STATE JOB PAYROLL $309.13 $1,229.42 1,229.42
09/04/2026 OCEAN STATE JOB PAYROLL 297.88 1,527.30 1,527.30
09/08/2026 WEB XFER TO SAV 15005171137805 250222115 $300.00 1,227.30 1,227.30
09/18/2026 WEB PMT TO 4170958501573781 261333115 720.51 421.00
09/18/2026 OCEAN STATE JOB PAYROLL 401.27 822.27 822.27
Ending Balance: $975.96"""
    assert rows(text) == [
        ["2026-08-28", "OCEAN STATE JOB PAYROLL", "309.13"],
        ["2026-09-04", "OCEAN STATE JOB PAYROLL", "297.88"],
        ["2026-09-08", "WEB XFER TO SAV 15005171137805 250222115", "-300.00"],
        ["2026-09-18", "WEB PMT TO 4170958501573781 261333115", "-720.51"],
        ["2026-09-18", "OCEAN STATE JOB PAYROLL", "401.27"],
    ]


def test_one_cell_per_line_text_is_joined_back_into_rows():
    # How pypdf reads M&T's table: every cell on its own line, sometimes with "$" split off
    cells = [
        "Checks",
        "Other Debits",
        "08/26/2026",
        "Beginning Balance",
        "$100.00",
        "08/28/2026",
        "PAYROLL",
        "$50.00",
        "$",
        "150.00",
        "150.00",
        "09/08/2026",
        "WEB PMT TO 4170958501573781",
        "261333115",
        "20.00",
        "130.00",
        "-",
        "Ending Balance:",
        "$130.00",
        "M&T PREMIUM SAVINGS",
        "09/08/2026",
        "WEB XFER FROM CHK",
        "20.00",
        "520.00",
    ]  # 2nd account: ignored
    assert rows("\n".join(cells)) == [
        ["2026-08-28", "PAYROLL", "50.00"],
        ["2026-09-08", "WEB PMT TO 4170958501573781 261333115", "-20.00"],
    ]
