"""User preferences (theme, month and date formats) stored with QSettings: the registry on
Windows, a config file on Linux."""

from datetime import datetime

from PySide6.QtCore import QSettings

APP_NAME = "SkimWise"
TAGLINE = "Skim the fat off your spending"

# key -> (menu label, strftime format)
MONTH_FORMATS = {
    "numbers": ("Numbers (2026-09)", "%Y-%m"),
    "names": ("Names (September 2026)", "%B %Y"),
}

# key -> (menu label, strftime format for display, Qt format for the date picker)
DATE_FORMATS = {
    "iso": ("2026-08-31", "%Y-%m-%d", "yyyy-MM-dd"),
    "us": ("08/31/2026", "%m/%d/%Y", "MM/dd/yyyy"),
    "names": ("Aug 31, 2026", "%b %d, %Y", "MMM dd, yyyy"),
}


def app_settings() -> QSettings:
    # Explicit names so we don't have to set an organization name, which would move the app data folder.
    return QSettings(APP_NAME, APP_NAME)


def _chosen(setting: str, options: dict, default: str) -> tuple:
    return options.get(app_settings().value(setting, default), options[default])


def month_label(year_month: str) -> str:
    """ "2026-09" shown in the user's chosen month format."""
    return datetime.strptime(year_month, "%Y-%m").strftime(_chosen("month_format", MONTH_FORMATS, "numbers")[1])


def date_format() -> str:
    """strftime format for showing dates. Read it once per refresh, not per table cell."""
    return _chosen("date_format", DATE_FORMATS, "iso")[1]


def qt_date_format() -> str:
    """The same format in Qt's syntax, for QDateEdit.setDisplayFormat."""
    return _chosen("date_format", DATE_FORMATS, "iso")[2]
