import re
from decimal import Decimal, InvalidOperation

_CURRENCY_SYMBOLS = "$€£¥"
_DECIMAL_COMMA = re.compile(r"-?\d+,\d{1,2}")  # "12,50": thousands groups are always 3 digits, so this is a decimal
_THOUSANDS = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d*)?")  # "1,234" / "12,345,678.90"


def parse_cents(text: str) -> int:
    """Parse a user- or bank-style amount into integer cents.

    "12.5" -> 1250, "$1,234.56" -> 123456, "-3" -> -300, "(5.00)" -> -500,
    "€12,50" -> 1250, "1.234,56" -> 123456, "5.00-" -> -500, "5.00 DR" -> -500, "5.00 CR" -> 500.
    Raises ValueError for anything else, including fractions of a cent.
    """
    s = text.strip()
    for symbol in _CURRENCY_SYMBOLS:
        s = s.replace(symbol, "")
    s = s.replace(" ", "")

    negative = False  # set by an explicit marker; the result is then negative however many markers there are
    if s.upper().endswith(("CR", "DR")):  # bank shorthand: credit (money in) / debit (money out)
        negative = s.upper().endswith("DR")
        s = s[:-2]
    if s.endswith("-"):  # trailing minus: "5.00-"
        negative, s = True, s[:-1]
    if s.startswith("(") and s.endswith(")"):  # accounting negative: "(5.00)"
        negative, s = True, s[1:-1]

    if _DECIMAL_COMMA.fullmatch(s):
        s = s.replace(",", ".")
    elif "," in s and "." in s and s.rindex(",") > s.rindex("."):  # European "1.234,56"
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        if not _THOUSANDS.fullmatch(s):  # "1,2,3" isn't a number; don't guess
            raise ValueError(f"Not a valid amount: {text!r}")
        s = s.replace(",", "")  # US thousands separators

    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"Not a valid amount: {text!r}") from None
    if not d.is_finite() or d.as_tuple().exponent < -2:
        raise ValueError(f"Not a valid amount: {text!r}")
    cents = int(d * 100)
    return -abs(cents) if negative else cents


def count(n: int, noun: str) -> str:
    """count(1, "transaction") -> "1 transaction", count(3, "transaction") -> "3 transactions"."""
    return f"{n} {noun}{'' if n == 1 else 's'}"


def format_cents(cents: int) -> str:
    """1234 -> "$12.34", -123456 -> "-$1,234.56"."""
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}${dollars:,}.{rem:02}"
