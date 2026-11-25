"""
PyStalker - Asset Overlap Creation Dialog

The overlap's asset list is DYNAMIC (the user's request: a minimum of
two assets, with the option to add more, no limit): the assets are
added one by one from a combo - listing them by their PERSONALIZED
DISPLAY NAMES like the spread dialog, the official symbol travelling
underneath - into the chosen-assets list, where any one of them can be
removed again. The first two assets of the database come pre-chosen so
the dialog is ready to accept, exactly like the spread dialog pairs
its two combos.

The start date (the user's request: "both lines must begin in a certain
date or first data date"): the checkbox - checked by default - starts
the lines at the FIRST DATA DATE (the first day ALL the chosen assets
share); unchecking it reveals the date picker (one year ago by
default, like the spread dialog).
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QDateEdit, QDialogButtonBox, QMessageBox, QListWidget,
    QListWidgetItem, QPushButton, QCheckBox, QLabel
)
from PyQt6.QtCore import QDate, Qt


class OverlapDialog(QDialog):
    def __init__(self, symbols: list, overlaps: list,
                 display_names: dict = None, parent=None,
                 initial_symbols: list = None,
                 title: str = "Create Asset Overlap",
                 show_start_date: bool = True):
        """The creation dialog by default; the context menu's "Change
        Assets..." reuses it with the overlap's current assets
        pre-chosen (initial_symbols), the "Change Overlap Assets" title
        and the start date block left out (show_start_date False - the
        date is changed by its own menu point)."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.symbols = symbols
        self.display_names = display_names or {}
        self.existing_names = [o['name'] for o in overlaps]
        self.initial_symbols = list(initial_symbols) if initial_symbols is not None else None
        self.show_start_date = show_start_date
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # the asset picker: the display names in the combo, the official
        # symbol as each item's data, exactly like the spread dialog
        picker_layout = QHBoxLayout()
        self.symbol_combo = QComboBox()
        for symbol in self.symbols:
            self.symbol_combo.addItem(self.display_names.get(symbol) or symbol,
                                       symbol)
        picker_layout.addWidget(self.symbol_combo, 1)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.on_add_asset)
        picker_layout.addWidget(add_button)
        layout.addLayout(picker_layout)

        layout.addWidget(QLabel("Chosen assets (at least two, no limit):"))
        self.chosen_list = QListWidget()
        self.chosen_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.chosen_list, 1)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self.on_remove_asset)
        layout.addWidget(remove_button)

        # the start date: the first shared data date, or a chosen date.
        # The widgets always exist (so get_start_date always works); the
        # block is only shown for the creation flow
        self.first_data_check = QCheckBox("From the first data date "
                                          "(the first day all the assets share)")
        self.first_data_check.setChecked(True)
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addYears(-1))
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setEnabled(False)
        self.first_data_check.toggled.connect(
            lambda on: self.start_date_edit.setEnabled(not on))
        if self.show_start_date:
            form = QFormLayout()
            form.addRow(self.first_data_check)
            form.addRow("Start Date:", self.start_date_edit)
            layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # the pre-chosen assets: the overlap's current ones when
        # changing them, the first two of the database when creating
        if self.initial_symbols is not None:
            for symbol in self.initial_symbols:
                self._add_symbol(symbol)
        else:
            if len(self.symbols) >= 1:
                self._add_symbol(self.symbols[0])
            if len(self.symbols) >= 2:
                self._add_symbol(self.symbols[1])

    def _add_symbol(self, symbol: str):
        item = QListWidgetItem(self.display_names.get(symbol) or symbol)
        item.setData(Qt.ItemDataRole.UserRole, symbol)
        self.chosen_list.addItem(item)

    def on_add_asset(self):
        symbol = self.symbol_combo.currentData() or self.symbol_combo.currentText()
        for i in range(self.chosen_list.count()):
            if self.chosen_list.item(i).data(Qt.ItemDataRole.UserRole) == symbol:
                QMessageBox.information(
                    self, "Asset Overlap",
                    f"{self.display_names.get(symbol) or symbol} is "
                    "already in the overlap.")
                return
        self._add_symbol(symbol)

    def on_remove_asset(self):
        for item in self.chosen_list.selectedItems():
            self.chosen_list.takeItem(self.chosen_list.row(item))

    def validate_and_accept(self):
        # a minimum of two different OFFICIAL symbols (two assets can
        # share a display name)
        if len(set(self.get_symbols())) < 2:
            QMessageBox.warning(self, "Invalid Overlap",
                                 "Please choose at least two different assets.")
            return
        self.accept()

    def get_symbols(self) -> list:
        return [self.chosen_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.chosen_list.count())]

    def get_start_date(self) -> str:
        """'' = from the first shared data date."""
        if self.first_data_check.isChecked():
            return ''
        return self.start_date_edit.date().toString("yyyy-MM-dd")

    def get_overlap_name(self) -> str:
        return '/'.join(self.get_symbols())
