"""Read transactions out of a PDF bank statement (text-based PDFs, e.g. M&T checking statements).

The statement becomes the same rows a CSV would give (Date, Description, Amount), so the normal
import preview, duplicate detection and rules all apply. It's best effort: statements vary by bank,
so the user always checks the preview before importing.
"""

import re
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from skimwise.services.csv_import import CsvImportError
from skimwise.services.money import parse_cents

HEADER = ["Date", "Description", "Amount"]

_AMOUNT = r"-?\$?\(?-?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?"  # always with cents: "1,234.56", "(5.00)", "5.00-"
# Date, description, then the amount and up to two balances (M&T: daily balance and ledger balance)
_TX_LINE = re.compile(rf"^(\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?)\s+(.+?)\s+({_AMOUNT}(?:\s+{_AMOUNT}){{0,2}})\s*$")
_START_BALANCE = re.compile(rf"(beginning|previous|opening|starting) balance.*?({_AMOUNT})\s*$", re.IGNORECASE)
_FULL_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")
_LONG_DATE = re.compile(r"\b([A-Z][a-z]+)\.? (\d{1,2}),? (\d{4})\b")  # "January 31, 2026", "Jan 31, 2026"
_SECOND_DATE = re.compile(r"^\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+")  # posted + effective dates: keep the first

# Section headings say whether the amounts below them are money in or money out.
_CREDIT_WORDS = ("deposit", "credit", "addition", "interest paid")
_DEBIT_WORDS = ("withdrawal", "debit", "check", "fee", "purchase", "payment", "subtraction", "charge")
_SKIP_WORDS = ("balance",)  # "Daily balance" tables list dates and amounts that aren't transactions


def read_statement(path: Path | str) -> list[list[str]]:
    """Rows for the import dialog: a header, then one row per transaction found."""
    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, OSError, ValueError) as e:
        raise CsvImportError(f"Couldn't read that PDF ({e}).") from None
    if not text.strip():
        raise CsvImportError(
            "This PDF has no readable text; it's probably a scanned image. Download the statement from "
            "your bank's website instead, or export a CSV."
        )
    rows = statement_rows(text.splitlines())
    if len(rows) == 1:
        raise CsvImportError("No transactions found in this PDF. Try your bank's CSV export instead.")
    return rows


def statement_rows(lines: list[str], today: date | None = None) -> list[list[str]]:
    """Find transaction lines ("01/05  COFFEE SHOP  4.50  1,234.56") in a statement's text."""
    lines = _join_cells(lines)
    end = _statement_end(lines) or today or date.today()
    rows = [HEADER]
    sign = -1  # until a section heading says otherwise, assume money out (the usual case)
    skipping = False
    balance: int | None = None

    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            continue
        if len(rows) > 1 and line.lower().startswith("ending balance"):
            break  # end of the first account; statements that bundle savings too list it after
        if m := _START_BALANCE.search(line):
            balance = parse_cents(m.group(2))
            continue
        m = _TX_LINE.match(line)
        if not m:
            heading = line.lower()
            if not re.search(r"\d", heading):  # headings have no numbers; wrapped text rarely lacks them all
                credit = any(w in heading for w in _CREDIT_WORDS)
                debit = any(w in heading for w in _DEBIT_WORDS)
                if credit != debit:
                    sign, skipping = (1 if credit else -1), False
                elif not credit and any(w in heading for w in _SKIP_WORDS):  # not a column header
                    skipping = True
            continue
        if skipping:
            continue
        when_text, description, amounts = m.groups()
        amounts = amounts.split()
        amount_text, balance_text = amounts[0], (amounts[-1] if len(amounts) > 1 else None)
        description = _SECOND_DATE.sub("", description)
        if not re.search(r"[A-Za-z]", description) or "balance" in description.lower():
            continue  # a daily-balance entry or a summary line, not a transaction
        when = _date(when_text, end)
        if when is None:
            continue

        amount = parse_cents(amount_text)
        new_balance = parse_cents(balance_text) if balance_text else None
        if amount < 0:  # an explicit minus / parentheses is the strongest signal
            signed = amount
        elif balance is not None and new_balance is not None and abs(new_balance - balance) == amount:
            signed = new_balance - balance  # the running balance shows which way it moved
        else:
            signed = sign * amount
        if new_balance is not None:
            balance = new_balance
        if signed:
            rows.append([when.isoformat(), description, _plain(signed)])
    return rows


def _join_cells(lines: list[str]) -> list[str]:
    """Some PDFs come out one table cell per line: "09/04/2026", "PAYROLL", "297.88", ...
    Glue a lone date and the cells after it back into one row, ending the row at the first
    non-amount cell after its amounts."""
    out: list[str] = []
    row: list[str] | None = None
    for raw in lines:
        line = " ".join(raw.split())
        is_amount = line == "$" or re.fullmatch(_AMOUNT, line) is not None
        if re.fullmatch(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?", line):
            if row:
                out.append(" ".join(row))
            row = [line]
        elif row is not None and (is_amount or not any(re.fullmatch(_AMOUNT, c) for c in row)):
            row.append(line)
        else:
            if row:
                out.append(" ".join(row))
                row = None
            out.append(raw)
    if row:
        out.append(" ".join(row))
    return [line.replace("$ ", "$") for line in out]  # a "$" cell split from its amount


def _statement_end(lines: list[str]) -> date | None:
    """The last day the statement covers: the latest full date in its first lines (the header)."""
    found = []
    for line in lines[:60]:
        for month, day, year in _FULL_DATE.findall(line):
            try:
                found.append(date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day)))
            except ValueError:
                pass
        for words in _LONG_DATE.findall(line):
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    found.append(datetime.strptime(" ".join(words), fmt).date())
                except ValueError:
                    pass
    return max(found) if found else None


def _date(text: str, end: date) -> date | None:
    """ "01/05" -> a date, taking the year from the statement: a December line on a January
    statement belongs to the previous year."""
    parts = [int(p) for p in text.split("/")]
    try:
        if len(parts) == 3:
            year = parts[2] + (2000 if parts[2] < 100 else 0)
            return date(year, parts[0], parts[1])
        year = end.year - (1 if parts[0] > end.month else 0)
        return date(year, parts[0], parts[1])
    except ValueError:
        return None


def _plain(cents: int) -> str:
    """-1234 -> "-12.34": plain text the normal amount parser reads back exactly."""
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02}"
