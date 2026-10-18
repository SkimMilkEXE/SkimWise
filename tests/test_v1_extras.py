import sqlite3
from datetime import date

import pytest

from skimwise.db.connection import MIGRATIONS, connect
from skimwise.services.app_services import build_services
from skimwise.services.backup import BackupError
from skimwise.services.demo import demo_connection, demo_transactions
from skimwise.services.reports import months_ending
from skimwise.services.transactions import totals


@pytest.fixture
def services():
    return build_services(connect(":memory:"))


def add(services, desc, amount, is_expense=True, when=date(2026, 9, 1)):
    return services.transactions.add(when, desc, amount, is_expense, None)


# --- bulk actions and totals ---


def test_delete_and_categorize_several_at_once(services):
    a, b, c = (add(services, d, "10") for d in ("A", "B", "C"))
    dining = next(cat.id for cat in services.categories.list() if cat.name == "Dining")

    services.transactions.set_category([a.id, b.id], dining)
    assert {t.description: t.category_id for t in services.transactions.list()} == {"A": dining, "B": dining, "C": None}
    services.transactions.set_category([a.id], None)  # back to uncategorized
    assert services.transactions.list(search="A")[0].category_id is None

    services.transactions.delete([a.id, c.id])
    assert [t.description for t in services.transactions.list()] == ["B"]
    services.transactions.delete([])  # nothing selected: nothing happens
    assert len(services.transactions.list()) == 1


def test_totals(services):
    add(services, "Pay", "3000", is_expense=False)
    add(services, "Rent", "1500")
    add(services, "Food", "250.50")
    t = totals(services.transactions.list())
    assert (t.count, t.income_cents, t.expense_cents, t.net_cents) == (3, 300000, 175050, 124950)
    assert totals([]).net_cents == 0


# --- backup and restore ---


def test_backup_then_restore_brings_data_back(services, tmp_path):
    add(services, "Kept", "10")
    backup = tmp_path / "backup.db"
    services.backup.backup_to(backup)

    add(services, "Added after backup", "20")
    services.transactions.delete([t.id for t in services.transactions.list() if t.description == "Kept"])
    services.backup.restore_from(backup)
    assert [t.description for t in services.transactions.list()] == ["Kept"]

    services.backup.backup_to(backup)  # backing up over an old backup replaces it
    services.backup.restore_from(backup)
    assert [t.description for t in services.transactions.list()] == ["Kept"]


def test_restore_rejects_files_that_arent_skimwise_backups(services, tmp_path):
    add(services, "Mine", "10")
    not_a_db = tmp_path / "notes.db"
    not_a_db.write_text("hello")
    other_db = tmp_path / "other.db"
    sqlite3.connect(other_db).execute("CREATE TABLE stuff (x)").connection.close()
    newer = tmp_path / "newer.db"
    conn = connect(newer)
    conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    conn.close()

    for path, message in [
        (tmp_path / "missing.db", "doesn't exist"),
        (not_a_db, "isn't a SkimWise backup"),
        (other_db, "isn't a SkimWise backup"),
        (newer, "newer version"),
    ]:
        with pytest.raises(BackupError, match=message):
            services.backup.restore_from(path)
    assert [t.description for t in services.transactions.list()] == ["Mine"]  # untouched every time


def test_restoring_an_older_backup_upgrades_it(services, tmp_path):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    for i, script in enumerate(MIGRATIONS[:2], start=1):  # a backup from before budgets existed
        conn.executescript(f"BEGIN; {script} PRAGMA user_version = {i}; COMMIT;")
    conn.execute("INSERT INTO transactions (date, description, amount_cents) VALUES ('2026-01-01', 'Old', -500)")
    conn.commit()
    conn.close()

    services.backup.restore_from(old)
    assert [t.description for t in services.transactions.list()] == ["Old"]
    groceries = next(c.id for c in services.categories.list() if c.name == "Groceries")
    services.budgets.set_limit(groceries, "100")  # tables from later migrations exist again
    assert services.budgets.lines("2026-01")[0].limit_cents == 10000


def test_backup_refuses_to_overwrite_the_live_database(tmp_path):
    live = tmp_path / "budget.db"
    services = build_services(connect(live))
    add(services, "Precious", "10")
    with pytest.raises(BackupError, match="different file"):
        services.backup.backup_to(live)
    assert [t.description for t in services.transactions.list()] == ["Precious"]


# --- demo data ---


def test_demo_data_is_a_full_current_year():
    services = build_services(demo_connection(today=date(2026, 9, 27)))
    txs = services.transactions.list()
    assert len(txs) > 400
    assert min(t.date for t in txs) >= date(2025, 10, 1) and max(t.date for t in txs) <= date(2026, 9, 27)
    assert sorted(services.transactions.months()) == months_ending("2026-09", 12)  # every month present
    categorized = sum(t.category_id is not None for t in txs) / len(txs)
    assert categorized > 0.8  # the demo rules cover almost everything
    assert len(services.budgets.lines("2026-09")) == 5
    assert [i.name for i in services.recurring.items()] == ["NETFLIX.COM", "PLANET FITNESS", "SPOTIFY USA"]


def test_demo_dates_follow_today_and_never_go_past_it():
    txs = demo_transactions(date(2030, 3, 15))
    assert min(t.date for t in txs) >= date(2029, 4, 1)
    assert max(t.date for t in txs) <= date(2030, 3, 15)
    assert demo_transactions(date(2030, 3, 15)) == txs  # deterministic


def test_demo_database_is_separate(tmp_path):
    real = build_services(connect(tmp_path / "budget.db"))
    demo_connection()
    assert real.transactions.list() == []


def test_restore_refuses_the_live_database_instead_of_freezing(tmp_path):
    live = tmp_path / "budget.db"
    services = build_services(connect(live))
    add(services, "Precious", "10")
    with pytest.raises(BackupError, match="different file"):
        services.backup.restore_from(live)
    assert [t.description for t in services.transactions.list()] == ["Precious"]


def test_failed_backup_keeps_the_previous_backup(services, tmp_path, monkeypatch):
    backup = tmp_path / "backup.db"
    add(services, "First", "10")
    services.backup.backup_to(backup)
    before = backup.read_bytes()

    def broken(*_):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sqlite3, "connect", broken)  # simulate the write failing midway
    with pytest.raises(BackupError, match="Couldn't save"):
        services.backup.backup_to(backup)
    assert backup.read_bytes() == before  # the old backup is untouched
    assert not (tmp_path / "backup.db.partial").exists()


def test_backup_to_unwritable_place_is_a_clear_error(services, tmp_path):
    with pytest.raises(BackupError, match="another folder"):
        services.backup.backup_to(tmp_path / "no such folder" / "backup.db")


# --- delete all data ---


def test_delete_all_returns_to_a_fresh_install(services):
    add(services, "Gone", "10")
    dining = next(c.id for c in services.categories.list() if c.name == "Dining")
    services.rules.add("coffee", dining)
    services.budgets.set_limit(dining, "100")
    services.recurring.add("Gym", "20", "monthly")
    services.categories.add("Custom")

    services.backup.delete_all()
    fresh = build_services(connect(":memory:"))
    assert services.transactions.list() == [] and services.rules.list() == []
    assert services.budgets.lines("2026-09") == [] and services.recurring.items() == []
    assert [c.name for c in services.categories.list()] == [c.name for c in fresh.categories.list()]
    add(services, "Works after", "5")  # the app keeps working normally afterwards
    assert len(services.transactions.list()) == 1
