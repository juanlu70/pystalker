"""
PyStalker - Phemex symbol picker dialog

Searchable list of the Phemex products (spot pairs, perpetual contracts and
tokenized assets like sTSLAONUSDT), to download any of them as a chart
without knowing the technical symbol names by heart.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QHBoxLayout
)

from pystalker.core.providers import PHEMEX_CATEGORY_LABELS


class PhemexSymbolDialog(QDialog):
    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Download Phemex Symbol")
        self.resize(860, 560)
        self.selected_symbol = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Search Phemex products (listed only) and double-click to download:"))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search by symbol, pair or asset name, e.g. TSLA, Tesla, gold, BTC...")
        self.search_edit.textChanged.connect(self.on_search)
        layout.addWidget(self.search_edit)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["SYMBOL", "DESCRIPTION", "NAME", "CATEGORY", "QUOTE"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont('monospace', 9))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(self.on_accept_row)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.ok_button = QPushButton("Download")
        self.ok_button.setEnabled(False)
        self.ok_button.clicked.connect(self.on_ok)
        buttons.addStretch()
        buttons.addWidget(self.ok_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        # listed products only, ordered by name for a stable, browsable list
        listed = [p for p in provider.get_products() if p.get('status') == 'Listed']
        listed.sort(key=lambda p: (p.get('symbol') or ''))
        self._rows = [
            (p.get('symbol') or '',
             p.get('displaySymbol') or '',
             provider.get_product_name(p),
             PHEMEX_CATEGORY_LABELS.get(provider.classify_product(p), ''),
             p.get('quoteCurrency') or '')
            for p in listed
        ]
        self.on_search('')

    def on_search(self, text):
        text = (text or '').strip().lower()
        self.table.setRowCount(0)
        for row in self._rows:
            if not text or any(text in value.lower() for value in row):
                self._add_row(row)
        self.ok_button.setEnabled(False)

    def _add_row(self, row):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, value in enumerate(row):
            item = QTableWidgetItem(value)
            if col == 0:
                item.setFont(QFont('monospace', 9, QFont.Weight.Bold))
            self.table.setItem(r, col, item)

    def on_accept_row(self, item):
        self.selected_symbol = self.table.item(item.row(), 0).text()
        self.accept()

    def on_ok(self):
        selected = self.table.selectedItems()
        if selected:
            self.selected_symbol = self.table.item(selected[0].row(), 0).text()
            self.accept()