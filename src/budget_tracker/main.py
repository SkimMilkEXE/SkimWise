import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from budget_tracker.db.connection import connect
from budget_tracker.services.app_services import build_services
from budget_tracker.services.demo import demo_connection
from budget_tracker.ui.colors import apply_background
from budget_tracker.ui.main_window import MainWindow
from budget_tracker.ui.reading import apply_reading, load_fonts
from budget_tracker.ui.settings import APP_NAME, app_settings

ASSETS = Path(__file__).parent / "assets"
OLD_NAME = "BudgetTracker"  # the app's name before it became SkimWise


def move_old_data_dir(data_dir: Path) -> None:
    """One-time move of the data folder saved under the old app name, so renaming the app loses nothing."""
    old_dir = data_dir.parent / OLD_NAME
    if old_dir.is_dir() and not data_dir.exists():
        old_dir.rename(data_dir)  # the database (and anything else) moves with the folder


def copy_old_settings(old: QSettings, new: QSettings) -> None:
    """One-time copy of preferences saved under the old app name (only if none exist under the new one)."""
    if old.allKeys() and not new.allKeys():
        for key in old.allKeys():
            new.setValue(key, old.value(key))


class WindowSwitcher:
    """Keeps one main window open and swaps it between the real data and the demo data."""

    def __init__(self, real: sqlite3.Connection):
        self.real = real
        self.window: MainWindow | None = None

    def show_real(self) -> None:
        self._show(build_services(self.real), demo=False)

    def show_demo(self) -> None:
        self._show(build_services(demo_connection()), demo=True)  # fresh each time; discarded on exit

    def rebuild(self) -> None:
        # a fresh window with the same data, so every label picks up a new font or size
        self._show(self.window.services, self.window.demo)

    def _show(self, services, demo: bool) -> None:
        old = self.window
        self.window = MainWindow(services, demo)
        self.window.explore_demo_requested.connect(self.show_demo)
        self.window.exit_demo_requested.connect(self.show_real)
        self.window.rebuild_requested.connect(self.rebuild)
        if old:
            self.window.restoreGeometry(old.saveGeometry())  # open exactly where the old one was
        self.window.show()  # show the new window before closing the old, or the app would quit
        if old:
            old.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            old.close()


def main() -> int:
    if sys.platform == "win32":
        # Give the app its own taskbar identity; otherwise Windows groups it under python.exe
        # and shows Python's icon instead of ours.
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)  # AppDataLocation is derived from this
    app.setWindowIcon(QIcon(str(ASSETS / "budget-icon.ico")))  # every window and dialog inherits it
    load_fonts(ASSETS / "fonts")
    apply_reading(app)
    apply_background(app)  # before any window exists, so nothing has to be restyled

    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    move_old_data_dir(data_dir)
    copy_old_settings(QSettings(OLD_NAME, OLD_NAME), app_settings())
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(data_dir / "budget.db")

    switcher = WindowSwitcher(conn)
    switcher.show_real()
    first_launch = not app_settings().value("welcome_shown", False, type=bool)
    if first_launch and not conn.execute("SELECT 1 FROM transactions LIMIT 1").fetchone():
        QTimer.singleShot(0, switcher.window.show_welcome)  # once the window is on screen
    return app.exec()  # Qt's event loop; returns when the last window closes


if __name__ == "__main__":
    sys.exit(main())
