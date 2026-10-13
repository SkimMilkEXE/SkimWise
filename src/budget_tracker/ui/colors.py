from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from budget_tracker.services.budgets import NEAR, OK, OVER
from budget_tracker.ui.settings import app_settings

LIGHT, DARK = "light", "dark"

# colors people can change: role -> (label in the colors dialog, used as text?)
# text needs 4.5:1 contrast to read comfortably, filled shapes like bars need 3:1
ROLES = {
    "income": ("Income amounts", True),
    "expense": ("Expense amounts", True),
    "budget_ok": ("Budget: under", False),
    "budget_near": ("Budget: near limit", False),
    "budget_over": ("Budget: over", False),
    "chart_income": ("Charts: income", False),
    "chart_spending": ("Charts: spending", False),
}

# each preset sets both modes: role -> (light mode, dark mode)
_CHARTS = {"chart_income": ("#2a78d6", "#3987e5"), "chart_spending": ("#eb6834", "#d95926")}
PRESETS = {
    "standard": (
        "Standard",
        {
            "income": ("#1a7f37", "#4ade80"),
            "expense": ("#c62828", "#f87171"),
            "budget_ok": ("#2e9e5b", "#4ade80"),
            "budget_near": ("#b07d00", "#facc15"),  # dark enough to see on white (3.6:1)
            "budget_over": ("#d93025", "#f87171"),
            **_CHARTS,
        },
    ),
    # blue / amber / pink-red instead of green / yellow / red, checked with a colour-blindness
    # simulator in both modes. the charts' blue and orange were already safe
    "colorblind": (
        "Color-blind friendly",
        {
            "income": ("#0067a3", "#56b4e9"),
            "expense": ("#b34700", "#ff8c42"),
            "budget_ok": ("#0072b2", "#3987e5"),
            "budget_near": ("#b07d00", "#b88a00"),
            "budget_over": ("#c4285f", "#e0447a"),
            **_CHARTS,
        },
    ),
}
CUSTOM = "custom"

# chart lines and text that aren't meant to be customized: role -> (light mode, dark mode)
_CHART_CHROME = {
    "ink": ("#0b0b0b", "#ffffff"),  # titles, legend
    "label": ("#52514e", "#c3c2b7"),  # axis tick labels
    "grid": ("#e1e0d9", "#3d3d3b"),
    "axis": ("#c3c2b7", "#555553"),
}

_LEVEL_ROLES = {OK: "budget_ok", NEAR: "budget_near", OVER: "budget_over"}
_cache: dict[str, dict[str, QColor]] = {}  # mode -> role -> color; amounts are drawn per table cell


def current_mode() -> str:
    return DARK if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark else LIGHT


def preset_colors(preset: str, mode: str) -> dict[str, str]:
    index = 1 if mode == DARK else 0
    return {role: pair[index] for role, pair in PRESETS[preset][1].items()}


def load() -> tuple[str, dict[str, dict[str, str]]]:
    # the saved preset, plus custom colors per mode (only filled in once someone customizes)
    settings = app_settings()
    preset = settings.value("colors/preset", "standard")
    if preset != CUSTOM and preset not in PRESETS:
        preset = "standard"
    custom = {mode: {} for mode in (LIGHT, DARK)}
    for mode in custom:
        for role in ROLES:
            value = settings.value(f"colors/custom/{mode}/{role}", "")
            if QColor.isValidColorName(value):
                custom[mode][role] = value
    return preset, custom


def save(preset: str, custom: dict[str, dict[str, str]]) -> None:
    settings = app_settings()
    settings.setValue("colors/preset", preset)
    settings.remove("colors/custom")  # so a reset doesn't leave old picks behind
    for mode, colors in custom.items():
        for role, value in colors.items():
            settings.setValue(f"colors/custom/{mode}/{role}", value)
    reload()


def resolve(preset: str, custom: dict[str, dict[str, str]], mode: str) -> dict[str, str]:
    # custom colors fall back to the standard ones for anything not picked yet
    colors = preset_colors("standard" if preset == CUSTOM else preset, mode)
    if preset == CUSTOM:
        colors.update(custom.get(mode, {}))
    return colors


def reload() -> None:
    _cache.clear()


def _palette() -> dict[str, QColor]:
    mode = current_mode()
    if mode not in _cache:
        _cache[mode] = {role: QColor(value) for role, value in resolve(*load(), mode).items()}
    return _cache[mode]


def amount_color(cents: int) -> QColor:
    return _palette()["income" if cents > 0 else "expense"]


def budget_color(level: str) -> str:
    return _palette()[_LEVEL_ROLES[level]].name()


def chart_color(role: str) -> QColor:
    if role in ("income", "spending"):
        return _palette()[f"chart_{role}"]
    # titles and axes follow how dark the background actually is, custom or not
    window = QGuiApplication.palette().color(QPalette.ColorRole.Window)
    return QColor(_CHART_CHROME[role][1 if is_dark(window) else 0])


# --- background: separate from the presets, one optional color per light/dark mode ---


def load_backgrounds() -> dict[str, str]:
    # mode -> hex, or "" for the theme's own background
    settings = app_settings()
    values = {mode: settings.value(f"colors/background/{mode}", "") for mode in (LIGHT, DARK)}
    return {mode: value if QColor.isValidColorName(value) else "" for mode, value in values.items()}


def save_backgrounds(backgrounds: dict[str, str]) -> None:
    settings = app_settings()
    for mode, value in backgrounds.items():
        settings.setValue(f"colors/background/{mode}", value)


def is_dark(color: QColor) -> bool:
    # dark when white text would read better on it than black
    return contrast(color, QColor("white")) > contrast(color, QColor("black"))


def text_color_for(background: QColor) -> QColor:
    return QColor("white") if is_dark(background) else QColor("black")


_theme_style: str | None = None  # the platform's own style (windows11), to switch back to


def apply_background(app) -> None:
    # paints the chosen background for the current mode, or goes back to the theme's own look
    global _theme_style
    if _theme_style is None:
        _theme_style = app.style().name()
    value = load_backgrounds()[current_mode()]
    if not value:
        app.setStyle(_theme_style)
        app.setPalette(QPalette())  # an empty palette follows the system theme again
        return

    # the windows 11 style keeps its own light buttons and headers whatever the palette says,
    # so a custom background uses fusion, qt's style that draws everything from the palette
    base = QColor(value)
    text = text_color_for(base)
    window = base.darker(106) if text == QColor("black") else base.lighter(125)  # a touch of depth
    palette = QPalette(window)  # qt works out every other shade (borders, bevels, disabled) from this
    muted = QColor(text)
    muted.setAlphaF(0.55)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.Window, window)
        palette.setColor(group, QPalette.ColorRole.Button, window)
        palette.setColor(group, QPalette.ColorRole.Base, base)
        palette.setColor(group, QPalette.ColorRole.AlternateBase, window)
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(group, role, text)
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, muted)
    app.setStyle("Fusion")
    app.setPalette(palette)  # after setStyle, which would otherwise swap in its own palette


def contrast(a: QColor, b: QColor) -> float:
    # wcag contrast ratio: 1 (same) to 21 (black on white)
    def luminance(c: QColor) -> float:
        def channel(v: float) -> float:
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        return 0.2126 * channel(c.redF()) + 0.7152 * channel(c.greenF()) + 0.0722 * channel(c.blueF())

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readability_warning(role: str, color: QColor, background: QColor) -> str:
    # empty when fine, otherwise a short note for the colors dialog
    needed = 4.5 if ROLES[role][1] else 3.0
    ratio = contrast(color, background)
    return "" if ratio >= needed else f"Hard to see on this background ({ratio:.1f}:1, aim for {needed:g}:1)"


def bar_style(fill: str) -> str:
    # budget progress bar look; the grey track works in light and dark
    return (
        "QProgressBar { border: none; border-radius: 4px; background: rgba(128, 128, 128, 60); margin: 6px 4px; }"
        f"QProgressBar::chunk {{ border-radius: 4px; background: {fill}; }}"
    )
