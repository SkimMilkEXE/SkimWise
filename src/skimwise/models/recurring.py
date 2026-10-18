from dataclasses import dataclass

MONTHLY, YEARLY = "monthly", "yearly"


@dataclass(frozen=True)
class RecurringItem:
    """A payment the user has confirmed (or added) as recurring."""

    id: int
    name: str
    amount_cents: int  # per charge, positive
    frequency: str  # MONTHLY or YEARLY

    @property
    def yearly_cents(self) -> int:
        return self.amount_cents * 12 if self.frequency == MONTHLY else self.amount_cents
