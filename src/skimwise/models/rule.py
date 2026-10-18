from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """Description contains `pattern` -> category. Lower priority runs first."""

    id: int
    pattern: str
    category_id: int
    priority: int
