from datetime import date, timedelta
from pathlib import Path

import pytest

from skimwise.db.connection import connect
from skimwise.db.profile_repo import ProfileRepository
from skimwise.db.recurring_repo import RecurringRepository
from skimwise.db.rule_repo import RuleRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.models import MONTHLY, YEARLY, RecurringItem, Transaction
from skimwise.services.csv_import import ImportService, guess_profile, read_rows
from skimwise.services.recurring_detection import RecurringError, RecurringService, detect, merchant, totals


def monthly(desc, cents, n, start=date(2026, 1, 5), step=30):
    return [Transaction(None, start + timedelta(days=step * i), desc, cents) for i in range(n)]


def names(txs):
    return {c.name: c.frequency for c in detect(txs)}


def test_merchant_strips_store_numbers():
    assert merchant("Spotify #88 NY") == "SPOTIFY"
    assert merchant("NETFLIX.COM") == "NETFLIX.COM"


def test_monthly_and_yearly_detected():
    txs = monthly("NETFLIX.COM", -1549, 4) + [
        Transaction(None, date(2025, 3, 1), "AMAZON PRIME", -13900),
        Transaction(None, date(2026, 3, 3), "AMAZON PRIME", -13900),
    ]
    assert names(txs) == {"NETFLIX.COM": MONTHLY, "AMAZON PRIME": YEARLY}


def test_price_increase_within_tolerance_uses_latest_amount():
    txs = monthly("NETFLIX.COM", -1549, 3) + monthly("NETFLIX.COM", -1799, 2, start=date(2026, 4, 4))
    [c] = detect(txs)
    assert c.amount_cents == 1799 and c.count == 5


@pytest.mark.parametrize(
    "txs, merchant_name",
    [
        (monthly("NETFLIX.COM", -1549, 2), "NETFLIX.COM"),  # too few charges
        (monthly("KROGER", -5000, 10, step=7), "KROGER"),  # weekly
        (monthly("POWER CO", -9000, 3) + monthly("POWER CO", -20000, 1, start=date(2026, 4, 5)), "POWER CO"),
        (monthly("PAYROLL", 300000, 6), "PAYROLL"),  # income, not a charge
        # stopped a year before the newest transaction
        (monthly("OLD GYM", -2499, 4, start=date(2025, 1, 1)) + monthly("NETFLIX.COM", -1549, 3), "OLD GYM"),
    ],
)
def test_not_recurring(txs, merchant_name):
    assert merchant_name not in names(txs)


def test_totals_convert_yearly_to_monthly():
    items = [RecurringItem(1, "Netflix", 1500, MONTHLY), RecurringItem(2, "Prime", 12000, YEARLY)]
    assert totals(items) == (2500, 30000)  # 15 + 120/12 per month; 180 + 120 per year


@pytest.fixture
def service():
    conn = connect(":memory:")
    tx_repo = TransactionRepository(conn)
    importer = ImportService(tx_repo, ProfileRepository(conn), RuleRepository(conn))
    rows = read_rows(Path(__file__).parent / "fixtures" / "demo_transactions.csv")
    importer.commit(importer.preview(rows, guess_profile(rows[0], 0)))
    return RecurringService(RecurringRepository(conn), tx_repo)


def test_demo_data_finds_bills_and_subscriptions(service):
    found = {c.name for c in service.suggestions()}
    assert {"NETFLIX.COM", "SPOTIFY USA", "COMCAST INTERNET", "RENT PAYMENT - OAKWOOD APTS"} <= found
    assert "KROGER" not in found  # weekly, varying amounts


def test_confirm_dismiss_and_manual_items(service):
    netflix, spotify = (next(c for c in service.suggestions() if c.name == n) for n in ("NETFLIX.COM", "SPOTIFY USA"))
    service.confirm(netflix)
    service.dismiss(spotify)
    remaining = {c.name for c in service.suggestions()}
    assert "NETFLIX.COM" not in remaining and "SPOTIFY USA" not in remaining  # neither suggested again
    assert [i.name for i in service.items()] == ["NETFLIX.COM"]  # dismissed isn't listed

    service.add(" Car  insurance ", "$600", YEARLY)
    car = next(i for i in service.items() if i.name == "Car insurance")
    service.update(car.id, "Car insurance", "650", YEARLY)
    assert next(i for i in service.items() if i.id == car.id).amount_cents == 65000

    with pytest.raises(RecurringError):
        service.add("netflix.com", "15", MONTHLY)  # duplicate name, any case
    with pytest.raises(RecurringError):
        service.add("Spotify USA", "12", MONTHLY)  # was dismissed
    for bad in (("", "5", MONTHLY), ("Gym", "abc", MONTHLY), ("Gym", "0", MONTHLY), ("Gym", "5", "weekly")):
        with pytest.raises(RecurringError):
            service.add(*bad)

    service.remove(car.id)
    assert [i.name for i in service.items()] == ["NETFLIX.COM"]


def test_recurring_fixture_every_case():
    """tests/fixtures/recurring_demo.csv: two years where each merchant exercises one detection case."""
    conn = connect(":memory:")
    tx_repo = TransactionRepository(conn)
    importer = ImportService(tx_repo, ProfileRepository(conn), RuleRepository(conn))
    rows = read_rows(Path(__file__).parent / "fixtures" / "recurring_demo.csv")
    importer.commit(importer.preview(rows, guess_profile(rows[0], 0)))
    found = {c.name: (c.frequency, c.amount_cents) for c in detect(tx_repo.list())}

    assert found == {
        "NETFLIX.COM": (MONTHLY, 1799),  # price increase: latest amount wins
        "SPOTIFY": (MONTHLY, 1199),  # changing store numbers grouped together
        "DISNEY PLUS": (MONTHLY, 1399),  # end-of-month billing, 28-31 day gaps
        "RENT PAYMENT - OAKWOOD APTS": (MONTHLY, 145000),
        "PLANET FITNESS": (MONTHLY, 2499),
        "AMAZON PRIME MEMBERSHIP": (YEARLY, 13900),
        "ADOBE CREATIVE CLOUD": (YEARLY, 23988),
    }
    # Deliberately absent: HULU (cancelled), CITY POWER & LIGHT (amount varies), XBOX GAME PASS
    # (missed a month), YOGA STUDIO (only two charges), PAYROLL (income), KROGER (weekly).


def test_redetect_brings_back_dismissed_but_keeps_confirmed(service):
    by_name = {c.name: c for c in service.suggestions()}
    service.confirm(by_name["NETFLIX.COM"])
    service.dismiss(by_name["SPOTIFY USA"])  # the accident
    service.dismiss(by_name["COMCAST INTERNET"])
    assert service.dismissed_count() == 2
    assert "SPOTIFY USA" not in {c.name for c in service.suggestions()}

    assert service.redetect() == 2
    assert service.dismissed_count() == 0
    suggested = {c.name for c in service.suggestions()}
    assert {"SPOTIFY USA", "COMCAST INTERNET"} <= suggested
    assert "NETFLIX.COM" not in suggested  # still confirmed, not re-suggested
    assert [i.name for i in service.items()] == ["NETFLIX.COM"]
    service.add("Spotify USA", "11.99", MONTHLY)  # and a formerly dismissed name can now be added by hand


def test_renaming_a_confirmed_item_doesnt_resuggest_it(service):
    netflix = next(c for c in service.suggestions() if c.name == "NETFLIX.COM")
    service.confirm(netflix)
    item = next(i for i in service.items() if i.name == "NETFLIX.COM")
    service.update(item.id, "Netflix", "15.49", MONTHLY)
    assert "NETFLIX.COM" not in {c.name for c in service.suggestions()}


def test_upgrade_fills_in_merchant_for_existing_items():
    import sqlite3

    from skimwise.db.connection import MIGRATIONS, migrate

    conn = sqlite3.connect(":memory:")
    for i, script in enumerate(MIGRATIONS[:6], start=1):  # a database from before the merchant column
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = {i}; COMMIT;")
    conn.execute("INSERT INTO recurring_items (name, amount_cents, frequency) VALUES ('Netflix.com', 1549, 'monthly')")
    conn.commit()
    migrate(conn)
    assert RecurringRepository(conn).known_merchants() == {"NETFLIX.COM"}


def test_renaming_to_another_merchants_name_never_breaks_confirm(service):
    by_name = {c.name: c for c in service.suggestions()}
    service.confirm(by_name["NETFLIX.COM"])
    netflix = next(i for i in service.items() if i.name == "NETFLIX.COM")
    service.update(netflix.id, "Spotify USA", "15.49", MONTHLY)
    # A suggestion that would collide with that name isn't offered, so Confirm can't fail on it.
    assert "SPOTIFY USA" not in {c.name for c in service.suggestions()}
    for c in service.suggestions():
        service.confirm(c)  # every remaining suggestion confirms cleanly
