from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from budget_tracker.ui.colors import (
    CUSTOM,
    DARK,
    LIGHT,
    PRESETS,
    ROLES,
    bar_style,
    current_mode,
    load,
    load_backgrounds,
    readability_warning,
    resolve,
    save,
    save_backgrounds,
    text_color_for,
)


class ColorsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Colors")
        self.mode = current_mode()  # custom colors are edited per light/dark mode
        self.preset, self.custom = load()
        self.backgrounds = load_backgrounds()  # separate from the presets, "" = theme default

        # preset picker
        self.preset_box = QComboBox()
        for key, (label, _colors) in PRESETS.items():
            self.preset_box.addItem(label, key)
        self.preset_box.addItem("Custom", CUSTOM)
        self.preset_box.currentIndexChanged.connect(self._preset_chosen)
        mode_note = QLabel(
            f"These are the colors for {self.mode} mode. Light and dark mode keep their own custom colors, "
            "so text stays readable in both. Switch Settings → Theme to edit the other one."
        )
        mode_note.setWordWrap(True)

        # background first, since the other colors are checked against it
        self.background_swatch = QPushButton()
        self.background_swatch.setFixedSize(72, 24)
        self.background_swatch.setAccessibleName("Change background color")
        self.background_swatch.clicked.connect(self.pick_background)
        self.background_default = QPushButton("Theme default")
        self.background_default.clicked.connect(self.default_background)

        # one clickable swatch per color, with a warning when it's hard to see
        self.swatches: dict[str, QPushButton] = {}
        self.warnings: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.addWidget(QLabel("Background"), 0, 0)
        grid.addWidget(self.background_swatch, 0, 1)
        grid.addWidget(self.background_default, 0, 2)
        for row, (role, (label, _is_text)) in enumerate(ROLES.items(), start=1):
            swatch = QPushButton()
            swatch.setFixedSize(72, 24)
            swatch.setAccessibleName(f"Change {label.lower()} color")
            swatch.clicked.connect(lambda _checked, r=role: self.pick(r))
            warning = QLabel()
            warning.setWordWrap(True)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(swatch, row, 1)
            grid.addWidget(warning, row, 2)
            self.swatches[role], self.warnings[role] = swatch, warning
        grid.setColumnStretch(2, 1)

        # live preview of amounts and budget bars
        self.income_sample = QLabel("$1,625.00  paycheck")
        self.expense_sample = QLabel("-$42.17  groceries")
        self.bars = {}
        preview = QFormLayout()
        preview.addRow("Amounts:", self.income_sample)
        preview.addRow("", self.expense_sample)
        for role, value, label in (
            ("budget_ok", 54, "Under"),
            ("budget_near", 87, "Near limit"),
            ("budget_over", 100, "Over"),
        ):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(value)
            bar.setTextVisible(False)
            bar.setFixedHeight(22)
            self.bars[role] = bar
            preview.addRow(f"{label}:", bar)
        self.preview_box = QGroupBox("Preview")
        self.preview_box.setLayout(preview)
        self.preview_box.setAutoFillBackground(True)  # so it can show the chosen background

        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self.reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton(reset, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Preset:", self.preset_box)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(mode_note)
        layout.addLayout(grid)
        layout.addWidget(self.preview_box)
        layout.addWidget(buttons)
        self.refresh()

    def colors(self) -> dict[str, str]:
        return resolve(self.preset, self.custom, self.mode)

    def _start_custom(self) -> None:
        # copies what's showing in both modes, so the other mode keeps its look until edited
        if self.preset != CUSTOM:
            for mode in (LIGHT, DARK):
                self.custom[mode] = resolve(self.preset, self.custom, mode)
            self.preset = CUSTOM

    def _preset_chosen(self) -> None:
        key = self.preset_box.currentData()
        if key == CUSTOM:
            self._start_custom()
        else:
            self.preset = key
        self.refresh()

    def pick(self, role: str) -> None:
        label = ROLES[role][0]
        color = QColorDialog.getColor(QColor(self.colors()[role]), self, f"Choose a color: {label}")
        if not color.isValid():
            return  # cancelled
        self._start_custom()
        self.custom[self.mode][role] = color.name()
        self.refresh()

    def pick_background(self) -> None:
        color = QColorDialog.getColor(self.background(), self, "Choose a color: Background")
        if color.isValid():
            self.backgrounds[self.mode] = color.name()
            self.refresh()

    def default_background(self) -> None:
        self.backgrounds[self.mode] = ""
        self.refresh()

    def background(self) -> QColor:
        # the chosen background, or what tables and lists sit on in the current theme
        chosen = self.backgrounds[self.mode]
        return QColor(chosen) if chosen else QApplication.palette().color(QPalette.ColorRole.Base)

    def reset(self) -> None:
        self.preset = "standard"
        self.custom = {LIGHT: {}, DARK: {}}
        self.backgrounds = {LIGHT: "", DARK: ""}
        self.refresh()

    def refresh(self) -> None:
        colors = self.colors()
        background = self.background()
        self.background_swatch.setStyleSheet(
            f"background: {background.name()}; border: 1px solid rgba(128, 128, 128, 160);"
        )
        self.background_swatch.setToolTip(background.name())
        self.background_default.setEnabled(bool(self.backgrounds[self.mode]))
        preview_palette = self.preview_box.palette()
        preview_palette.setColor(QPalette.ColorRole.Window, background)
        preview_palette.setColor(QPalette.ColorRole.WindowText, text_color_for(background))
        self.preview_box.setPalette(preview_palette)
        self.preset_box.blockSignals(True)
        self.preset_box.setCurrentIndex(self.preset_box.findData(self.preset))
        self.preset_box.blockSignals(False)

        for role, swatch in self.swatches.items():
            swatch.setStyleSheet(f"background: {colors[role]}; border: 1px solid rgba(128, 128, 128, 160);")
            swatch.setToolTip(colors[role])
            self.warnings[role].setText(readability_warning(role, QColor(colors[role]), background))

        self.income_sample.setStyleSheet(f"color: {colors['income']};")
        self.expense_sample.setStyleSheet(f"color: {colors['expense']};")
        for role, bar in self.bars.items():
            bar.setStyleSheet(bar_style(colors[role]))

    def accept(self) -> None:
        save(self.preset, self.custom)
        save_backgrounds(self.backgrounds)
        super().accept()
