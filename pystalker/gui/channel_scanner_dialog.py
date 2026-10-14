"""
PyStalker - Channel Scanner dialog (Trading > Channel Scanner)

The channel_scanner.py tool inside the application: assets whose price is
near a drawn channel line (inside the channel, within the chosen proximity
percentage of the lower or upper line), plus broken-channel notifications.
Double-click a row to open that asset's chart.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QAbstractItemView
)

from ..core.channel_scanner import scan_channel_proximity


class ChannelScannerDialog(QDialog):
    def __init__(self, database, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Channel Scanner")
        self.setModal(False)
        self.setMinimumSize(950, 600)
        self._database = database
        self._main_window = main_window

        layout = QVBoxLayout(self)

        # controls
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Max proximity:"))
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(0.1, 100.0)
        self.max_spin.setDecimals(1)
        self.max_spin.setSingleStep(0.5)
        self.max_spin.setValue(10.0)
        self.max_spin.setSuffix("%")
        controls.addWidget(self.max_spin)
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.run_scan)
        controls.addWidget(self.scan_button)
        controls.addStretch()
        self.generated_label = QLabel("")
        self.generated_label.setStyleSheet("color: gray;")
        controls.addWidget(self.generated_label)
        layout.addLayout(controls)

        # near-line results
        self.header_label = QLabel("")
        layout.addWidget(self.header_label)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ASSET", "CHANNEL", "NEAR LINE", "PROXIMITY",
                                              "LAST CLOSE", "LINE VALUE"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        font = QFont('monospace', 9)
        self.table.setFont(font)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)
        layout.addWidget(self.table, 3)

        # broken channels
        broken_group = QGroupBox("Broken channels (price beyond a line)")
        broken_layout = QVBoxLayout(broken_group)
        self.broken_table = QTableWidget(0, 4)
        self.broken_table.setHorizontalHeaderLabels(["ASSET", "CHANNEL", "BROKEN LINE", "DISTANCE BEYOND"])
        self.broken_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.broken_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.broken_table.verticalHeader().setVisible(False)
        self.broken_table.setAlternatingRowColors(True)
        self.broken_table.setFont(font)
        bheader = self.broken_table.horizontalHeader()
        bheader.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            bheader.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.broken_table.cellDoubleClicked.connect(self.on_broken_double_clicked)
        broken_layout.addWidget(self.broken_table)
        layout.addWidget(broken_group, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

    def run_scan(self):
        conn = self._database.conn
        res = scan_channel_proximity(conn, max_proximity=float(self.max_spin.value()))
        self.generated_label.setText(
            res['generated'].strftime('Report generated: %Y-%m-%d %H:%M:%S %Z'))
        self.header_label.setText(
            f"Assets with price within {self.max_spin.value():g}% of a channel line "
            f"- scanned {res['scanned']} asset(s) with channel drawings")

        # near-line table
        self.table.setRowCount(0)
        for symbol, ev, price in res['near']:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._set_item(self.table, row, 0, symbol)
            self._set_item(self.table, row, 1, ev['kind'])
            self._set_item(self.table, row, 2, ev['near'])
            proximity_item = self._set_item(self.table, row, 3, f"{ev['proximity']:.2f}%")
            proximity_item.setForeground(QColor('#2EA043'))
            self._set_item(self.table, row, 4, f"{price:.2f}")
            self._set_item(self.table, row, 5, f"{ev['line_value']:.2f}")

        # broken table
        self.broken_table.setRowCount(0)
        for symbol, ev, price in res['broken']:
            row = self.broken_table.rowCount()
            self.broken_table.insertRow(row)
            self._set_item(self.broken_table, row, 0, symbol)
            self._set_item(self.broken_table, row, 1, ev['kind'])
            broken_item = self._set_item(self.broken_table, row, 2, f"beyond {ev['broken_line'].lower()} line")
            broken_item.setForeground(QColor('#FF4444'))
            beyond = ev['beyond']
            dist_item = self._set_item(self.broken_table, row, 3,
                                       f"{beyond:.2f}%" if beyond != float('inf') else "?")
            dist_item.setForeground(QColor('#FF4444'))

        self.status_label.setText(
            f"{len(res['near'])} asset(s) near a channel line, "
            f"{len(res['broken'])} broken channel(s)"
            + (f" - skipped: {', '.join(res['skipped'])}" if res['skipped'] else ""))

    @staticmethod
    def _set_item(table, row, col, text):
        item = QTableWidgetItem(str(text))
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                              if col >= 3 else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.setItem(row, col, item)
        return item

    def _symbol_from_row(self, table, row):
        item = table.item(row, 0)
        return item.text() if item else None

    def on_row_double_clicked(self, row, _col):
        symbol = self._symbol_from_row(self.table, row)
        if symbol and self._main_window:
            self._main_window.load_chart(symbol)
            self._main_window.raise_()
            self._main_window.activateWindow()

    def on_broken_double_clicked(self, row, _col):
        symbol = self._symbol_from_row(self.broken_table, row)
        if symbol and self._main_window:
            self._main_window.load_chart(symbol)
            self._main_window.raise_()
            self._main_window.activateWindow()