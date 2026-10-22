"""
PyStalker - Channel Scanner dialog (Trading > Channel Scanner)

The channel_scanner.py tool inside the application: assets whose price is
near a drawn channel line (inside the channel, within the chosen proximity
percentage of the lower or upper line), plus broken-channel notifications.
The "Lower than" input filters the whole report to the assets whose last
price is at that price or lower (the console scanner's --lower-than flag).
The border between the two sections is draggable (the near-line table keeps
about 3x the broken section's height). Double-clicking a row opens that
asset's chart with draggable indicator lines at the channel's line values
(upper green, lower red - the Operations entry/exit line precedent); the
next scanner double-click replaces the previous lines. The CHANNEL column
shows Ascending with a green background and Descending with a red one; the
NEAR LINE column shows Lower with a red background and Upper with a green
one; the broken-channels "beyond upper/lower line" column uses the same
coding (white letters on green/red).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QAbstractItemView,
    QLineEdit, QMessageBox, QSplitter
)

from ..core.channel_scanner import scan_channel_proximity

# the Operations-list look: colored background with white bold text
ASC_COLOR = QColor('#2e7d32')      # Ascending channel
DESC_COLOR = QColor('#c62828')      # Descending channel
LINE_UPPER_COLOR = QColor('#2e7d32')   # near the upper line
LINE_LOWER_COLOR = QColor('#c62828')   # near the lower line

# the chart indicator lines of a double-clicked row (draggable hline
# drawings, the Operations entry/exit precedent): the upper channel line
# in green and the lower one in red - the scanner's color coding
SCANNER_UPPER_LINE = '#00FF00'
SCANNER_LOWER_LINE = '#FF0000'


class ChannelScannerDialog(QDialog):
    def __init__(self, database, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Channel Scanner")
        self.setModal(False)
        self.setMinimumSize(950, 600)
        self._database = database
        self._main_window = main_window
        self._near_evals = {}          # row -> evaluation (for the double-click)
        self._broken_evals = {}
        self._indicator_symbol = None  # where the current indicator lines live

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
        controls.addWidget(QLabel("Lower than:"))
        self.lower_edit = QLineEdit()
        self.lower_edit.setPlaceholderText("e.g. 15 (empty = all prices)")
        self.lower_edit.setMaximumWidth(190)
        self.lower_edit.setToolTip(
            "Only the assets whose last price is at this price or lower,\n"
            "in the whole report (the --lower-than flag of the console\n"
            "scanner). Empty = all prices.")
        controls.addWidget(self.lower_edit)
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

        # the two sections with a draggable border: the near-line table keeps
        # ~3x the height of the broken section (3:1), and the divider between
        # them moves with the mouse
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(broken_group)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([3000, 1000])
        layout.addWidget(self.splitter)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

    def run_scan(self):
        # 'Lower than': empty = all prices, otherwise a positive number
        lower_text = self.lower_edit.text().strip()
        lower_than = None
        if lower_text:
            try:
                lower_than = float(lower_text)
                if lower_than <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Channel Scanner",
                                     "The \"Lower than\" price must be a positive number.")
                return
        conn = self._database.conn
        res = scan_channel_proximity(conn, max_proximity=float(self.max_spin.value()),
                                     lower_than=lower_than)
        self.generated_label.setText(
            res['generated'].strftime('Report generated: %Y-%m-%d %H:%M:%S %Z'))
        price_filter = f" - price <= {lower_than:g}" if lower_than is not None else ""
        self.header_label.setText(
            f"Assets with price within {self.max_spin.value():g}% of a channel line"
            f"{price_filter} - scanned {res['scanned']} asset(s) with channel drawings")

        # near-line table
        self.table.setRowCount(0)
        self._near_evals = {}
        for symbol, ev, price in res['near']:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._near_evals[row] = ev
            self._set_item(self.table, row, 0, symbol)
            # CHANNEL: green background for Ascending, red for Descending;
            # NEAR LINE: red for Lower, green for Upper
            self.table.setItem(row, 1, self._colored_item(
                ev['kind'], ASC_COLOR if ev['kind'] == 'Ascending' else DESC_COLOR))
            self.table.setItem(row, 2, self._colored_item(
                ev['near'], LINE_UPPER_COLOR if ev['near'] == 'Upper' else LINE_LOWER_COLOR))
            proximity_item = self._set_item(self.table, row, 3, f"{ev['proximity']:.2f}%")
            proximity_item.setForeground(QColor('#2EA043'))
            self._set_item(self.table, row, 4, f"{price:.2f}")
            self._set_item(self.table, row, 5, f"{ev['line_value']:.2f}")

        # broken table
        self.broken_table.setRowCount(0)
        self._broken_evals = {}
        for symbol, ev, price in res['broken']:
            row = self.broken_table.rowCount()
            self.broken_table.insertRow(row)
            self._broken_evals[row] = ev
            self._set_item(self.broken_table, row, 0, symbol)
            # CHANNEL: the same green/red background as the near-line table
            self.broken_table.setItem(row, 1, self._colored_item(
                ev['kind'], ASC_COLOR if ev['kind'] == 'Ascending' else DESC_COLOR))
            # BROKEN LINE: "beyond upper line" white on green,
            # "beyond lower line" white on red (the same color coding)
            self.broken_table.setItem(row, 2, self._colored_item(
                f"beyond {ev['broken_line'].lower()} line",
                LINE_UPPER_COLOR if ev['broken_line'] == 'Upper' else LINE_LOWER_COLOR))
            beyond = ev['beyond']
            dist_item = self._set_item(self.broken_table, row, 3,
                                       f"{beyond:.2f}%" if beyond != float('inf') else "?")
            dist_item.setForeground(QColor('#FF4444'))

        self.status_label.setText(
            f"{len(res['near'])} asset(s) near a channel line, "
            f"{len(res['broken'])} broken channel(s)"
            + (f" - skipped: {', '.join(res['skipped'])}" if res['skipped'] else ""))

    @staticmethod
    def _colored_item(text, color):
        """A cell with a colored background and white bold text - the same
        look as the Operations list (the CHANNEL and NEAR LINE columns)."""
        item = QTableWidgetItem(str(text))
        item.setBackground(color)
        item.setForeground(QColor('#FFFFFF'))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

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
            self._open_asset_chart(symbol, self._near_evals.get(row))

    def on_broken_double_clicked(self, row, _col):
        symbol = self._symbol_from_row(self.broken_table, row)
        if symbol and self._main_window:
            self._open_asset_chart(symbol, self._broken_evals.get(row))

    def _open_asset_chart(self, symbol, ev):
        """Open the asset's chart with draggable indicator lines at the
        channel's line values (the upper channel line in green, the lower one
        in red - the scanner's color coding), like the Operations entry/exit
        lines: they are normal hline drawings (moved/deleted by hand like any
        other), and the next scanner double-click replaces the previous set."""
        self._remove_indicator_lines()
        self._main_window.load_chart(symbol)
        self._main_window.raise_()
        self._main_window.activateWindow()
        if ev is None:
            return
        tab = self._main_window.chart_tabs.tabs.get(symbol)
        if tab is None:
            return
        for kind, price, color in (('upper', ev['upper'], SCANNER_UPPER_LINE),
                                   ('lower', ev['lower'], SCANNER_LOWER_LINE)):
            if price:
                tab.chart_view.add_tagged_hline(
                    price, color, {'channel_scanner': True, 'scanner_kind': kind})
        self._database.save_drawings(symbol, tab.chart_view.get_drawings())
        self._indicator_symbol = symbol

    def _remove_indicator_lines(self):
        """Remove the previous scanner indicator lines (from the open chart
        or from the stored drawings when the chart is closed)."""
        symbol = self._indicator_symbol
        if symbol is None:
            return
        self._indicator_symbol = None
        tab = self._main_window.chart_tabs.tabs.get(symbol)
        if tab is not None:
            tab.chart_view.remove_tagged_hlines('channel_scanner', True)
            self._database.save_drawings(symbol, tab.chart_view.get_drawings())
        else:
            drawings = self._database.load_drawings(symbol)
            kept = [d for d in drawings
                    if not (d.get('type') == 'hline'
                            and (d.get('params') or {}).get('channel_scanner'))]
            if len(kept) != len(drawings):
                self._database.save_drawings(symbol, kept)