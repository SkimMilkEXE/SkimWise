from datetime import date

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

import skimwise.ui.colors as colors
import skimwise.ui.settings as settings
from skimwise.db.connection import connect
from skimwise.models import EXPENSE, INCOME
from skimwise.services.app_services import build_services
from skimwise.ui.colors import PRESETS, contrast, preset_colors
from skimwise.ui.transactions_view import (
    HIGHLIGHT_ROLE,
    STRIP_SPACE_ROLE,
    TINT_STRENGTH,
    TransactionsView,
)


@pytest.fixture
def view(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    ini = str(tmp_path / "settings.ini")  # never the real registry
    monkeypatch.setattr(settings, "QSettings", lambda *_: QSettings(ini, QSettings.Format.IniFormat))
    colors.reload()
    services = build_services(connect(":memory:"))
    services.transactions.add(date(2026, 9, 1), "Paycheck", "2000", False, None)
    services.transactions.add(date(2026, 9, 2), "Coffee", "4.50", True, None)
    return TransactionsView(services.transactions, services.categories, services.importer, services.rules)


def cell(view, description, role, column=0):
    row = next(i for i, t in enumerate(view.model.rows) if t.description == description)
    return view.model.data(view.model.index(row, column), role)


def set_reading(view, **values):
    for key, value in values.items():
        settings.app_settings().setValue(f"reading/{key}", value)
    view.reload_table()


def test_type_filter(view):
    for label, value, expected in (("Income", INCOME, ["Paycheck"]), ("Expenses", EXPENSE, ["Coffee"])):
        view.kind.setCurrentIndex(view.kind.findData(value))
        assert [t.description for t in view.model.rows] == expected and label in view.kind.currentText()
    assert view.summary.text().startswith("1 transaction")  # totals follow the filter
    view.kind.setCurrentIndex(0)
    assert len(view.model.rows) == 2


def test_no_highlight_by_default(view):
    assert cell(view, "Paycheck", Qt.ItemDataRole.BackgroundRole) is None
    assert not cell(view, "Paycheck", STRIP_SPACE_ROLE)


def test_tint_income_only_then_both(view):
    set_reading(view, row_highlight="income", highlight_style="tint")
    tint = cell(view, "Paycheck", Qt.ItemDataRole.BackgroundRole, column=2)  # every cell in the row
    assert tint.rgb() == colors.amount_color(1).rgb() and tint.alphaF() == pytest.approx(TINT_STRENGTH, abs=0.01)
    assert cell(view, "Coffee", Qt.ItemDataRole.BackgroundRole) is None
    set_reading(view, row_highlight="both")
    assert cell(view, "Coffee", Qt.ItemDataRole.BackgroundRole).rgb() == colors.amount_color(-1).rgb()


def test_strip_marks_rows_and_keeps_dates_aligned(view):
    set_reading(view, row_highlight="income", highlight_style="strip")
    assert cell(view, "Paycheck", HIGHLIGHT_ROLE) == colors.amount_color(1)
    assert cell(view, "Coffee", HIGHLIGHT_ROLE) is None  # no bar on expenses...
    assert cell(view, "Coffee", STRIP_SPACE_ROLE)  # ...but the same indent, so dates line up
    assert cell(view, "Paycheck", Qt.ItemDataRole.BackgroundRole) is None  # strip instead of tint


def test_tint_keeps_amount_text_readable_in_every_preset():
    for preset in PRESETS:
        for mode, base in (("light", "#ffffff"), ("dark", "#2b2b2b"), ("dark", "#1e1e1e")):
            background = QColor(base)
            for role in ("income", "expense"):
                text = QColor(preset_colors(preset, mode)[role])
                channels = ("redF", "greenF", "blueF")
                mix = [
                    TINT_STRENGTH * getattr(text, c)() + (1 - TINT_STRENGTH) * getattr(background, c)()
                    for c in channels
                ]
                assert contrast(text, QColor.fromRgbF(*mix)) >= 4.5, (preset, mode, base, role)
