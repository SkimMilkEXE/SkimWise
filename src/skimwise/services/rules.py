from __future__ import annotations  # our list() method shadows the builtin inside the class body

from skimwise.db.rule_repo import RuleRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import Rule


class RuleError(ValueError):
    """A user-facing validation error; the message is safe to show in the UI."""


def match(rules: list[Rule], description: str) -> int | None:
    """Category of the first rule (in priority order) whose pattern appears in the description."""
    text = description.casefold()
    return next((r.category_id for r in rules if r.pattern.casefold() in text), None)


def suggest_pattern(description: str) -> str:
    """A starting pattern for a rule made from one transaction: the description up to the first
    word with a digit or '#', which is usually a store number or date.
    "STARBUCKS #1234" -> "STARBUCKS", "KROGER 567 CINCINNATI" -> "KROGER"."""
    words = description.split()
    keep = []
    for w in words:
        if any(ch.isdigit() or ch == "#" for ch in w):
            break
        keep.append(w)
    return " ".join(keep or words)


class RuleService:
    def __init__(self, rules: RuleRepository, transactions: TransactionRepository):
        self.rules = rules
        self.transactions = transactions

    def list(self) -> list[Rule]:
        return self.rules.list()

    def categorize(self, description: str) -> int | None:
        return match(self.rules.list(), description)

    def add(self, pattern: str, category_id: int | None) -> Rule:
        return self.rules.add(*_validate(pattern, category_id))

    def update(self, rule_id: int, pattern: str, category_id: int | None) -> None:
        self.rules.update(rule_id, *_validate(pattern, category_id))

    def delete(self, rule_id: int) -> None:
        self.rules.delete(rule_id)

    def move(self, rule_id: int, step: int) -> None:
        """step -1 = higher priority (earlier), +1 = lower. No-op at either end."""
        rules = self.rules.list()
        i = next(i for i, r in enumerate(rules) if r.id == rule_id)
        if 0 <= i + step < len(rules):
            self.rules.swap_priority(rules[i], rules[i + step])

    def rerun(self, overwrite: bool = False) -> int:
        """Categorize existing transactions. By default only uncategorized ones are touched;
        with overwrite, a matching rule also replaces an existing category. Transactions no
        rule matches keep whatever category they have. Returns how many changed."""
        rules = self.rules.list()
        changes = []
        for tx in self.transactions.list():
            if tx.category_id is not None and not overwrite:
                continue
            category = match(rules, tx.description)
            if category is not None and category != tx.category_id:
                changes.append((tx.id, category))
        self.transactions.set_categories(changes)
        return len(changes)


def _validate(pattern: str, category_id: int | None) -> tuple[str, int]:
    pattern = " ".join(pattern.split())
    if not pattern:
        raise RuleError("Enter the text to look for in descriptions.")
    if category_id is None:
        raise RuleError("Choose a category.")
    return pattern, category_id
