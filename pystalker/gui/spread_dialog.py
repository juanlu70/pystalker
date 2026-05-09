"""
PyStalker - Spread Creation Dialog
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox,
    QDateEdit, QDialogButtonBox, QMessageBox
)
from PyQt6.QtCore import QDate


class SpreadDialog(QDialog):
    def __init__(self, symbols: list, spreads: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Spread")
        self.setMinimumWidth(350)
        self.symbols = symbols
        self.existing_names = [s['name'] for s in spreads]
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.symbol1_combo = QComboBox()
        self.symbol1_combo.addItems(self.symbols)
        form.addRow("Asset 1:", self.symbol1_combo)
        
        self.symbol2_combo = QComboBox()
        self.symbol2_combo.addItems(self.symbols)
        form.addRow("Asset 2:", self.symbol2_combo)
        
        if len(self.symbols) > 1:
            self.symbol2_combo.setCurrentIndex(1)
        
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addYears(-1))
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        form.addRow("Start Date:", self.start_date_edit)
        
        layout.addLayout(form)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def validate_and_accept(self):
        if self.symbol1_combo.currentText() == self.symbol2_combo.currentText():
            QMessageBox.warning(self, "Invalid Spread", "Please select two different assets.")
            return
        self.accept()
    
    def get_symbol1(self) -> str:
        return self.symbol1_combo.currentText()
    
    def get_symbol2(self) -> str:
        return self.symbol2_combo.currentText()
    
    def get_start_date(self) -> str:
        return self.start_date_edit.date().toString("yyyy-MM-dd")
    
    def get_spread_name(self) -> str:
        return f"{self.get_symbol1()}/{self.get_symbol2()}"