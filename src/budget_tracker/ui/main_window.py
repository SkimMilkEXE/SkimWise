from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QActionGroup, QGuiApplication, QPalette
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from budget_tracker import __version__
from budget_tracker.services.app_services import AppServices
from budget_tracker.services.backup import BackupError
from budget_tracker.ui.budgets_view import BudgetsView
from budget_tracker.ui.categories_view import CategoriesView
from budget_tracker.ui.charts_view import ChartsView
from budget_tracker.ui.colors import apply_background
from budget_tracker.ui.colors_dialog import ColorsDialog
from budget_tracker.ui.reading import FONTS, TEXT_SIZES, apply_reading, font_choice, striped_rows, text_size
from budget_tracker.ui.rules_view import RulesView
from budget_tracker.ui.settings import APP_NAME, DATE_FORMATS, MONTH_FORMATS, TAGLINE, app_settings
from budget_tracker.ui.subscriptions_view import SubscriptionsView
from budget_tracker.ui.transactions_view import TransactionsView

# Theme menu entries. ColorScheme.Unknown tells Qt to follow the Windows setting.
THEMES = {"System": Qt.ColorScheme.Unknown, "Light": Qt.ColorScheme.Light, "Dark": Qt.ColorScheme.Dark}


class MainWindow(QMainWindow):
    # Ask main.py to swap this window for one showing demo data, or back to the real data.
    explore_demo_requested = Signal()
    exit_demo_requested = Signal()
    rebuild_requested = Signal()  # reading options changed: main.py swaps in a fresh window

    def __init__(self, services: AppServices, demo: bool = False):
        super().__init__()
        self.services = services
        self.demo = demo
        self.setWindowTitle(f"{APP_NAME} - {TAGLINE}" + ("  (demo data)" if demo else ""))
        self.settings = app_settings()
        self.resize(900, 600)
        self.restoreGeometry(self.settings.value("geometry", b""))  # last size/position, if any

        # One tab per feature.
        self.tabs = tabs = QTabWidget()
        s = services
        self.transactions_view = TransactionsView(s.transactions, s.categories, s.importer, s.rules)
        tabs.addTab(self.transactions_view, "Transactions")
        tabs.addTab(BudgetsView(s.budgets, s.categories), "Budgets")
        tabs.addTab(ChartsView(s.reports), "Charts")
        tabs.addTab(SubscriptionsView(s.recurring), "Subscriptions")
        tabs.addTab(RulesView(s.rules, s.categories), "Rules")
        tabs.addTab(CategoriesView(s.categories), "Categories")
        # Each view reloads when shown, so edits made in one tab appear in the others.
        tabs.currentChanged.connect(self.refresh_current_tab)
        # Redraw on light/dark switches too, so theme-dependent colours (budget bars) update.
        # (A method, not a lambda: Qt disconnects it automatically when this window is deleted.)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._theme_changed)
        # Settings sits at the right end of the tab bar instead of in a separate menu bar.
        tabs.setCornerWidget(self._settings_button(), Qt.Corner.TopRightCorner)

        credit = QLabel("Built by SkimMilk.EXE")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credit.setForegroundRole(QPalette.ColorRole.PlaceholderText)  # muted grey that follows the theme
        font = credit.font()
        font.setPointSizeF(font.pointSizeF() * 0.85)
        credit.setFont(font)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 4)  # keep the tabs flush with the window edges
        if demo:
            layout.addWidget(self._demo_banner())
        layout.addWidget(tabs)
        layout.addWidget(credit)
        self.setCentralWidget(central)

    def _settings_button(self) -> QToolButton:
        menu = QMenu(self)
        theme = self.settings.value("theme", "System")
        self._add_choice_menu(menu, "&Theme", {n: n for n in THEMES}, theme, self.set_theme)
        self.set_theme(theme if theme in THEMES else "System")
        months = {key: label for key, (label, _fmt) in MONTH_FORMATS.items()}
        current = self.settings.value("month_format", "numbers")
        self._add_choice_menu(menu, "&Month format", months, current, self.set_month_format)
        dates = {key: label for key, (label, _fmt, _qt) in DATE_FORMATS.items()}
        current = self.settings.value("date_format", "iso")
        self._add_choice_menu(menu, "&Date format", dates, current, self.set_date_format)
        menu.addAction("&Colors…").triggered.connect(self.edit_colors)

        # reading comfort: font, text size and striped rows
        reading = menu.addMenu("&Reading")
        fonts = {key: label for key, (label, _family) in FONTS.items()}
        self._add_choice_menu(reading, "&Font", fonts, font_choice(), lambda k: self.set_reading("font", k))
        sizes = TEXT_SIZES
        self._add_choice_menu(reading, "Text &size", sizes, text_size(), lambda k: self.set_reading("text_size", k))
        stripes = reading.addAction("&Striped table rows")
        stripes.setCheckable(True)
        stripes.setChecked(striped_rows())
        stripes.toggled.connect(lambda on: self.set_reading("striped_rows", on))

        menu.addSeparator()
        data_actions = (
            ("&Back up data…", self.back_up),
            ("&Restore from backup…", self.restore),
            ("&Delete all data…", self.delete_all),
        )
        for text, slot in data_actions:
            action = menu.addAction(text)
            action.triggered.connect(slot)
            action.setEnabled(not self.demo)  # these act on your real data, never the demo
        menu.addSeparator()
        if not self.demo:
            menu.addAction("&Explore demo data").triggered.connect(self.explore_demo_requested)
        menu.addAction(f"&About {APP_NAME}").triggered.connect(self.show_about)

        button = QToolButton()
        button.setText("Settings")
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)  # open the menu on click
        button.setAutoRaise(True)  # flat until hovered, like the tabs next to it
        button.setStyleSheet("QToolButton { padding: 2px 10px; } QToolButton::menu-indicator { image: none; }")
        return button

    def _add_choice_menu(
        self, menu: QMenu, title: str, options: dict[str, str], current: str, on_pick: Callable[[str], None]
    ) -> None:
        """A submenu of mutually exclusive choices (key -> label), with `current` checked."""
        submenu = menu.addMenu(title)
        group = QActionGroup(submenu)  # makes the actions mutually exclusive, like radio buttons
        for key, label in options.items():
            action = submenu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == current)
            group.addAction(action)
            action.triggered.connect(lambda _checked, k=key: on_pick(k))

    def _demo_banner(self) -> QWidget:
        banner = QWidget()
        banner.setStyleSheet("background: palette(highlight); color: palette(highlighted-text);")
        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 6, 12, 6)
        row.addWidget(QLabel("You're exploring demo data. Nothing here is saved, and your real data isn't touched."))
        row.addStretch()
        exit_btn = QPushButton("Exit demo")
        exit_btn.clicked.connect(self.exit_demo_requested)
        row.addWidget(exit_btn)
        return banner

    def set_reading(self, key: str, value) -> None:
        self.settings.setValue(f"reading/{key}", value)
        apply_reading(QGuiApplication.instance())
        self.rebuild_requested.emit()

    def edit_colors(self) -> None:
        if ColorsDialog(self).exec():
            self._redraw_for_background()

    def _theme_changed(self, *_) -> None:
        self._redraw_for_background()  # the other mode may have a different background

    def _redraw_for_background(self) -> None:
        if apply_background(QGuiApplication.instance()):
            self.rebuild_requested.emit()  # the style changed: a fresh window keeps fonts right
        else:
            self.refresh_current_tab()  # other tabs pick the new colors up when they're shown

    def show_about(self) -> None:
        data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b><br>{TAGLINE}.<br><br>"
            "A private, local-only budget app: no accounts, no internet, no tracking.<br>"
            f"Your data is stored on this PC in:<br><code>{data}</code><br><br>"
            "Built by SkimMilk.EXE",
        )

    def refresh_current_tab(self, *_) -> None:
        self.tabs.currentWidget().refresh()

    def show_welcome(self) -> None:
        """First launch with no data: offer demo data, an import, or an empty start."""
        box = QMessageBox(self)
        box.setWindowTitle(f"Welcome to {APP_NAME}")
        box.setText(f"<b>Welcome to {APP_NAME}</b><br>{TAGLINE}.")
        box.setInformativeText(
            "Import a CSV or PDF statement from your bank to get started, or look around first with a year "
            "of demo data. "
            "Everything stays on this PC."
        )
        demo = box.addButton("Explore demo data", QMessageBox.ButtonRole.ActionRole)
        import_csv = box.addButton("Import a bank statement…", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Start empty", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(demo)
        box.exec()
        self.settings.setValue("welcome_shown", True)  # once is enough; the demo stays in Settings
        if box.clickedButton() is demo:
            self.explore_demo_requested.emit()
        elif box.clickedButton() is import_csv:
            self.transactions_view.import_csv()

    def back_up(self) -> bool:
        """Returns True if a backup was saved."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up SkimWise data", f"SkimWise backup {date.today()}.db", "SkimWise backup (*.db)"
        )
        if not path:
            return False
        try:
            self.services.backup.backup_to(path)
        except (BackupError, OSError) as e:
            QMessageBox.warning(self, "Backup failed", str(e))
            return False
        QMessageBox.information(self, "Backup saved", f"Your data was saved to:\n{path}")
        return True

    def delete_all(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Delete all data")
        box.setText("<b>Delete all your data and start fresh?</b>")
        box.setInformativeText(
            "This permanently deletes every transaction, rule, budget, subscription and bank profile, "
            "and puts the categories back to the defaults. Your theme and format settings are kept.\n\n"
            "It can't be undone unless you have a backup."
        )
        back_up_first = box.addButton("Back up first…", QMessageBox.ButtonRole.ActionRole)
        carry_on = box.addButton("Delete everything…", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(box.addButton(QMessageBox.StandardButton.Cancel))  # the safe choice
        box.exec()
        if box.clickedButton() is back_up_first:
            if not self.back_up():
                return  # no backup, no delete
        elif box.clickedButton() is not carry_on:
            return

        typed, ok = QInputDialog.getText(self, "Delete all data", "Type DELETE to confirm:")
        if not ok or typed.strip() != "DELETE":
            if ok:
                QMessageBox.information(self, "Delete all data", "Nothing was deleted.")
            return
        self.services.backup.delete_all()
        self.settings.remove("welcome_shown")  # the next launch greets you like a first launch
        self.refresh_current_tab()
        QMessageBox.information(self, "Delete all data", f"All data deleted. {APP_NAME} is back to a fresh start.")

    def restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore SkimWise backup", "", "SkimWise backup (*.db)")
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "Restore backup",
            "Replace ALL your current data with this backup?\n\n"
            "Anything added since the backup was made will be lost. If you're not sure, cancel and "
            "back up your current data first.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,  # the safe choice is the default
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.services.backup.restore_from(path)
        except (BackupError, OSError) as e:
            QMessageBox.warning(self, "Restore failed", f"Nothing was changed.\n\n{e}")
            return
        self.refresh_current_tab()
        QMessageBox.information(self, "Backup restored", "Your data was restored from the backup.")

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())  # reopen at the same size and place
        super().closeEvent(event)

    def set_theme(self, name: str) -> None:
        QGuiApplication.styleHints().setColorScheme(THEMES[name])
        self.settings.setValue("theme", name)

    def set_month_format(self, key: str) -> None:
        self.settings.setValue("month_format", key)
        self.tabs.currentWidget().refresh()  # relabel month pickers (other tabs refresh when shown)

    def set_date_format(self, key: str) -> None:
        self.settings.setValue("date_format", key)
        self.tabs.currentWidget().refresh()  # redraw dates (other tabs refresh when shown)
