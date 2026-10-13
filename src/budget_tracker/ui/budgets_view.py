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
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from budget_tracker.models import Category
from budget_tracker.services.budgets import NEAR, OVER, BudgetError, BudgetLine, BudgetService
from budget_tracker.services.categories import CategoryService
from budget_tracker.services.money import format_cents
from budget_tracker.ui.colors import bar_style, budget_color
from budget_tracker.ui.reading import fit_columns, stripe
from budget_tracker.ui.settings import month_label

COLUMNS = ["Category", "Progress", "Used", "Spent", "Limit", "Left"]
STATUS_WORDS = {NEAR: "near limit", OVER: "over budget"}


class BudgetDialog(QDialog):
    """Category + monthly limit. When editing, the category is fixed."""

    def __init__(self, parent, title, categories: list[Category], service: BudgetService, line: BudgetLine | None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.service = service
        self.category = QComboBox()
        for c in categories:
            self.category.addItem(c.name, c.id)
        self.limit = QLineEdit()
        self.limit.setPlaceholderText("400")
        if line:
            self.category.setCurrentIndex(self.category.findData(line.category_id))
            self.category.setEnabled(False)
            self.limit.setText(format_cents(line.limit_cents))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout(self)
        form.addRow("Category:", self.category)
        form.addRow("Monthly limit:", self.limit)
        form.addRow(buttons)

    def accept(self):
        try:
            self.service.set_limit(self.category.currentData(), self.limit.text())
        except BudgetError as e:
            QMessageBox.warning(self, "Can't save budget", str(e))
            return
        super().accept()


class BudgetsView(QWidget):
    def __init__(self, budgets: BudgetService, categories: CategoryService):
        super().__init__()
        self.budgets = budgets
        self.categories = categories
        self.lines: list[BudgetLine] = []

        self.month = QComboBox()
        self.month.currentIndexChanged.connect(self.reload_table)
        self.add_btn = QPushButton("Set budget…")
        self.edit_btn = QPushButton("Edit…")
        self.remove_btn = QPushButton("Remove")
        self.add_btn.clicked.connect(self.add)
        self.edit_btn.clicked.connect(self.edit)
        self.remove_btn.clicked.connect(self.remove)

        self.summary = QLabel()
        self.table = QTableWidget(0, len(COLUMNS))
        stripe(self.table)
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        fit_columns(self.table, stretch=1)  # the progress bar takes the spare width
        self.table.doubleClicked.connect(self.edit)
        self.table.itemSelectionChanged.connect(self.update_buttons)

        bar = QHBoxLayout()
        for b in (self.add_btn, self.edit_btn, self.remove_btn):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(QLabel("Month:"))
        bar.addWidget(self.month)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.summary)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        current = self.month.currentData()
        self.month.blockSignals(True)
        self.month.clear()
        for m in self.budgets.months():
            self.month.addItem(month_label(m), m)
        self.month.setCurrentIndex(max(0, self.month.findData(current)))  # defaults to the newest month
        self.month.blockSignals(False)
        self.reload_table()

    def reload_table(self) -> None:
        self.lines = self.budgets.lines(self.month.currentData())
        self.table.setRowCount(len(self.lines))
        for row, line in enumerate(self.lines):
            left = f"{format_cents(-line.left_cents)} over" if line.left_cents < 0 else format_cents(line.left_cents)
            used = f"{line.fraction:.0%}"  # the real percentage, even past 100%
            if status := STATUS_WORDS.get(line.level):  # says it in words too, never colour alone
                used += f"  ·  {status}"
            cells = [line.category, "", used, format_cents(line.spent_cents), format_cents(line.limit_cents), left]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)
            self.table.setCellWidget(row, 1, _progress_bar(line))

        spent = sum(line.spent_cents for line in self.lines)
        limit = sum(line.limit_cents for line in self.lines)
        self.summary.setText(
            f"Total: {format_cents(spent)} of {format_cents(limit)} budgeted"
            if self.lines
            else "No budgets yet. Click “Set budget…” to give a category a monthly limit."
        )
        self.update_buttons()

    def update_buttons(self) -> None:
        has_selection = self.selected() is not None
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)
        self.add_btn.setEnabled(bool(self._unbudgeted()))

    def selected(self) -> BudgetLine | None:
        rows = self.table.selectionModel().selectedRows()
        return self.lines[rows[0].row()] if rows else None

    def _unbudgeted(self) -> list[Category]:
        budgeted = {line.category_id for line in self.lines}
        return [c for c in self.categories.list() if c.id not in budgeted]

    def add(self) -> None:
        if BudgetDialog(self, "Set budget", self._unbudgeted(), self.budgets, None).exec():
            self.reload_table()

    def edit(self) -> None:
        if not (line := self.selected()):
            return
        if BudgetDialog(self, "Edit budget", self.categories.list(), self.budgets, line).exec():
            self.reload_table()

    def remove(self) -> None:
        if not (line := self.selected()):
            return
        answer = QMessageBox.question(self, "Remove budget", f'Remove the monthly budget for "{line.category}"?')
        if answer == QMessageBox.StandardButton.Yes:
            self.budgets.remove(line.category_id)
            self.reload_table()


def _progress_bar(line: BudgetLine) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(min(100, round(line.fraction * 100)))
    bar.setTextVisible(False)  # no text colour reads well on both the fill and the track; see the Used column
    bar.setStyleSheet(bar_style(budget_color(line.level)))
    return bar
