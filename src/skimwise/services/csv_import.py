"""Read bank CSV exports, map their columns, and detect already-imported rows."""

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

from skimwise.db.profile_repo import ProfileRepository
from skimwise.db.rule_repo import RuleRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import BankProfile, Transaction
from skimwise.services.money import parse_cents
from skimwise.services.rules import match

NEW, DUPLICATE, ERROR = "new", "duplicate", "error"

# Tried in order; on a tie the earlier one wins, so US month-first beats day-first.
DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d",
    "%m-%d-%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y%m%d", "%b %d, %Y", "%d %b %Y",
]  # fmt: skip


class CsvImportError(ValueError):
    """The file or mapping can't be used at all; the message is safe to show in the UI."""


@dataclass
class ParsedRow:
    row_number: int  # 1-based, counting every row in the file
    tx: Transaction | None
    status: str  # NEW, DUPLICATE or ERROR
    error: str = ""


def read_rows(path: Path | str) -> list[list[str]]:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")  # -sig strips the byte-order mark Excel adds
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")  # older Windows exports
    try:
        # European banks often use ";" (because "," is their decimal point); some use tabs.
        # Only the delimiter is taken from the sniffer: its quote-character guess can be fooled
        # by apostrophes in descriptions ("TRADER JOE'S"), and bank exports always quote with ".
        delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","  # can't tell (e.g. a one-column file): assume commas
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))


def guess_header_row(rows: list[list[str]]) -> int:
    """Index of the header row: the first row that is as wide as most rows and has no blank cells.
    Skips bank preambles like "Account: ...", "Balance: ...", blank lines."""
    widths = Counter(len(r) for r in rows if any(c.strip() for c in r))
    if not widths:
        return 0
    width = widths.most_common(1)[0][0]
    return next((i for i, r in enumerate(rows) if len(r) == width and all(c.strip() for c in r)), 0)


def guess_profile(header: list[str], skip_rows: int) -> BankProfile:
    def find(*words):
        return next((h for h in header if any(w in h.lower() for w in words)), "")

    amount = find("amount")
    return BankProfile(
        skip_rows=skip_rows,
        date_col=find("date"),
        description_col=find("desc", "memo", "payee", "merchant", "details", "name"),
        amount_col=amount,
        debit_col="" if amount else find("debit", "withdraw"),
        credit_col="" if amount else find("credit", "deposit"),
    )


def header_of(rows: list[list[str]], skip_rows: int) -> list[str]:
    return [h.strip() for h in rows[skip_rows]] if skip_rows < len(rows) else []


def detect_date_format(values: list[str]) -> str | None:
    """The format that parses the most values (junk rows like "Total" just don't count)."""
    best, best_count = None, 0
    for fmt in DATE_FORMATS:
        count = sum(1 for v in values if _parse_date(v, fmt))
        if count > best_count:
            best, best_count = fmt, count
    return best


def parse(rows: list[list[str]], p: BankProfile) -> list[ParsedRow]:
    header = header_of(rows, p.skip_rows)
    needed = [p.date_col, p.description_col] + ([p.amount_col] if p.amount_col else [p.debit_col, p.credit_col])
    if not all(needed):
        raise CsvImportError("Choose a column for date, description, and amount.")
    if missing := [c for c in needed if c not in header]:
        raise CsvImportError(f"Column not found: {', '.join(missing)}")
    index = {name: i for i, name in reversed(list(enumerate(header)))}  # first match wins on duplicate names

    def cell(row, name):
        i = index[name]
        return row[i].strip() if i < len(row) else ""

    data = rows[p.skip_rows + 1 :]
    fmt = detect_date_format([cell(r, p.date_col) for r in data])
    result = []
    for n, row in enumerate(data, start=p.skip_rows + 2):
        if not any(c.strip() for c in row):
            continue  # blank lines aren't worth reporting
        try:
            tx = _parse_row(row, p, cell, fmt)
            result.append(ParsedRow(n, tx, NEW))
        except ValueError as e:
            result.append(ParsedRow(n, None, ERROR, str(e)))
    return result


def mark_duplicates(parsed: list[ParsedRow], existing: list[tuple[date, str, int]]) -> None:
    """Mark rows matching an existing transaction on (date, description, amount).
    Counts, not a set: if the DB has one $4.50 coffee on a day and the file has two,
    only one is a duplicate, so re-importing overlapping statements is safe."""
    remaining = Counter(existing)
    for r in parsed:
        if r.tx:
            key = (r.tx.date, r.tx.description, r.tx.amount_cents)
            if remaining[key] > 0:
                remaining[key] -= 1
                r.status = DUPLICATE


class ImportService:
    def __init__(self, transactions: TransactionRepository, profiles: ProfileRepository, rules: RuleRepository):
        self.transactions = transactions
        self.rules = rules
        self.profiles = profiles

    def preview(self, rows: list[list[str]], profile: BankProfile) -> list[ParsedRow]:
        parsed = parse(rows, profile)
        rules = self.rules.list()
        for r in parsed:
            if r.tx:
                r.tx = replace(r.tx, category_id=match(rules, r.tx.description))
        dates = [r.tx.date for r in parsed if r.tx]
        if dates:
            mark_duplicates(parsed, self.transactions.keys_between(min(dates), max(dates)))
        return parsed

    def commit(self, parsed: list[ParsedRow]) -> int:
        new = [r.tx for r in parsed if r.status == NEW]
        self.transactions.add_many(new)
        return len(new)

    def list_profiles(self) -> list[BankProfile]:
        return self.profiles.list()

    def matching_profile(self, rows: list[list[str]]) -> BankProfile | None:
        """The first saved profile whose columns all exist in this file, for one-click repeat imports."""
        for p in self.profiles.list():
            header = header_of(rows, p.skip_rows)
            cols = [p.date_col, p.description_col, p.amount_col, p.debit_col, p.credit_col]
            if p.date_col and p.description_col and all(c in header for c in cols if c):
                return p
        return None

    def save_profile(self, profile: BankProfile) -> BankProfile:
        name = " ".join(profile.name.split())
        if not name:
            raise CsvImportError("Profile name can't be empty.")
        return self.profiles.save(replace(profile, name=name))


_TIME_SUFFIX = re.compile(r"[ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?\s*([AaPp][Mm])?(Z|[+-]\d{2}:?\d{2})?$")


def _parse_date(value: str, fmt: str) -> date | None:
    try:
        # Some exports add a time ("2026-08-01 14:32:00", "8/1/2026 2:32 PM"); only the date matters.
        return datetime.strptime(_TIME_SUFFIX.sub("", value.strip()), fmt).date()
    except ValueError:
        return None


def _parse_row(row, p: BankProfile, cell, fmt) -> Transaction:
    raw_date = cell(row, p.date_col)
    when = _parse_date(raw_date, fmt) if fmt else None
    if not when:
        raise ValueError(f"Unreadable date: {raw_date!r}")

    description = " ".join(cell(row, p.description_col).split())
    if not description:
        raise ValueError("Missing description")

    try:
        if p.amount_col:
            cents = parse_cents(cell(row, p.amount_col)) * (-1 if p.flip_sign else 1)
        else:
            debit, credit = cell(row, p.debit_col), cell(row, p.credit_col)
            if not debit and not credit:
                raise ValueError
            # Banks disagree on whether debits are written negative, so ignore their sign.
            cents = (abs(parse_cents(credit)) if credit else 0) - (abs(parse_cents(debit)) if debit else 0)
    except ValueError:
        raise ValueError("Unreadable amount") from None
    if cents == 0:
        raise ValueError("Amount is zero")
    return Transaction(None, when, description, cents)
