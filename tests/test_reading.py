from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication, QTableWidget

import skimwise.ui.colors as colors
import skimwise.ui.reading as reading
import skimwise.ui.settings as settings
from skimwise.db.connection import connect
from skimwise.services.app_services import build_services
from skimwise.ui.main_window import MainWindow

FONTS = Path(__file__).parent.parent / "src" / "skimwise" / "assets" / "fonts"


@pytest.fixture(autouse=True)
def app(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    ini = str(tmp_path / "settings.ini")  # never the real registry
    monkeypatch.setattr(settings, "QSettings", lambda *_: QSettings(ini, QSettings.Format.IniFormat))
    colors.reload()
    reading.load_fonts(FONTS)
    yield app
    if reading._system_font is not None:
        app.setFont(reading._system_font)  # don't leave a big or different font for other tests


def test_bundled_fonts_and_licences_ship_with_the_app():
    names = sorted(p.name for p in FONTS.iterdir())
    assert "OFL-AtkinsonHyperlegible.txt" in names and "OFL-OpenDyslexic.txt" in names
    families = QFontDatabase.families()
    assert "Atkinson Hyperlegible" in families and "OpenDyslexic" in families


def test_defaults_change_nothing():
    assert (reading.font_choice(), reading.text_size(), reading.striped_rows()) == ("default", "100", False)


def test_font_and_size_apply_and_never_compound(app):
    reading.apply_reading(app)
    base = QApplication.font()
    settings.app_settings().setValue("reading/font", "atkinson")
    settings.app_settings().setValue("reading/text_size", "150")
    reading.apply_reading(app)
    assert app.font().family() == "Atkinson Hyperlegible"
    assert app.font().pointSizeF() == pytest.approx(base.pointSizeF() * 1.5)

    reading.apply_reading(app)  # applying twice doesn't grow it again
    assert app.font().pointSizeF() == pytest.approx(base.pointSizeF() * 1.5)

    settings.app_settings().setValue("reading/font", "default")
    settings.app_settings().setValue("reading/text_size", "100")
    reading.apply_reading(app)
    assert app.font() == base  # exactly back to the system font


def test_unknown_saved_values_fall_back_safely():
    settings.app_settings().setValue("reading/font", "comic sans")
    settings.app_settings().setValue("reading/text_size", "999")
    assert (reading.font_choice(), reading.text_size()) == ("default", "100")


def test_striped_rows():
    table = QTableWidget()
    reading.stripe(table)
    assert not table.alternatingRowColors()
    settings.app_settings().setValue("reading/striped_rows", True)
    reading.stripe(table)
    assert table.alternatingRowColors()


def test_reading_menu_saves_and_asks_for_a_fresh_window(app):
    window = MainWindow(build_services(connect(":memory:")))
    rebuilt = []
    window.rebuild_requested.connect(lambda: rebuilt.append(True))
    menu = window.tabs.cornerWidget().menu()
    reading_menu = next(a.menu() for a in menu.actions() if a.text() == "&Reading")
    items = {a.text().replace("&", ""): a for a in reading_menu.actions()}
    assert set(items) == {"Font", "Text size", "Row highlight", "Highlight style", "Striped table rows"}

    next(a for a in items["Font"].menu().actions() if a.text() == "OpenDyslexic").trigger()
    items["Striped table rows"].trigger()
    assert (reading.font_choice(), reading.striped_rows()) == ("opendyslexic", True)
    assert app.font().family() == "OpenDyslexic" and rebuilt == [True, True]
    window.close()


def test_rebuilt_window_keeps_the_same_data_and_picks_up_stripes():
    from skimwise.main import WindowSwitcher

    switcher = WindowSwitcher(connect(":memory:"))
    switcher.show_real()
    services, old = switcher.window.services, switcher.window
    assert not old.transactions_view.table.alternatingRowColors()
    settings.app_settings().setValue("reading/striped_rows", True)
    switcher.rebuild()
    assert switcher.window is not old and switcher.window.services is services and not switcher.window.demo
    assert switcher.window.transactions_view.table.alternatingRowColors()
    switcher.window.close()


def test_every_tab_gets_the_text_size_not_just_the_visible_one(app):
    # regression: restyling the app while the window was built left hidden tabs at the old size
    settings.app_settings().setValue("reading/text_size", "150")
    reading.apply_reading(app)
    colors.apply_background(app)
    window = MainWindow(build_services(connect(":memory:")))
    window.show()
    app.processEvents()
    from PySide6.QtWidgets import QAbstractItemView

    sizes = {t.font().pointSizeF() for t in window.findChildren(QAbstractItemView)}
    assert sizes == {app.font().pointSizeF()}
    window.close()


def test_switching_style_for_a_background_rebuilds_the_window(app, monkeypatch):
    monkeypatch.setattr(colors, "current_mode", lambda: colors.LIGHT)
    original_style = app.style().name()
    app.setStyle("Windows")  # the test platform defaults to fusion, so start from a different style
    monkeypatch.setattr(colors, "_theme_style", None)
    colors.apply_background(app)  # remembers "windows" as the theme's own style
    window = MainWindow(build_services(connect(":memory:")))
    rebuilt = []
    window.rebuild_requested.connect(lambda: rebuilt.append(True))

    colors.save_backgrounds({colors.LIGHT: "#f6efe0", colors.DARK: ""})
    window._redraw_for_background()  # theme style -> fusion: needs a fresh window
    window._redraw_for_background()  # same style again: just a redraw
    assert rebuilt == [True]

    colors.save_backgrounds({colors.LIGHT: "", colors.DARK: ""})
    window._redraw_for_background()  # back to the theme style
    assert rebuilt == [True, True]
    window.close()
    app.setStyle(original_style)
