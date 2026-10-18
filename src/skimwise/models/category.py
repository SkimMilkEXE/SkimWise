from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: int
    name: str
