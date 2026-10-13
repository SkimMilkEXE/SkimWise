from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QHeaderView

from budget_tracker.ui.settings import app_settings

# reading options for people who find dense screens hard to read, e.g. with dyslexia or low vision
# key -> (menu label, font family or None for the system font)
FONTS = {
    "default": ("Default", None),
    "atkinson": ("Atkinson Hyperlegible", "Atkinson Hyperlegible"),  # by the braille institute
    "opendyslexic": ("OpenDyslexic", "OpenDyslexic"),
}
TEXT_SIZES = {"100": "100%", "125": "125%", "150": "150%"}

_system_font: QFont | None = None  # the font the app started with, so sizes don't compound


def load_fonts(folder: Path) -> None:
    # registers the bundled fonts so qt can use them by family name
    for path in sorted(folder.glob("*.[ot]tf")):
        QFontDatabase.addApplicationFont(str(path))


def font_choice() -> str:
    value = app_settings().value("reading/font", "default")
    return value if value in FONTS else "default"


def text_size() -> str:
    value = app_settings().value("reading/text_size", "100")
    return value if value in TEXT_SIZES else "100"


def striped_rows() -> bool:
    return app_settings().value("reading/striped_rows", False, type=bool)


def apply_reading(app) -> None:
    # sets the app-wide font: chosen family and size, on top of the system font
    global _system_font
    if _system_font is None:
        _system_font = QFont(app.font())
    font = QFont(_system_font)
    family = FONTS[font_choice()][1]
    if family:
        font.setFamily(family)
    font.setPointSizeF(_system_font.pointSizeF() * int(text_size()) / 100)
    app.setFont(font)


def fit_columns(table, stretch: int) -> None:
    # short columns (dates, amounts) grow with the text size so nothing gets cut off,
    # and the one wide column (like the description) takes up the rest
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)


def stripe(table) -> None:
    # alternating row shades help your eye stay on the right row across a wide table
    table.setAlternatingRowColors(striped_rows())
