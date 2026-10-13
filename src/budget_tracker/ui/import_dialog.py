from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from budget_tracker.models import BankProfile
from budget_tracker.services.csv_import import (
    DUPLICATE,
    ERROR,
    NEW,
    CsvImportError,
    ImportService,
    ParsedRow,
    guess_header_row,
    guess_profile,
    header_of,
)
from budget_tracker.services.money import format_cents
from budget_tracker.ui.colors import amount_color
from budget_tracker.ui.reading import fit_columns, stripe
from budget_tracker.ui.settings import date_format

NEW_PROFILE = "(New profile)"


class ImportDialog(QDialog):
    """Map a CSV's columns, preview the result, then import. Every settings change re-runs the preview."""

    def __init__(
        self, parent, service: ImportService, path: Path, rows: list[list[str]], category_names: dict[int, str]
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Import {path.name}")
        self.resize(900, 600)
        self.service = service
        self.rows = rows
        self.category_names = category_names
        self.parsed: list[ParsedRow] = []
        self.imported = 0
        self._loading = False  # true while _apply fills widgets, so each change doesn't re-preview

        self.profile = QComboBox()
        self.profile.addItem(NEW_PROFILE, None)
        for p in service.list_profiles():
            self.profile.addItem(p.name, p)
        # Which line holds the column names, counted from 1 like a person would. Bank profiles store
        # it as "rows above the header" (line 1 = 0 rows above), so saved profiles keep working.
        self.header_line = QSpinBox()
        self.header_line.setRange(1, max(1, len(rows)))
        self.header_line.setToolTip(
            "Some banks put account details above the table. Pick the line that has the column names "
            "(like Date, Description, Amount). SkimWise usually finds it for you."
        )
        self.header_found = QLabel()  # the column names on that line, so a wrong pick is obvious
        self.header_found.setWordWrap(True)
        self.date_col, self.desc_col, self.amount_col, self.debit_col, self.credit_col = (QComboBox() for _ in range(5))
        self.single = QRadioButton("One amount column")
        self.split = QRadioButton("Separate debit and credit columns")
        self.flip = QCheckBox("Expenses are positive numbers (flip signs)")
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("e.g. Chase Checking (leave blank to not save)")

        self.summary = QLabel()
        self.table = QTableWidget(0, 5)
        stripe(self.table)
        self.table.setHorizontalHeaderLabels(["Status", "Date", "Description", "Category", "Amount"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        fit_columns(self.table, stretch=2)  # description

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_btn = buttons.addButton("Import", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.profile.currentIndexChanged.connect(self._profile_chosen)
        self.header_line.valueChanged.connect(self._header_line_changed)
        for w in (self.date_col, self.desc_col, self.amount_col, self.debit_col, self.credit_col):
            w.currentIndexChanged.connect(self.update_preview)
        self.single.toggled.connect(self.update_preview)
        self.flip.toggled.connect(self.update_preview)

        amount_modes = QHBoxLayout()
        amount_modes.addWidget(self.single)
        amount_modes.addWidget(self.split)
        amount_modes.addStretch()
        debit_credit = QHBoxLayout()
        debit_credit.addWidget(QLabel("Debit:"))
        debit_credit.addWidget(self.debit_col, 1)
        debit_credit.addWidget(QLabel("Credit:"))
        debit_credit.addWidget(self.credit_col, 1)

        form = QFormLayout()
        form.addRow("Bank profile:", self.profile)
        form.addRow("Column names are on line:", self.header_line)
        form.addRow("", self.header_found)
        form.addRow("Date column:", self.date_col)
        form.addRow("Description column:", self.desc_col)
        form.addRow("Amount:", amount_modes)
        form.addRow("Amount column:", self.amount_col)
        form.addRow("", debit_credit)
        form.addRow("", self.flip)
        form.addRow("Save as profile:", self.profile_name)

        if path.suffix.lower() == ".pdf":  # a PDF statement always arrives with its column names on line 1
            form.setRowVisible(self.header_line, False)
            form.setRowVisible(self.header_found, False)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.summary)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

        # Start from a saved profile that fits this file, else from guesses.
        match = service.matching_profile(rows)
        if match:
            self.profile.setCurrentIndex(self.profile.findText(match.name))  # triggers _apply
        else:
            skip = guess_header_row(rows)
            self._apply(guess_profile(header_of(rows, skip), skip))

    # --- widgets <-> BankProfile ---

    def _apply(self, p: BankProfile) -> None:
        self._loading = True
        self.header_line.setValue(p.skip_rows + 1)
        self._fill_columns()
        for combo, name in (
            (self.date_col, p.date_col),
            (self.desc_col, p.description_col),
            (self.amount_col, p.amount_col),
            (self.debit_col, p.debit_col),
            (self.credit_col, p.credit_col),
        ):
            combo.setCurrentIndex(max(0, combo.findData(name)))
        (self.split if (p.debit_col or p.credit_col) and not p.amount_col else self.single).setChecked(True)
        self.flip.setChecked(p.flip_sign)
        self.profile_name.setText(p.name)
        self._loading = False
        self.update_preview()

    def current_profile(self) -> BankProfile:
        single = self.single.isChecked()
        return BankProfile(
            name=self.profile_name.text(),
            skip_rows=self._skip_rows(),
            date_col=self.date_col.currentData(),
            description_col=self.desc_col.currentData(),
            amount_col=self.amount_col.currentData() if single else "",
            debit_col="" if single else self.debit_col.currentData(),
            credit_col="" if single else self.credit_col.currentData(),
            flip_sign=single and self.flip.isChecked(),
        )

    def _fill_columns(self) -> None:
        """Column choices come from the header line, which moves when the user picks another line."""
        header = header_of(self.rows, self._skip_rows())
        names = [h for h in header if h]
        self.header_found.setText(
            f"Found: {'  ·  '.join(names)}" if names else "That line is empty. Pick the line with the column names."
        )
        for combo in (self.date_col, self.desc_col, self.amount_col, self.debit_col, self.credit_col):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("—", "")
            for name in header:
                combo.addItem(name, name)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

    def _profile_chosen(self) -> None:
        p = self.profile.currentData()
        if p:
            self._apply(p)

    def _skip_rows(self) -> int:
        return self.header_line.value() - 1

    def _header_line_changed(self) -> None:
        # A different header line means different column names: re-guess them, keep the rest.
        if not self._loading:
            current = self.current_profile()
            guess = guess_profile(header_of(self.rows, self._skip_rows()), self._skip_rows())
            self._apply(replace(guess, name=current.name, flip_sign=current.flip_sign))

    # --- preview ---

    def update_preview(self) -> None:
        if self._loading:
            return
        single = self.single.isChecked()
        self.amount_col.setEnabled(single)
        self.flip.setEnabled(single)
        self.debit_col.setEnabled(not single)
        self.credit_col.setEnabled(not single)

        try:
            self.parsed = self.service.preview(self.rows, self.current_profile())
        except CsvImportError as e:
            self.parsed = []
            self.summary.setText(str(e))
        else:
            counts = {s: sum(r.status == s for r in self.parsed) for s in (NEW, DUPLICATE, ERROR)}
            self.summary.setText(
                f"{counts[NEW]} new · {counts[DUPLICATE]} already imported (skipped) · "
                f"{counts[ERROR]} unreadable (skipped)"
            )

        fmt = date_format()
        self.table.setRowCount(len(self.parsed))
        for i, r in enumerate(self.parsed):
            status = {NEW: "New", DUPLICATE: "Duplicate"}.get(r.status, f"Row {r.row_number}: {r.error}")
            cells = [status, "", "", "", ""]
            if r.tx:
                category = self.category_names.get(r.tx.category_id, "Uncategorized")
                cells[1:] = [r.tx.date.strftime(fmt), r.tx.description, category, format_cents(r.tx.amount_cents)]
            for col, text in enumerate(cells):
                self.table.setItem(i, col, QTableWidgetItem(text))
            if r.tx:
                self.table.item(i, 4).setForeground(amount_color(r.tx.amount_cents))
        self.import_btn.setEnabled(any(r.status == NEW for r in self.parsed))

    def accept(self):
        if not any(r.status == NEW for r in self.parsed):
            return  # the Import button is disabled in this state; this is just a backstop
        profile = self.current_profile()
        if profile.name.strip():
            try:
                self.service.save_profile(profile)
            except CsvImportError as e:
                QMessageBox.warning(self, "Can't save profile", str(e))
                return
        self.imported = self.service.commit(self.parsed)
        super().accept()
