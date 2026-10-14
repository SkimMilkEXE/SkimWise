from dataclasses import dataclass
from datetime import date

NO_CATEGORY = 0  # category filter value meaning "uncategorized" (real ids start at 1)
INCOME, EXPENSE = "income", "expense"  # type filter values


@dataclass(frozen=True)
class Transaction:
    id: int | None  # None until saved
    date: date
    description: str
    amount_cents: int  # negative = expense, positive = income
    category_id: int | None = None
