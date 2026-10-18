from dataclasses import dataclass


@dataclass(frozen=True)
class BankProfile:
    """How to read one bank's CSV export. Columns are referenced by header name."""

    name: str = ""
    skip_rows: int = 0  # rows above the header row
    date_col: str = ""
    description_col: str = ""
    amount_col: str = ""  # set this, or debit_col/credit_col
    debit_col: str = ""
    credit_col: str = ""
    flip_sign: bool = False  # for exports where expenses are positive numbers
    id: int | None = None
