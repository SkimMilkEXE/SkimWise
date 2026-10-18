from datetime import date
from pathlib import Path

import pytest

from skimwise.db.category_repo import CategoryRepository
from skimwise.db.connection import connect
from skimwise.db.profile_repo import ProfileRepository
from skimwise.db.rule_repo import RuleRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.services.categories import CategoryService
from skimwise.services.csv_import import ImportService, guess_profile, read_rows
from skimwise.services.rules import RuleError, RuleService, match, suggest_pattern
from skimwise.services.transactions import TransactionService


@pytest.fixture
def app():
    conn = connect(":memory:")
    tx_repo, rule_repo = TransactionRepository(conn), RuleRepository(conn)
    cats = {c.name: c.id for c in CategoryService(CategoryRepository(conn)).list()}
    return RuleService(rule_repo, tx_repo), TransactionService(tx_repo), CategoryService(CategoryRepository(conn)), cats


@pytest.mark.parametrize(
    "description, pattern",
    [
        ("STARBUCKS #1234", "STARBUCKS"),
        ("KROGER 567 CINCINNATI", "KROGER"),
        ("NETFLIX.COM STREAMING", "NETFLIX.COM STREAMING"),
        ("7-ELEVEN 3321", "7-ELEVEN 3321"),  # would be empty, so keep everything
    ],
)
def test_suggest_pattern(description, pattern):
    assert suggest_pattern(description) == pattern


def test_first_match_wins_and_move_changes_order(app):
    rules, _, _, cats = app
    rules.add("amazon", cats["Entertainment"])
    prime = rules.add("amazon prime", cats["Subscriptions"])
    assert rules.categorize("AMAZON PRIME*1X2Y") == cats["Entertainment"]  # case-insensitive, first rule wins

    rules.move(prime.id, -1)
    assert rules.categorize("AMAZON PRIME*1X2Y") == cats["Subscriptions"]
    assert rules.categorize("Amazon.com order") == cats["Entertainment"]
    assert rules.categorize("Kroger") is None

    rules.move(prime.id, -1)  # already first: no-op
    assert [r.pattern for r in rules.list()] == ["amazon prime", "amazon"]


def test_rerun_respects_manual_categories_unless_overwrite(app):
    rules, txs, _, cats = app
    txs.add(date(2026, 9, 1), "STARBUCKS #1", "4", True, None)
    txs.add(date(2026, 9, 2), "STARBUCKS #2", "4", True, cats["Groceries"])  # set by hand
    txs.add(date(2026, 9, 3), "SHELL OIL", "40", True, cats["Transport"])  # no rule matches
    rules.add("starbucks", cats["Dining"])

    assert rules.rerun() == 1
    by_desc = {t.description: t.category_id for t in txs.list()}
    assert by_desc["STARBUCKS #1"] == cats["Dining"] and by_desc["STARBUCKS #2"] == cats["Groceries"]

    assert rules.rerun(overwrite=True) == 1
    by_desc = {t.description: t.category_id for t in txs.list()}
    assert by_desc["STARBUCKS #2"] == cats["Dining"]
    assert by_desc["SHELL OIL"] == cats["Transport"]  # unmatched keeps its category
    assert rules.rerun(overwrite=True) == 0


def test_validation_and_category_delete_removes_rules(app):
    rules, _, categories, cats = app
    with pytest.raises(RuleError):
        rules.add("   ", cats["Dining"])
    with pytest.raises(RuleError):
        rules.add("coffee", None)

    rules.add("coffee", cats["Dining"])
    categories.delete(cats["Dining"])
    assert rules.list() == []  # ON DELETE CASCADE


def test_import_applies_rules():
    conn = connect(":memory:")
    tx_repo, rule_repo = TransactionRepository(conn), RuleRepository(conn)
    cats = {c.name: c.id for c in CategoryService(CategoryRepository(conn)).list()}
    RuleService(rule_repo, tx_repo).add("starbucks", cats["Dining"])
    importer = ImportService(tx_repo, ProfileRepository(conn), rule_repo)

    rows = read_rows(Path(__file__).parent / "fixtures" / "checking.csv")
    importer.commit(importer.preview(rows, guess_profile(rows[4], 4)))
    categorized = {t.description: t.category_id for t in tx_repo.list()}
    assert categorized["STARBUCKS #1234"] == cats["Dining"]
    assert categorized["KROGER #567"] is None


def test_match_empty_rules():
    assert match([], "anything") is None


def test_edit_rule_changes_what_it_matches(app):
    rules, _, _, cats = app
    rule = rules.add("starbucks", cats["Dining"])
    rules.update(rule.id, "  dunkin  ", cats["Groceries"])
    assert [(r.pattern, r.category_id) for r in rules.list()] == [("dunkin", cats["Groceries"])]
    assert rules.categorize("DUNKIN #3345") == cats["Groceries"]
    assert rules.categorize("STARBUCKS #1") is None
    with pytest.raises(RuleError):
        rules.update(rule.id, "", cats["Dining"])

    rules.delete(rule.id)
    assert rules.list() == []
