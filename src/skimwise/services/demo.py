"""A year of realistic fake data for "Explore demo data", in its own in-memory database so it never
mixes with the user's real data. Dates end today, so the demo always looks current."""

import random
import sqlite3
from datetime import date, timedelta

from skimwise.db.connection import connect
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import Transaction
from skimwise.services.app_services import build_services
from skimwise.services.reports import months_ending

RULES = [
    ("PAYROLL", "Income"),
    ("RENT PAYMENT", "Rent"),
    ("KROGER", "Groceries"),
    ("TRADER JOE", "Groceries"),
    ("COSTCO", "Groceries"),
    ("STARBUCKS", "Dining"),
    ("CHIPOTLE", "Dining"),
    ("DOORDASH", "Dining"),
    ("OLIVE GARDEN", "Dining"),
    ("SUSHI", "Dining"),
    ("CITY POWER", "Utilities"),
    ("WATER DEPT", "Utilities"),
    ("COMCAST", "Utilities"),
    ("VERIZON", "Utilities"),
    ("NETFLIX", "Subscriptions"),
    ("SPOTIFY", "Subscriptions"),
    ("ICLOUD", "Subscriptions"),
    ("PLANET FITNESS", "Subscriptions"),
    ("SHELL OIL", "Transport"),
    ("EXXONMOBIL", "Transport"),
    ("UBER TRIP", "Transport"),
    ("LYFT", "Transport"),
    ("AMC THEATRES", "Entertainment"),
    ("STEAM", "Entertainment"),
]
BUDGETS = [
    ("Groceries", "650"),
    ("Dining", "400"),
    ("Utilities", "400"),
    ("Transport", "200"),
    ("Entertainment", "100"),
]
CONFIRMED_SUBSCRIPTIONS = ["NETFLIX.COM", "SPOTIFY USA", "PLANET FITNESS"]


def demo_connection(today: date | None = None) -> sqlite3.Connection:
    """An in-memory database filled with demo transactions, rules, budgets and subscriptions."""
    conn = connect(":memory:")
    services = build_services(conn)
    cats = {c.name: c.id for c in services.categories.list()}
    for pattern, category in RULES:
        services.rules.add(pattern, cats[category])
    TransactionRepository(conn).add_many(demo_transactions(today or date.today()))
    services.rules.rerun()  # categorize everything with the rules above
    for category, limit in BUDGETS:
        services.budgets.set_limit(cats[category], limit)
    for candidate in services.recurring.suggestions():
        if candidate.name in CONFIRMED_SUBSCRIPTIONS:
            services.recurring.confirm(candidate)
    return conn


def demo_transactions(today: date) -> list[Transaction]:
    """About 12 months of a checking account ending `today`. Deterministic for a given `today`."""
    rng = random.Random(2026)
    end = today
    first_month = months_ending(today.strftime("%Y-%m"), 12)[0]  # "YYYY-MM", 11 months back
    start = date.fromisoformat(f"{first_month}-01")
    rows: list[Transaction] = []

    def add(d: date, desc: str, cents: int) -> None:
        if start <= d <= end:
            rows.append(Transaction(None, d, desc, cents))

    def money(lo: float, hi: float) -> int:
        return round(rng.uniform(lo, hi) * 100)

    # Paycheck every other Friday
    payday = start + timedelta(days=(4 - start.weekday()) % 7)
    while payday <= end:
        add(payday, "PAYROLL DEPOSIT ACME CORP", 162500)
        payday += timedelta(days=14)

    # Monthly bills and subscriptions
    month = start
    while month <= end:
        y, m = month.year, month.month
        add(date(y, m, 1), "RENT PAYMENT - OAKWOOD APTS", -145000)
        seasonal = m in (12, 1, 2, 6, 7, 8)
        add(date(y, m, 8), "CITY POWER & LIGHT", -money(150, 210) if seasonal else -money(85, 120))
        add(date(y, m, 12), "METRO WATER DEPT", -money(38, 55))
        add(date(y, m, 15), "COMCAST INTERNET", -7999)
        add(date(y, m, 20), "VERIZON WIRELESS", -6500)
        add(date(y, m, 5), "NETFLIX.COM", -1549)
        add(date(y, m, 9), "SPOTIFY USA", -1199)
        add(date(y, m, 22), "ICLOUD STORAGE APPLE.COM/BILL", -299)
        add(date(y, m, 27), "PLANET FITNESS", -2499)
        month = date(y + (m == 12), m % 12 + 1, 1)

    # Day-to-day spending
    d = start
    while d <= end:
        wd, holiday = d.weekday(), d.month == 12
        if wd == 5:
            store = rng.choice(["KROGER #1123", "KROGER #1123", "TRADER JOE'S #552", "COSTCO WHSE #0412"])
            add(d, store, -money(140, 260) if "COSTCO" in store else -money(70, 190))
        if rng.random() < 0.28:
            add(d, rng.choice(["STARBUCKS #10293", "CHIPOTLE 2211", "DOORDASH*THAI BASIL"]), -money(6, 38))
        if wd in (4, 5) and rng.random() < 0.45:
            add(d, rng.choice(["OLIVE GARDEN 1182", "SUSHI ZEN", "LOCAL TAPHOUSE"]), -money(28, 95))
        if rng.random() < 0.12:
            add(d, rng.choice(["SHELL OIL 57442", "EXXONMOBIL 4410"]), -money(32, 62))
        if rng.random() < 0.06:
            add(d, rng.choice(["UBER TRIP", "LYFT RIDE"]), -money(11, 34))
        if rng.random() < (0.2 if holiday else 0.06):
            add(d, rng.choice(["AMAZON.COM*MK2L91", "TARGET T-1450"]), -money(15, 180 if holiday else 90))
        if rng.random() < 0.04:
            add(d, rng.choice(["AMC THEATRES 2201", "STEAM PURCHASE"]), -money(12, 70))
        d += timedelta(days=1)

    return sorted(rows, key=lambda t: (t.date, t.description))
