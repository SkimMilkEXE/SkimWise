import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

import skimwise.ui.colors as colors
import skimwise.ui.settings as settings
from skimwise.services.budgets import NEAR, OK, OVER, BudgetLine
from skimwise.ui.colors import CUSTOM, DARK, LIGHT, contrast, readability_warning
from skimwise.ui.colors_dialog import ColorsDialog

WHITE, DARK_GREY = QColor("#ffffff"), QColor("#2b2b2b")


@pytest.fixture(autouse=True)
def temp_settings(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    ini = str(tmp_path / "settings.ini")  # never the real registry
    monkeypatch.setattr(settings, "QSettings", lambda *_: QSettings(ini, QSettings.Format.IniFormat))
    colors.reload()
    monkeypatch.setattr(colors, "current_mode", lambda: LIGHT)  # the offscreen test platform has no theme
    yield
    QApplication.instance().setPalette(QPalette())  # don't leave a custom background for other tests


def test_standard_colors_are_unchanged_by_default():
    assert colors.amount_color(500).name() == "#1a7f37" and colors.amount_color(-500).name() == "#c62828"
    assert colors.budget_color(OVER) == "#d93025"
    assert colors.chart_color("spending").name() == "#eb6834"


def test_colorblind_preset_replaces_red_and_green():
    colors.save("colorblind", {LIGHT: {}, DARK: {}})
    assert colors.amount_color(500).name() == "#0067a3" and colors.amount_color(-500).name() == "#b34700"
    assert [colors.budget_color(level) for level in (OK, NEAR, OVER)] == ["#0072b2", "#b07d00", "#c4285f"]
    for mode in (LIGHT, DARK):  # amounts are text: readable on that mode's background
        background = WHITE if mode == LIGHT else DARK_GREY
        picked = colors.preset_colors("colorblind", mode)
        assert contrast(QColor(picked["income"]), background) >= 4.5
        assert contrast(QColor(picked["expense"]), background) >= 4.5


def test_custom_colors_are_kept_per_mode_and_fall_back_to_standard():
    colors.save(CUSTOM, {LIGHT: {"expense": "#8000ff"}, DARK: {}})
    assert colors.amount_color(-500).name() == "#8000ff"
    assert colors.amount_color(500).name() == "#1a7f37"  # not picked: standard
    assert colors.resolve(*colors.load(), DARK)["expense"] == "#f87171"  # dark mode untouched


def test_contrast_and_warnings():
    assert round(contrast(QColor("black"), QColor("white"))) == 21
    assert readability_warning("expense", QColor("#c62828"), WHITE) == ""
    assert "Hard to see" in readability_warning("expense", QColor("#ffee88"), WHITE)  # pale text on white
    assert readability_warning("budget_near", QColor("#b07d00"), WHITE) == ""  # bars only need 3:1


def test_dialog_pick_preview_save_and_reset(monkeypatch):
    dialog = ColorsDialog(None)
    assert dialog.preset_box.currentText() == "Standard" and dialog.mode == LIGHT

    monkeypatch.setattr(
        "skimwise.ui.colors_dialog.QColorDialog.getColor", lambda *_: QColor("#ffee88")
    )  # user picks a pale yellow for expenses
    dialog.pick("expense")
    assert dialog.preset_box.currentText() == "Custom"
    assert "Hard to see" in dialog.warnings["expense"].text()  # warned, but allowed
    assert "#ffee88" in dialog.expense_sample.styleSheet()  # live preview
    dialog.accept()
    assert colors.amount_color(-500).name() == "#ffee88"

    dialog = ColorsDialog(None)
    dialog.reset()
    dialog.accept()
    assert colors.load() == ("standard", {LIGHT: {}, DARK: {}}) and colors.amount_color(-500).name() == "#c62828"


def test_cancelling_the_color_picker_changes_nothing(monkeypatch):
    dialog = ColorsDialog(None)
    monkeypatch.setattr("skimwise.ui.colors_dialog.QColorDialog.getColor", lambda *_: QColor())  # cancel
    dialog.pick("income")
    assert dialog.preset_box.currentText() == "Standard"


def test_budget_status_is_in_words_not_just_color():
    from skimwise.ui.budgets_view import STATUS_WORDS

    assert STATUS_WORDS == {NEAR: "near limit", OVER: "over budget"}
    assert BudgetLine(1, "x", 10000, 9000).level == NEAR  # 90% -> "near limit" in the Used column


@pytest.mark.parametrize("preset", ["standard", "colorblind"])
def test_built_in_presets_never_show_a_warning(preset):
    for mode, backgrounds in ((LIGHT, ["#ffffff"]), (DARK, ["#1e1e1e", "#2b2b2b"])):
        for role, value in colors.preset_colors(preset, mode).items():
            for background in backgrounds:
                assert readability_warning(role, QColor(value), QColor(background)) == "", (mode, role, background)


def test_background_is_per_mode_and_resets(monkeypatch):
    app = QApplication.instance()
    theme_window = app.palette().color(QPalette.ColorRole.Window)
    theme_style = app.style().name()
    colors.save_backgrounds({LIGHT: "#1f3a5f", DARK: ""})  # dark navy in light mode
    colors.apply_background(app)
    assert app.palette().color(QPalette.ColorRole.Base).name() == "#1f3a5f"
    assert app.palette().color(QPalette.ColorRole.Text).name() == "#ffffff"  # text flips to stay readable
    assert colors.chart_color("ink").name() == "#ffffff"  # chart titles too
    assert app.style().name() == "fusion"  # the style that draws everything from the palette

    monkeypatch.setattr(colors, "current_mode", lambda: DARK)  # dark mode has no custom background
    colors.apply_background(app)
    assert app.palette().color(QPalette.ColorRole.Window) == theme_window
    assert app.style().name() == theme_style  # the normal look is back


def test_dialog_checks_colors_against_the_chosen_background(monkeypatch):
    dialog = ColorsDialog(None)
    assert not dialog.background_default.isEnabled()  # already the theme default
    assert dialog.warnings["income"].text() == ""

    monkeypatch.setattr("skimwise.ui.colors_dialog.QColorDialog.getColor", lambda *_: QColor("#1f3a5f"))
    dialog.pick_background()
    assert "Hard to see" in dialog.warnings["income"].text()  # dark green amounts on dark navy
    assert dialog.preset_box.currentText() == "Standard"  # a background doesn't make the preset custom
    assert dialog.background_default.isEnabled()
    dialog.accept()
    assert colors.load_backgrounds() == {LIGHT: "#1f3a5f", DARK: ""}

    dialog = ColorsDialog(None)
    dialog.default_background()
    dialog.accept()
    assert colors.load_backgrounds() == {LIGHT: "", DARK: ""}
