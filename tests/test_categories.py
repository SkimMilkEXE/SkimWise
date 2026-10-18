import pytest

from skimwise.db.category_repo import CategoryRepository
from skimwise.db.connection import MIGRATIONS, connect, migrate
from skimwise.services.categories import CategoryError, CategoryService


@pytest.fixture
def service():
    return CategoryService(CategoryRepository(connect(":memory:")))


def names(service):
    return [c.name for c in service.list()]


def test_new_db_has_default_categories_sorted(service):
    assert names(service) == sorted(names(service), key=str.lower)
    assert "Groceries" in names(service)


def test_add_rename_delete(service):
    cat = service.add("  Pet   Supplies ")
    assert cat.name == "Pet Supplies"
    service.rename(cat.id, "Pets")
    assert "Pets" in names(service) and "Pet Supplies" not in names(service)
    service.delete(cat.id)
    assert "Pets" not in names(service)


def test_rejects_empty_and_duplicate_names(service):
    with pytest.raises(CategoryError):
        service.add("   ")
    with pytest.raises(CategoryError):
        service.add("groceries")  # case-insensitive duplicate
    other = service.add("Other")
    with pytest.raises(CategoryError):
        service.rename(other.id, "Rent")


def test_migrate_is_idempotent():
    conn = connect(":memory:")
    migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
