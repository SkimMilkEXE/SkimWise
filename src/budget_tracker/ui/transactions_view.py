from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, QRect, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from budget_tracker.models import EXPENSE, INCOME, NO_CATEGORY, Transaction
from budget_tracker.services.categories import CategoryService
from budget_tracker.services.csv_import import CsvImportError, ImportService, read_rows
from budget_tracker.services.money import count, format_cents
from budget_tracker.services.pdf_import import read_statement
from budget_tracker.services.rules import RuleService, suggest_pattern
from budget_tracker.services.transactions import TransactionError, TransactionService, totals
from budget_tracker.ui.colors import amount_color
from budget_tracker.ui.import_dialog import ImportDialog
from budget_tracker.ui.reading import fit_columns, highlight_style, row_highlight, stripe
from budget_tracker.ui.rules_view import RuleDialog
from budget_tracker.ui.settings import date_format, month_label, qt_date_format

UNCATEGORIZED = "Uncategorized"
HIGHLIGHT_ROLE = Qt.ItemDataRole.UserRole + 1  # the strip color for a row, or None
STRIP_SPACE_ROLE = Qt.ItemDataRole.UserRole + 2  # true when strips are on, so every date lines up
TINT_STRENGTH = 0.08  # strongest tint that keeps amount text at 4.5:1 in every preset and mode
STRIP_WIDTH = 4
STRIP_GAP = 4  # space between the strip and the text


class TransactionTableModel(QAbstractTableModel):
    """Model/view: the model owns the rows and answers "what goes in cell (r, c)?";
    QTableView just asks and draws. Qt calls data() once per cell per *role*:
    DisplayRole is the text, UserRole is our raw value used for sorting."""

    HEADERS = ["Date", "Description", "Category", "Amount"]

    def __init__(self):
        super().__init__()
        self.rows: list[Transaction] = []
        self.category_names: dict[int, str] = {}
        self.date_format = "%Y-%m-%d"
        self.highlight, self.style = "none", "tint"

    def set_rows(self, rows: list[Transaction], category_names: dict[int, str], date_format: str) -> None:
        self.beginResetModel()  # tells attached views to drop everything and re-ask
        self.rows, self.category_names, self.date_format = rows, category_names, date_format
        self.highlight, self.style = row_highlight(), highlight_style()  # read once, not per cell
        self.endResetModel()

    def _highlight_color(self, tx: Transaction) -> QColor | None:
        # income rows stand out, and expense rows too when chosen; colors follow the user's choices
        if self.highlight == "none" or (self.highlight == "income" and tx.amount_cents < 0):
            return None
        return amount_color(tx.amount_cents)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        tx = self.rows[index.row()]
        col = index.column()
        category = self.category_names.get(tx.category_id, UNCATEGORIZED)
        if role == Qt.ItemDataRole.DisplayRole:
            return [tx.date.strftime(self.date_format), tx.description, category, format_cents(tx.amount_cents)][col]
        if role == Qt.ItemDataRole.UserRole:
            return [tx.date.isoformat(), tx.description.lower(), category.lower(), tx.amount_cents][col]
        if role == Qt.ItemDataRole.ForegroundRole and col == 3:
            return amount_color(tx.amount_cents)
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 3:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.BackgroundRole and self.style == "tint":
            if color := self._highlight_color(tx):
                tint = QColor(color)
                tint.setAlphaF(TINT_STRENGTH)
                return tint  # wins over striped rows
        if role == HIGHLIGHT_ROLE and self.style == "strip":
            return self._highlight_color(tx)
        if role == STRIP_SPACE_ROLE:
            return self.style == "strip" and self.highlight != "none"
        return None


class StripDelegate(QStyledItemDelegate):
    # draws a thin colored bar down the cell's left edge, with the text moved over to make room
    def paint(self, painter, option, index):
        if not index.data(STRIP_SPACE_ROLE):
            super().paint(painter, option, index)
            return
        # background first (selection, stripes) across the whole cell, then the text shifted right
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        style = background.widget.style() if background.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, background, painter, background.widget)
        shifted = QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(STRIP_WIDTH + STRIP_GAP, 0, 0, 0)
        super().paint(painter, shifted, index)
        if color := index.data(HIGHLIGHT_ROLE):  # only highlighted rows get the bar
            rect = option.rect
            painter.fillRect(QRect(rect.left(), rect.top(), STRIP_WIDTH, rect.height()), color)

    def sizeHint(self, option, index):
        # room for the strip, so the column sized to its contents doesn't cut the date off
        size = super().sizeHint(option, index)
        size.setWidth(size.width() + STRIP_WIDTH + STRIP_GAP)
        return size


class TransactionDialog(QDialog):
    """Add/edit form. `on_save(**values)` does the saving; if it raises
    TransactionError the message is shown and the dialog stays open."""

    def __init__(self, parent, title, categories, on_save, tx: Transaction | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.on_save = on_save

        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat(qt_date_format())
        self.kind = QComboBox()
        self.kind.addItems(["Expense", "Income"])
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("12.34")
        self.description = QLineEdit()
        self.category = QComboBox()
        self.category.addItem(UNCATEGORIZED, None)
        for c in categories:
            self.category.addItem(c.name, c.id)

        if tx:
            self.date.setDate(QDate(tx.date.year, tx.date.month, tx.date.day))
            self.kind.setCurrentIndex(0 if tx.amount_cents < 0 else 1)
            self.amount.setText(format_cents(abs(tx.amount_cents)))
            self.description.setText(tx.description)
            self.category.setCurrentIndex(max(0, self.category.findData(tx.category_id)))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Date:", self.date)
        form.addRow("Type:", self.kind)
        form.addRow("Amount:", self.amount)
        form.addRow("Description:", self.description)
        form.addRow("Category:", self.category)
        form.addRow(buttons)

    def accept(self):
        try:
            self.on_save(
                when=self.date.date().toPython(),
                description=self.description.text(),
                amount=self.amount.text(),
                is_expense=self.kind.currentIndex() == 0,
                category_id=self.category.currentData(),
            )
        except TransactionError as e:
            QMessageBox.warning(self, "Can't save transaction", str(e))
            return
        super().accept()


class TransactionsView(QWidget):
    def __init__(
        self, transactions: TransactionService, categories: CategoryService, importer: ImportService, rules: RuleService
    ):
        super().__init__()
        self.transactions = transactions
        self.categories = categories
        self.importer = importer
        self.rules = rules

        # Filter bar
        self.month = QComboBox()
        self.category = QComboBox()
        self.kind = QComboBox()
        for label, value in (("All types", None), ("Income", INCOME), ("Expenses", EXPENSE)):
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(self.reload_table)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search descriptions…")
        self.search.setClearButtonEnabled(True)
        self.month.currentIndexChanged.connect(self.reload_table)
        self.category.currentIndexChanged.connect(self.reload_table)
        self.search.textChanged.connect(self.reload_table)

        # Action buttons
        import_btn = QPushButton("Import…")
        add_btn = QPushButton("Add…")
        self.edit_btn = QPushButton("Edit…")
        self.set_category_btn = QPushButton("Set category…")
        self.delete_btn = QPushButton("Delete")
        import_btn.clicked.connect(self.import_csv)
        add_btn.clicked.connect(self.add)
        self.edit_btn.clicked.connect(self.edit)
        self.set_category_btn.clicked.connect(self.set_category)
        self.delete_btn.clicked.connect(self.delete)

        # Table: view -> proxy (sorting on header click) -> model (our data)
        self.model = TransactionTableModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)  # sort by raw values, not display text
        self.table = QTableView()
        stripe(self.table)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Ctrl+click / Shift+click select several rows for Set category or Delete.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        fit_columns(self.table, stretch=1)  # description
        self.table.setItemDelegateForColumn(0, StripDelegate(self.table))
        self.table.doubleClicked.connect(self.edit)
        self.table.selectionModel().selectionChanged.connect(self.update_buttons)

        bar = QHBoxLayout()
        for w in (import_btn, add_btn, self.edit_btn, self.set_category_btn, self.delete_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.month)
        bar.addWidget(self.category)
        bar.addWidget(self.kind)
        bar.addWidget(self.search)

        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.table)
        self.summary = QLabel()  # totals for the rows the filters show
        layout.addWidget(self.summary)

        self.refresh()

    def refresh(self) -> None:
        """Reload filter choices (categories/months may have changed) and the table."""
        self._category_list = self.categories.list()
        _refill(self.month, "All months", [(month_label(m), m) for m in self.transactions.months()])
        categories = [(UNCATEGORIZED, NO_CATEGORY)] + [(c.name, c.id) for c in self._category_list]
        _refill(self.category, "All categories", categories)
        self.reload_table()

    def reload_table(self) -> None:
        rows = self.transactions.list(
            self.month.currentData(), self.category.currentData(), self.search.text(), self.kind.currentData()
        )
        self.model.set_rows(rows, {c.id: c.name for c in self._category_list}, date_format())
        t = totals(rows)
        if t.count:
            self.summary.setText(
                f"{count(t.count, 'transaction')}  ·  Income {format_cents(t.income_cents)}  ·  "
                f"Expenses {format_cents(t.expense_cents)}  ·  Net {format_cents(t.net_cents)}"
            )
        elif (
            self.month.currentData()
            or self.category.currentData() is not None
            or self.search.text()
            or self.kind.currentData()
        ):
            self.summary.setText("No transactions match these filters.")
        else:
            self.summary.setText("No transactions yet. Click “Import…” to load a CSV or PDF statement from your bank.")
        self.update_buttons()

    def update_buttons(self) -> None:
        n = len(self.selected_rows())
        self.edit_btn.setEnabled(n == 1)
        self.set_category_btn.setEnabled(n > 0)
        self.delete_btn.setEnabled(n > 0)
        self.delete_btn.setText(f"Delete ({n})" if n > 1 else "Delete")

    def selected_rows(self) -> list[Transaction]:
        # proxy row != model row once sorted, so map each back to the model
        return [self.model.rows[self.proxy.mapToSource(i).row()] for i in self.table.selectionModel().selectedRows()]

    def selected(self) -> Transaction | None:
        """The selected transaction when exactly one is selected (for Edit)."""
        rows = self.selected_rows()
        return rows[0] if len(rows) == 1 else None

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import bank statement",
            "",
            "Bank statements (*.csv *.pdf);;CSV files (*.csv);;PDF statements (*.pdf);;All files (*)",
        )
        if not path:
            return
        try:
            # A PDF statement becomes the same rows as a CSV, so everything after this is shared.
            rows = read_statement(path) if path.lower().endswith(".pdf") else read_rows(path)
        except (OSError, CsvImportError) as e:
            QMessageBox.warning(self, "Can't read that file", str(e))
            return
        names = {c.id: c.name for c in self._category_list}
        dialog = ImportDialog(self, self.importer, Path(path), rows, names)
        if dialog.exec():
            self.refresh()
            QMessageBox.information(self, "Import complete", f"Imported {count(dialog.imported, 'transaction')}.")

    def add(self) -> None:
        saved = {}

        def save(**values):
            self.transactions.add(**values)
            saved.update(values)

        if TransactionDialog(self, "Add transaction", self._category_list, save).exec():
            self.refresh()
            self._offer_rule(saved["description"], saved["category_id"])

    def edit(self) -> None:
        if not (tx := self.selected()):
            return
        saved = {}

        def save(**values):
            self.transactions.update(tx.id, **values)
            saved.update(values)

        if TransactionDialog(self, "Edit transaction", self._category_list, save, tx).exec():
            self.refresh()
            if saved["category_id"] != tx.category_id:
                self._offer_rule(saved["description"], saved["category_id"])

    def _offer_rule(self, description: str, category_id: int | None) -> None:
        """After a manual categorize, offer a rule so similar transactions get it automatically.
        Skipped when the rules would already pick this category."""
        if category_id is None or self.rules.categorize(description) == category_id:
            return
        note = (
            f'Create a rule so transactions like "{description}" get this category automatically? '
            "Edit the text to match on, or Cancel to skip."
        )
        dialog = RuleDialog(
            self, "Create a rule?", self._category_list, self.rules.add, suggest_pattern(description), category_id, note
        )
        if dialog.exec():
            changed = self.rules.rerun()  # fill in other uncategorized transactions it matches
            self.refresh()
            if changed:
                QMessageBox.information(
                    self, "Rule created", f"Also categorized {count(changed, 'other transaction')}."
                )

    def set_category(self) -> None:
        if not (txs := self.selected_rows()):
            return
        names = [UNCATEGORIZED] + [c.name for c in self._category_list]
        name, ok = QInputDialog.getItem(
            self, "Set category", f"Category for {count(len(txs), 'selected transaction')}:", names, 0, False
        )
        if ok:
            category_id = next((c.id for c in self._category_list if c.name == name), None)
            self.transactions.set_category([t.id for t in txs], category_id)
            self.reload_table()

    def delete(self) -> None:
        if not (txs := self.selected_rows()):
            return
        if len(txs) == 1:
            tx = txs[0]
            title, text = "Delete transaction", f'Delete "{tx.description}" ({format_cents(tx.amount_cents)})?'
        else:
            first, last = min(t.date for t in txs), max(t.date for t in txs)
            fmt = date_format()
            title = "Delete transactions"
            text = (
                f"Delete {count(len(txs), 'transaction')} ({first.strftime(fmt)} to {last.strftime(fmt)}, "
                f"totalling {format_cents(sum(t.amount_cents for t in txs))})?\n\nThis can't be undone."
            )
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        # "No" is the default so a stray Enter never deletes anything.
        answer = QMessageBox.question(self, title, text, buttons, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.transactions.delete([t.id for t in txs])
            self.refresh()


def _refill(combo: QComboBox, all_label: str, items: list[tuple[str, object]]) -> None:
    """Replace a filter combo's items, keeping the current choice if it still exists."""
    current = combo.currentData()
    combo.blockSignals(True)  # don't fire currentIndexChanged for every intermediate state
    combo.clear()
    combo.addItem(all_label, None)
    for label, value in items:
        combo.addItem(label, value)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)
