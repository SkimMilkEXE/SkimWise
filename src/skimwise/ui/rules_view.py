from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from skimwise.models import Category, Rule
from skimwise.services.categories import CategoryService
from skimwise.services.money import count
from skimwise.services.rules import RuleError, RuleService


class RuleDialog(QDialog):
    """Pattern + category form. `on_save(pattern, category_id)` does the saving; on RuleError
    the message is shown and the dialog stays open."""

    def __init__(self, parent, title, categories: list[Category], on_save, pattern="", category_id=None, note=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.on_save = on_save
        self.pattern = QLineEdit(pattern)
        self.category = QComboBox()
        for c in categories:
            self.category.addItem(c.name, c.id)
        self.category.setCurrentIndex(max(0, self.category.findData(category_id)))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        if note:
            label = QLabel(note)
            label.setWordWrap(True)
            form.addRow(label)
        form.addRow("Description contains:", self.pattern)
        form.addRow("Category:", self.category)
        form.addRow(buttons)

    def accept(self):
        try:
            self.on_save(self.pattern.text(), self.category.currentData())
        except RuleError as e:
            QMessageBox.warning(self, "Can't save rule", str(e))
            return
        super().accept()


class RulesView(QWidget):
    def __init__(self, rules: RuleService, categories: CategoryService):
        super().__init__()
        self.rules = rules
        self.categories = categories

        self.list = QListWidget()
        add_btn = QPushButton("Add…")
        self.edit_btn = QPushButton("Edit…")
        self.delete_btn = QPushButton("Delete")
        self.up_btn = QPushButton("Move up")
        self.down_btn = QPushButton("Move down")
        rerun_btn = QPushButton("Re-run rules…")

        add_btn.clicked.connect(self.add)
        self.edit_btn.clicked.connect(self.edit)
        self.delete_btn.clicked.connect(self.delete)
        self.up_btn.clicked.connect(lambda: self.move(-1))
        self.down_btn.clicked.connect(lambda: self.move(1))
        rerun_btn.clicked.connect(self.rerun)
        self.list.itemDoubleClicked.connect(self.edit)
        self.list.currentRowChanged.connect(self.update_buttons)

        buttons = QHBoxLayout()
        for b in (add_btn, self.edit_btn, self.delete_btn, self.up_btn, self.down_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(rerun_btn)

        hint = QLabel(
            "Rules sort transactions into categories automatically. A rule like "
            '<b>"NETFLIX" → Subscriptions</b> puts any transaction whose description contains '
            '"netflix" (any capitalization) into Subscriptions.<br><br>'
            "Rules run on every CSV import. They're checked from the top and the <b>first match wins</b>, "
            'so put specific rules ("AMAZON PRIME") above general ones ("AMAZON"). '
            "When you categorize a transaction by hand you'll be offered a rule for it, and "
            "<b>Re-run rules</b> applies them to transactions you've already imported."
        )
        hint.setWordWrap(True)  # QLabel treats text containing tags as rich text

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(hint)
        layout.addWidget(self.list)

        self.refresh()

    def refresh(self, select_id: int | None = None) -> None:
        self._categories = self.categories.list()
        names = {c.id: c.name for c in self._categories}
        self.list.clear()
        for r in self.rules.list():
            item = QListWidgetItem(f'"{r.pattern}"  →  {names.get(r.category_id, "?")}')
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.list.addItem(item)
            if r.id == select_id:
                self.list.setCurrentItem(item)
        self.update_buttons()

    def update_buttons(self) -> None:
        row = self.list.currentRow()
        for b in (self.edit_btn, self.delete_btn):
            b.setEnabled(row >= 0)
        self.up_btn.setEnabled(row > 0)
        self.down_btn.setEnabled(0 <= row < self.list.count() - 1)

    def selected(self) -> Rule | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add(self) -> None:
        saved = []
        dialog = RuleDialog(self, "Add rule", self._categories, lambda p, c: saved.append(self.rules.add(p, c)))
        if dialog.exec():
            self.refresh(select_id=saved[0].id)

    def edit(self) -> None:
        if not (r := self.selected()):
            return

        def save(pattern, category_id):
            self.rules.update(r.id, pattern, category_id)

        if RuleDialog(self, "Edit rule", self._categories, save, r.pattern, r.category_id).exec():
            self.refresh(select_id=r.id)

    def delete(self) -> None:
        if not (r := self.selected()):
            return
        if (
            QMessageBox.question(self, "Delete rule", f'Delete the rule for "{r.pattern}"?')
            == QMessageBox.StandardButton.Yes
        ):
            self.rules.delete(r.id)
            self.refresh()

    def move(self, step: int) -> None:
        if r := self.selected():
            self.rules.move(r.id, step)
            self.refresh(select_id=r.id)

    def rerun(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Re-run rules")
        box.setText("Apply rules to transactions you've already imported?")
        box.setInformativeText(
            "Uncategorized only: fills in blanks and never changes a category you've set.\n"
            "All transactions: where a rule matches, it replaces the current category."
        )
        uncategorized = box.addButton("Uncategorized only", QMessageBox.ButtonRole.AcceptRole)
        everything = box.addButton("All transactions", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(uncategorized)
        box.exec()
        if box.clickedButton() in (uncategorized, everything):
            changed = self.rules.rerun(overwrite=box.clickedButton() is everything)
            QMessageBox.information(self, "Re-run rules", f"Updated {count(changed, 'transaction')}.")
