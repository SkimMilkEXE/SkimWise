"""Smoke tests for the real window: every tab builds and shows the demo data, and the main flows
work end to end. Runs offscreen against an in-memory database; settings go to a temp .ini file."""

from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

import budget_tracker.ui.colors as colors
import budget_tracker.ui.settings as settings
from budget_tracker.db.connection import connect
from budget_tracker.services.app_services import build_services
from budget_tracker.services.csv_import import read_rows
from budget_tracker.services.demo import demo_transactions
from budget_tracker.ui.import_dialog import ImportDialog
from budget_tracker.ui.main_window import MainWindow
from budget_tracker.ui.rules_view import RuleDialog

DEMO = Path(__file__).parent / "fixtures" / "demo_transactions.csv"


@pytest.fixture
def asked(monkeypatch):
    """Records every Yes/No question the app asks; answers with asked.answer (Yes by default)."""

    class Asked(list):
        answer = QMessageBox.StandardButton.Yes

    questions = Asked()

    def question(_parent, title, text, *_):
        questions.append((title, text))
        return questions.answer

    monkeypatch.setattr(QMessageBox, "question", question)
    return questions


@pytest.fixture
def window(tmp_path, monkeypatch, asked):
    app = QApplication.instance() or QApplication([])
    # Never touch the real registry: every app_settings() call gets a temp .ini file instead.
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(settings, "QSettings", lambda *_: QSettings(ini, QSettings.Format.IniFormat))
    colors.reload()  # forget colors cached from another test's settings
    # Message boxes would block waiting for a click; acknowledge them automatically.
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: QMessageBox.StandardButton.Ok)

    w = MainWindow(build_services(connect(":memory:")))
    w.show()
    yield w
    w.close()
    app.setPalette(QPalette())  # back to the theme's own colors for the next test
    app.processEvents()


def tab(w, name):
    index = next(i for i in range(w.tabs.count()) if w.tabs.tabText(i) == name)
    w.tabs.setCurrentIndex(index)  # triggers the view's refresh(), like a user click
    return w.tabs.currentWidget()


def import_demo(w):
    view = tab(w, "Transactions")
    dialog = ImportDialog(view, view.importer, DEMO, read_rows(DEMO), {})
    assert dialog.summary.text().startswith("527 new")
    dialog.profile_name.setText("Demo Bank")
    dialog.accept()
    view.refresh()
    return view


def test_tabs_in_order(window):
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert names == ["Transactions", "Budgets", "Charts", "Subscriptions", "Rules", "Categories"]


def test_import_then_filter(window):
    view = import_demo(window)
    assert view.proxy.rowCount() == 527
    view.month.setCurrentIndex(view.month.findData("2026-02"))
    assert {view.model.rows[i].date.month for i in range(view.proxy.rowCount())} == {2}
    view.search.setText("netflix")
    assert view.proxy.rowCount() == 1


def test_manual_categorize_offers_rule_that_fills_in_the_rest(window, monkeypatch):
    view = import_demo(window)
    dining = next(c.id for c in view._category_list if c.name == "Dining")
    monkeypatch.setattr(RuleDialog, "exec", lambda self: (self.accept(), self.result())[1])  # user clicks OK
    view._offer_rule("STARBUCKS #10293", dining)
    assert [r.pattern for r in view.rules.list()] == ["STARBUCKS"]
    view.search.setText("starbucks")
    assert all(view.model.rows[i].category_id == dining for i in range(view.proxy.rowCount()))


def test_budgets_tab_shows_progress(window):
    import_demo(window)
    budgets = tab(window, "Budgets")
    groceries = next(c.id for c in budgets.categories.list() if c.name == "Groceries")
    budgets.budgets.set_limit(groceries, "400")
    budgets.refresh()
    assert budgets.table.rowCount() == 1
    assert budgets.table.cellWidget(0, 1) is not None  # the progress bar
    assert budgets.summary.text().startswith("Total:")


def test_charts_tab_draws_all_three(window):
    import_demo(window)
    charts = tab(window, "Charts")
    charts.month.setCurrentIndex(charts.month.findData("2026-09"))
    assert charts.by_category.chart().series()  # uncategorized spending still charts
    bar_sets = charts.income_expenses.chart().series()[0].barSets()
    assert [b.label() for b in bar_sets] == ["Income", "Expenses"]
    assert bar_sets[0].count() == 12  # Oct 2025 - Sep 2026


def test_subscriptions_confirm(window):
    import_demo(window)
    subs = tab(window, "Subscriptions")
    detected = subs.suggestions.rowCount()
    assert detected >= 5
    subs.suggestions.selectRow(0)
    subs.confirm()
    assert subs.table.rowCount() == 1 and subs.suggestions.rowCount() == detected - 1
    assert "/ month" in subs.total.text()


def test_settings_menu_changes_formats_and_theme(window):
    import_demo(window)
    menu = window.tabs.cornerWidget().menu()
    submenu = {a.text().replace("&", ""): a.menu() for a in menu.actions() if a.menu()}
    assert set(submenu) == {"Theme", "Month format", "Date format"}
    actions = [a.text().replace("&", "") for a in menu.actions() if not a.menu() and not a.isSeparator()]
    assert actions == [
        "Colors…",
        "Back up data…",
        "Restore from backup…",
        "Delete all data…",
        "Explore demo data",
        "About SkimWise",
    ]

    next(a for a in submenu["Date format"].actions() if a.text() == "Aug 31, 2026").trigger()
    view = window.tabs.currentWidget()
    assert view.proxy.index(0, 0).data() == "Sep 29, 2026"

    # (The offscreen test platform has no system theme, so we check the saved choice, not the colours.)
    next(a for a in submenu["Theme"].actions() if a.text() == "Dark").trigger()
    assert settings.app_settings().value("theme") == "Dark"  # saved to the temp .ini, not the registry


def test_window_remembers_geometry(window):
    window.resize(1000, 700)
    window.close()
    assert settings.app_settings().value("geometry")


def select_rows(view, rows):
    from PySide6.QtCore import QItemSelectionModel

    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    view.table.clearSelection()
    for r in rows:
        view.table.selectionModel().select(view.proxy.index(r, 0), flags)


def test_multi_delete_asks_first_and_no_means_no(window, asked):
    view = import_demo(window)
    select_rows(view, [0, 1, 2])
    assert view.delete_btn.text() == "Delete (3)" and not view.edit_btn.isEnabled()

    asked.answer = QMessageBox.StandardButton.No
    view.delete()
    title, text = asked[-1]
    assert title == "Delete transactions" and "3 transactions" in text and "can't be undone" in text
    assert view.proxy.rowCount() == 527  # nothing deleted

    asked.answer = QMessageBox.StandardButton.Yes
    view.delete()
    assert view.proxy.rowCount() == 524


def test_set_category_on_selection(window, monkeypatch):
    view = import_demo(window)
    select_rows(view, [0, 1, 2, 3])
    chosen = [view.selected_rows()[i].id for i in range(4)]
    monkeypatch.setattr("budget_tracker.ui.transactions_view.QInputDialog.getItem", lambda *_: ("Dining", True))
    view.set_category()
    dining = next(c.id for c in view._category_list if c.name == "Dining")
    assert {t.id: t.category_id for t in view.model.rows if t.id in chosen} == dict.fromkeys(chosen, dining)


def test_totals_line_follows_filters(window):
    view = tab(window, "Transactions")
    assert view.summary.text().startswith("No transactions yet")
    import_demo(window)
    assert view.summary.text().startswith("527 transactions  ·  Income $")
    view.search.setText("netflix")
    assert view.summary.text().startswith("12 transactions")  # one a month
    view.month.setCurrentIndex(view.month.findData("2026-02"))
    assert view.summary.text() == "1 transaction  ·  Income $0.00  ·  Expenses $15.49  ·  Net -$15.49"
    view.search.setText("no such merchant")
    assert view.summary.text() == "No transactions match these filters."


def test_demo_mode_switches_windows_and_leaves_real_data_alone(window, monkeypatch):
    from budget_tracker.main import WindowSwitcher

    real = connect(":memory:")
    switcher = WindowSwitcher(real)
    switcher.show_real()
    switcher.window.explore_demo_requested.emit()
    demo_window = switcher.window
    assert demo_window.demo and "demo data" in demo_window.windowTitle()
    assert demo_window.transactions_view.proxy.rowCount() == len(
        demo_transactions(date.today())
    )  # any day of the month
    backup_action = next(a for a in demo_window.tabs.cornerWidget().menu().actions() if "Back up" in a.text())
    assert not backup_action.isEnabled()  # no backing up demo data

    demo_window.exit_demo_requested.emit()
    assert not switcher.window.demo
    assert real.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    switcher.window.close()


def test_welcome_offers_demo_and_remembers_it_was_shown(window, monkeypatch):
    def click(label):
        monkeypatch.setattr(
            QMessageBox, "exec", lambda box: next(b for b in box.buttons() if b.text() == label).click()
        )

    wanted_demo = []
    window.explore_demo_requested.connect(lambda: wanted_demo.append(True))
    click("Start empty")
    window.show_welcome()
    assert not wanted_demo and settings.app_settings().value("welcome_shown", type=bool)
    click("Explore demo data")
    window.show_welcome()
    assert wanted_demo == [True]


def test_redetect_button_asks_then_restores_dismissed(window, asked):
    import_demo(window)
    subs = tab(window, "Subscriptions")
    assert not subs.redetect_btn.isEnabled()  # nothing hidden yet
    detected = subs.suggestions.rowCount()
    subs.suggestions.selectRow(0)
    subs.dismiss()
    assert subs.suggestions.rowCount() == detected - 1 and subs.redetect_btn.isEnabled()

    asked.answer = QMessageBox.StandardButton.No
    subs.redetect()
    assert "1 merchant" in asked[-1][1] and subs.suggestions.rowCount() == detected - 1

    asked.answer = QMessageBox.StandardButton.Yes
    subs.redetect()
    assert subs.suggestions.rowCount() == detected and not subs.redetect_btn.isEnabled()


def test_about_shows_version_and_data_folder(window, monkeypatch):
    from budget_tracker import __version__

    shown = []
    monkeypatch.setattr(QMessageBox, "about", lambda _parent, title, text: shown.append((title, text)))
    window.show_about()
    title, text = shown[0]
    assert title == "About SkimWise" and f"SkimWise {__version__}" in text and "stored on this PC" in text


@pytest.mark.parametrize(
    "button, backup_ok, typed, deleted",
    [
        ("Cancel", True, "DELETE", False),
        ("Delete everything…", True, "delete", False),  # must be typed exactly
        ("Delete everything…", True, "DELETE", True),
        ("Back up first…", False, "DELETE", False),  # the backup was cancelled or failed: stop
        ("Back up first…", True, "DELETE", True),
    ],
)
def test_delete_all_needs_confirmation(window, monkeypatch, button, backup_ok, typed, deleted):
    import_demo(window)
    settings.app_settings().setValue("welcome_shown", True)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: next(b for b in box.buttons() if b.text() == button).click())
    monkeypatch.setattr(window, "back_up", lambda: backup_ok)
    monkeypatch.setattr("budget_tracker.ui.main_window.QInputDialog.getText", lambda *_: (typed, True))

    window.delete_all()
    remaining = window.transactions_view.proxy.rowCount()
    assert (remaining == 0) == deleted
    assert settings.app_settings().contains("welcome_shown") != deleted  # a fresh start greets you again


def test_import_button_accepts_pdf_statements(window, monkeypatch, tmp_path):
    from test_pdf_import import MT_STATEMENT, make_pdf

    pdf = make_pdf(tmp_path / "statement.pdf", MT_STATEMENT)
    view = tab(window, "Transactions")
    monkeypatch.setattr("budget_tracker.ui.transactions_view.QFileDialog.getOpenFileName", lambda *_: (str(pdf), ""))
    monkeypatch.setattr(ImportDialog, "exec", lambda self: (self.accept(), self.result())[1])  # user clicks Import
    view.import_csv()
    assert view.proxy.rowCount() == 5


def test_import_dialog_shows_which_line_has_the_column_names(window, tmp_path):
    from test_pdf_import import MT_STATEMENT, make_pdf

    csv_path = Path(__file__).parent / "fixtures" / "checking.csv"  # 4 lines of account details on top
    dialog = ImportDialog(window, window.services.importer, csv_path, read_rows(csv_path), {})
    assert dialog.header_line.value() == 5  # found automatically, counted from 1
    assert dialog.header_found.text() == "Found: Posting Date  ·  Description  ·  Amount  ·  Balance"

    dialog.header_line.setValue(1)  # a wrong pick is obvious from what it finds
    assert dialog.header_found.text() == "Found: Account Name:  ·  Everyday Checking"
    dialog.header_line.setValue(5)
    assert dialog.summary.text().startswith("6 new") and dialog.current_profile().skip_rows == 4  # stored as before

    pdf = make_pdf(tmp_path / "statement.pdf", MT_STATEMENT)
    from budget_tracker.services.pdf_import import read_statement

    pdf_dialog = ImportDialog(window, window.services.importer, pdf, read_statement(pdf), {})
    assert pdf_dialog.header_line.isHidden()  # not relevant to PDF statements
