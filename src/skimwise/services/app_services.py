"""Every service the UI needs, built for one database connection."""

import sqlite3
from dataclasses import dataclass

from skimwise.db.budget_repo import BudgetRepository
from skimwise.db.category_repo import CategoryRepository
from skimwise.db.profile_repo import ProfileRepository
from skimwise.db.recurring_repo import RecurringRepository
from skimwise.db.rule_repo import RuleRepository
from skimwise.db.transaction_repo import TransactionRepository
from skimwise.services.backup import BackupService
from skimwise.services.budgets import BudgetService
from skimwise.services.categories import CategoryService
from skimwise.services.csv_import import ImportService
from skimwise.services.recurring_detection import RecurringService
from skimwise.services.reports import ReportService
from skimwise.services.rules import RuleService
from skimwise.services.transactions import TransactionService


@dataclass(frozen=True)
class AppServices:
    categories: CategoryService
    transactions: TransactionService
    importer: ImportService
    rules: RuleService
    budgets: BudgetService
    reports: ReportService
    recurring: RecurringService
    backup: BackupService


def build_services(conn: sqlite3.Connection) -> AppServices:
    tx, rules, cats = TransactionRepository(conn), RuleRepository(conn), CategoryRepository(conn)
    return AppServices(
        categories=CategoryService(cats),
        transactions=TransactionService(tx),
        importer=ImportService(tx, ProfileRepository(conn), rules),
        rules=RuleService(rules, tx),
        budgets=BudgetService(BudgetRepository(conn), tx, cats),
        reports=ReportService(tx, cats),
        recurring=RecurringService(RecurringRepository(conn), tx),
        backup=BackupService(conn),
    )
