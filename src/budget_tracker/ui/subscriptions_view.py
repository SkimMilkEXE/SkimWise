from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_tracker.models import MONTHLY, YEARLY, RecurringItem
from budget_tracker.services.money import count, format_cents
from budget_tracker.services.recurring_detection import Candidate, RecurringError, RecurringService, totals
from budget_tracker.ui.reading import fit_columns, stripe
from budget_tracker.ui.settings import date_format

FREQUENCY_LABELS = {MONTHLY: "Monthly", YEARLY: "Yearly"}


class RecurringDialog(QDialog):
    """Name + amount + frequency. `on_save(name, amount, frequency)` saves; on RecurringError
    the message is shown and the dialog stays open."""

    def __init__(self, parent, title, on_save, item: RecurringItem | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.on_save = on_save
        self.name = QLineEdit(item.name if item else "")
        self.amount = QLineEdit(format_cents(item.amount_cents) if item else "")
        self.amount.setPlaceholderText("15.49")
        self.frequency = QComboBox()
        for key, label in FREQUENCY_LABELS.items():
            self.frequency.addItem(label, key)
        if item:
            self.frequency.setCurrentIndex(self.frequency.findData(item.frequency))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow("Name:", self.name)
        form.addRow("Amount per charge:", self.amount)
        form.addRow("Charged:", self.frequency)
        form.addRow(buttons)

    def accept(self):
        try:
            self.on_save(self.name.text(), self.amount.text(), self.frequency.currentData())
        except RecurringError as e:
            QMessageBox.warning(self, "Can't save", str(e))
            return
        super().accept()


class SubscriptionsView(QWidget):
    def __init__(self, service: RecurringService):
        super().__init__()
        self.service = service
        self.items: list[RecurringItem] = []
        self.candidates: list[Candidate] = []

        # Your list
        self.total = QLabel()
        font = self.total.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        self.total.setFont(font)
        add_btn = QPushButton("Add…")
        self.edit_btn = QPushButton("Edit…")
        self.remove_btn = QPushButton("Remove")
        add_btn.clicked.connect(self.add)
        self.edit_btn.clicked.connect(self.edit)
        self.remove_btn.clicked.connect(self.remove)
        self.table = _table(["Name", "Charged", "Amount", "Per month", "Per year"])
        self.table.doubleClicked.connect(self.edit)
        self.table.itemSelectionChanged.connect(self.update_buttons)

        # Suggestions
        self.suggest_title = QLabel()
        self.confirm_btn = QPushButton("Confirm")
        self.dismiss_btn = QPushButton("Not recurring")
        self.redetect_btn = QPushButton("Re-detect…")
        self.confirm_btn.clicked.connect(self.confirm)
        self.dismiss_btn.clicked.connect(self.dismiss)
        self.redetect_btn.clicked.connect(self.redetect)
        self.suggestions = _table(["Merchant", "Looks like", "Last amount", "Times seen", "Last charged"])
        self.suggestions.doubleClicked.connect(self.confirm)
        self.suggestions.itemSelectionChanged.connect(self.update_buttons)

        top = QHBoxLayout()
        top.addWidget(self.total)
        top.addStretch()
        for b in (add_btn, self.edit_btn, self.remove_btn):
            top.addWidget(b)
        suggest_bar = QHBoxLayout()
        suggest_bar.addWidget(self.suggest_title)
        suggest_bar.addStretch()
        suggest_bar.addWidget(self.confirm_btn)
        suggest_bar.addWidget(self.dismiss_btn)
        suggest_bar.addWidget(self.redetect_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 3)
        layout.addLayout(suggest_bar)
        layout.addWidget(self.suggestions, 2)

        self.refresh()

    def refresh(self) -> None:
        self.items = self.service.items()
        monthly, yearly = totals(self.items)
        self.total.setText(f"{format_cents(monthly)} / month  ·  {format_cents(yearly)} / year")
        _fill(
            self.table,
            [
                [i.name, FREQUENCY_LABELS[i.frequency], i.amount_cents, round(i.yearly_cents / 12), i.yearly_cents]
                for i in self.items
            ],
        )

        self.candidates = self.service.suggestions()
        fmt = date_format()
        self.suggest_title.setText(
            f"Detected in your transactions ({len(self.candidates)}): confirm to add to your list"
            if self.candidates
            else "Nothing new detected. Recurring charges appear here after a few months of transactions."
        )
        _fill(
            self.suggestions,
            [
                [c.name, FREQUENCY_LABELS[c.frequency], c.amount_cents, str(c.count), c.last_date.strftime(fmt)]
                for c in self.candidates
            ],
        )
        hidden = self.service.dismissed_count()
        self.redetect_btn.setEnabled(hidden > 0)
        self.redetect_btn.setToolTip(
            f'Show the {count(hidden, "merchant")} you marked "Not recurring" as suggestions again.'
            if hidden
            else "Nothing is hidden: every detected subscription is already shown."
        )
        self.update_buttons()

    def update_buttons(self) -> None:
        for b in (self.edit_btn, self.remove_btn):
            b.setEnabled(self._selected(self.table, self.items) is not None)
        for b in (self.confirm_btn, self.dismiss_btn):
            b.setEnabled(self._selected(self.suggestions, self.candidates) is not None)

    @staticmethod
    def _selected(table: QTableWidget, rows: list):
        selected = table.selectionModel().selectedRows()
        return rows[selected[0].row()] if selected else None

    def add(self) -> None:
        if RecurringDialog(self, "Add recurring payment", self.service.add).exec():
            self.refresh()

    def edit(self) -> None:
        if not (item := self._selected(self.table, self.items)):
            return

        def save(name, amount, frequency):
            self.service.update(item.id, name, amount, frequency)

        if RecurringDialog(self, "Edit recurring payment", save, item).exec():
            self.refresh()

    def remove(self) -> None:
        if not (item := self._selected(self.table, self.items)):
            return
        if (
            QMessageBox.question(self, "Remove", f'Remove "{item.name}" from your list?')
            == QMessageBox.StandardButton.Yes
        ):
            self.service.remove(item.id)
            self.refresh()

    def confirm(self) -> None:
        if c := self._selected(self.suggestions, self.candidates):
            self.service.confirm(c)
            self.refresh()

    def dismiss(self) -> None:
        if c := self._selected(self.suggestions, self.candidates):
            self.service.dismiss(c)
            self.refresh()

    def redetect(self) -> None:
        hidden = self.service.dismissed_count()
        answer = QMessageBox.question(
            self,
            "Re-detect subscriptions",
            f'You\'ve marked {count(hidden, "merchant")} as "Not recurring". Look for them again?\n\n'
            "Any that still look recurring will reappear as suggestions. Your confirmed list isn't changed.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.service.redetect()
            self.refresh()


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    stripe(table)
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().hide()
    fit_columns(table, stretch=0)  # name
    return table


def _fill(table: QTableWidget, rows: list[list]) -> None:
    """Fill a table; int cells are cents, shown as money and right-aligned. Counts (digit strings) are centred."""
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(format_cents(value) if isinstance(value, int) else value)
            if isinstance(value, int):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif value.isdigit():
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(r, c, item)
