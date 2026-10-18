from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from skimwise.services.categories import CategoryError, CategoryService


class CategoriesView(QWidget):
    def __init__(self, service: CategoryService):
        super().__init__()
        self.service = service

        self.list = QListWidget()
        add_btn = QPushButton("Add…")
        self.rename_btn = QPushButton("Rename…")
        self.delete_btn = QPushButton("Delete")

        # Signals/slots: a widget emits a signal (e.g. `clicked`) and any callable
        # connected to it runs in response.
        add_btn.clicked.connect(self.add)
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn.clicked.connect(self.delete)
        self.list.itemDoubleClicked.connect(self.rename)
        self.list.currentItemChanged.connect(self.update_buttons)

        # Layouts position child widgets and resize them with the window.
        buttons = QHBoxLayout()
        for b in (add_btn, self.rename_btn, self.delete_btn):
            buttons.addWidget(b)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.list)

        self.refresh()

    def refresh(self, select_id: int | None = None) -> None:
        self.list.clear()
        for cat in self.service.list():
            item = QListWidgetItem(cat.name)
            item.setData(Qt.ItemDataRole.UserRole, cat.id)  # stash the id on the row
            self.list.addItem(item)
            if cat.id == select_id:
                self.list.setCurrentItem(item)
        self.update_buttons()

    def update_buttons(self) -> None:
        has_selection = self.list.currentItem() is not None
        self.rename_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def selected(self) -> tuple[int, str] | None:
        item = self.list.currentItem()
        return (item.data(Qt.ItemDataRole.UserRole), item.text()) if item else None

    def add(self) -> None:
        name, ok = QInputDialog.getText(self, "Add category", "Name:")
        if ok:
            try:
                cat = self.service.add(name)
            except CategoryError as e:
                QMessageBox.warning(self, "Can't add category", str(e))
                return
            self.refresh(select_id=cat.id)

    def rename(self) -> None:
        if not (sel := self.selected()):
            return
        cat_id, old = sel
        name, ok = QInputDialog.getText(self, "Rename category", "Name:", text=old)
        if ok:
            try:
                self.service.rename(cat_id, name)
            except CategoryError as e:
                QMessageBox.warning(self, "Can't rename category", str(e))
                return
            self.refresh(select_id=cat_id)

    def delete(self) -> None:
        if not (sel := self.selected()):
            return
        cat_id, name = sel
        answer = QMessageBox.question(
            self,
            "Delete category",
            f'Delete "{name}"? Its transactions will become uncategorized and its rules will be deleted.',
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.service.delete(cat_id)
            self.refresh()
