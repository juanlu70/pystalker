"""
PyStalker - Supertrend dialog (Trading > Supertrend)

The supertrend.py tool inside the application: assets whose last close is
TOUCHING the active supertrend line (within the chosen proximity
percentage, still on the safe side of it) plus the SURPASSED
notifications - the close crossed the line on the last bar, flipping the
trend. The ASSET column shows the personalized display names (the
official symbol rides along hidden, so charts and indicator lines keep
working). Click a column header to sort like the Operations list (the
numeric columns sort numerically). The controls are the indicator's own
parameters: the period and the multiplier (10 and 1.8, the project's
chosen defaults) and the max proximity. The border between the two
sections is draggable (the touching table keeps about 3x the surpassed
section's height).

Double-clicking a row opens that asset's chart with a draggable
indicator line at the reported level, colored BY THE TREND (Up = green,
Down = red - in a supertrend the trend is the signal, unlike the channel
scanner's line-kind colors); the next scanner double-click replaces the
previous line. The TREND column shows Up with a green background and
Down with a red one; the LINE column shows Lower with a red background
and Upper with a green one (the channel scanner's coding); the surpassed
"beyond upper/lower line" column uses the same coding (white letters on
green/red).
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QAbstractItemView, QSplitter
)

from ..core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                scan_supertrend)
from .operations_dialog import NumericItem

# the Operations-list look: colored background with white bold text
TREND_UP_COLOR = QColor('#2e7d32')        # Up trend
TREND_DOWN_COLOR = QColor('#c62828')     # Down trend
LINE_UPPER_COLOR = QColor('#2e7d32')     # the upper line
LINE_LOWER_COLOR = QColor('#c62828')     # the lower line

# the chart indicator line of a double-clicked row (a draggable hline
# drawing, the Operations entry/exit precedent): colored BY THE TREND -
# green when the asset is in an Up trend, red in a Down one (the trend is
# the supertrend's signal)
SCANNER_UP_LINE = '#00FF00'
SCANNER_DOWN_LINE = '#FF0000'


class SupertrendDialog(QDialog):
    def __init__(self, database, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Supertrend")
        self.setModal(False)
        self.setMinimumSize(950, 600)
        self._database = database
        self._main_window = main_window
        self._touching_evals = {}        # symbol -> evaluation (double-click)
        self._surpassed_evals = {}
        self._indicator_symbol = None    # where the current indicator line lives

        layout = QVBoxLayout(self)

        # controls: the indicator's parameters
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Period:"))
        self.period_spin = QSpinBox()
        self.period_spin.setRange(2, 200)
        self.period_spin.setValue(SUPERTREND_PERIOD)
        controls.addWidget(self.period_spin)
        controls.addWidget(QLabel("Multiplier:"))
        self.multiplier_spin = QDoubleSpinBox()
        self.multiplier_spin.setRange(0.1, 10.0)
        self.multiplier_spin.setDecimals(1)
        self.multiplier_spin.setSingleStep(0.1)
        self.multiplier_spin.setValue(SUPERTREND_MULTIPLIER)
        controls.addWidget(self.multiplier_spin)
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

        # touching results
        self.header_label = QLabel("")
        layout.addWidget(self.header_label)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ASSET", "TREND", "LINE", "AGE",
                                              "PROXIMITY", "LAST CLOSE", "LINE VALUE"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        font = QFont('monospace', 9)
        self.table.setFont(font)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)

        # surpassed (the close crossed the line on the last bar)
        surpassed_group = QGroupBox("Surpassed (the close crossed the line on the last bar)")
        surpassed_layout = QVBoxLayout(surpassed_group)
        self.surpassed_table = QTableWidget(0, 4)
        self.surpassed_table.setHorizontalHeaderLabels(["ASSET", "TREND", "LINE",
                                                        "DISTANCE BEYOND"])
        self.surpassed_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.surpassed_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.surpassed_table.verticalHeader().setVisible(False)
        self.surpassed_table.setAlternatingRowColors(True)
        self.surpassed_table.setFont(font)
        sheader = self.surpassed_table.horizontalHeader()
        sheader.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            sheader.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.surpassed_table.cellDoubleClicked.connect(self.on_surpassed_double_clicked)
        surpassed_layout.addWidget(self.surpassed_table)

        # the two sections with a draggable border: the touching table keeps
        # ~3x the height of the surpassed section (3:1), and the divider
        # between them moves with the mouse
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(surpassed_group)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([3000, 1000])
        layout.addWidget(self.splitter)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

    def run_scan(self):
        conn = self._database.conn
        res = scan_supertrend(conn, period=self.period_spin.value(),
                              multiplier=float(self.multiplier_spin.value()),
                              max_proximity=float(self.max_spin.value()))
        self.generated_label.setText(
            res['generated'].strftime('Report generated: %Y-%m-%d %H:%M:%S %Z'))
        self.header_label.setText(
            f"Assets with the close within {self.max_spin.value():g}% of the "
            f"supertrend line (period {self.period_spin.value()}, multiplier "
            f"{self.multiplier_spin.value():g}) - scanned {res['scanned']} asset(s)")

        # touching table
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._touching_evals = {}
        for symbol, ev, price in res['touching']:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._touching_evals[symbol] = ev
            self.table.setItem(row, 0, self._asset_item(symbol))
            # TREND: green background for Up, red for Down; LINE: red for
            # Lower, green for Upper (the channel scanner's coding)
            self.table.setItem(row, 1, self._colored_item(
                ev['trend'], TREND_UP_COLOR if ev['trend'] == 'Up' else TREND_DOWN_COLOR))
            self.table.setItem(row, 2, self._colored_item(
                ev['line'], LINE_UPPER_COLOR if ev['line'] == 'Upper' else LINE_LOWER_COLOR))
            self._numeric_item(self.table, row, 3, str(ev['age']), ev['age'])
            proximity_item = self._numeric_item(self.table, row, 4,
                                                f"{ev['proximity']:.2f}%", ev['proximity'])
            proximity_item.setForeground(QColor('#2EA043'))
            self._numeric_item(self.table, row, 5, f"{price:.2f}", price)
            self._numeric_item(self.table, row, 6, f"{ev['line_value']:.2f}",
                               ev['line_value'])
        # sorting like the Operations list: click a column header to sort
        # (numeric columns sort numerically); the default keeps the
        # proximity order
        self.table.setSortingEnabled(True)
        self.table.sortItems(4, Qt.SortOrder.AscendingOrder)

        # surpassed table
        self.surpassed_table.setSortingEnabled(False)
        self.surpassed_table.setRowCount(0)
        self._surpassed_evals = {}
        for symbol, ev, price in res['surpassed']:
            row = self.surpassed_table.rowCount()
            self.surpassed_table.insertRow(row)
            self._surpassed_evals[symbol] = ev
            self.surpassed_table.setItem(row, 0, self._asset_item(symbol))
            # TREND: "Down -> Up" with the NEW trend's background
            self.surpassed_table.setItem(row, 1, self._colored_item(
                f"{ev['old_trend']} -> {ev['trend']}",
                TREND_UP_COLOR if ev['trend'] == 'Up' else TREND_DOWN_COLOR))
            # LINE: "beyond upper/lower line" white on green/red (the same
            # coding as the channel scanner's broken table)
            self.surpassed_table.setItem(row, 2, self._colored_item(
                f"beyond {ev['line'].lower()} line",
                LINE_UPPER_COLOR if ev['line'] == 'Upper' else LINE_LOWER_COLOR))
            beyond = ev['beyond']
            finite = beyond != float('inf')
            dist_item = self._numeric_item(self.surpassed_table, row, 3,
                                           f"{beyond:.2f}%" if finite else "?",
                                           beyond if finite else None)
            dist_item.setForeground(QColor('#FF4444'))
        self.surpassed_table.setSortingEnabled(True)
        self.surpassed_table.sortItems(0, Qt.SortOrder.AscendingOrder)

        self.status_label.setText(
            f"{len(res['touching'])} asset(s) touching the supertrend line, "
            f"{len(res['surpassed'])} surpassed (trend flipped)"
            + (f" - skipped: {', '.join(res['skipped'])}" if res['skipped'] else ""))

    def _asset_item(self, symbol):
        """The ASSET cell: the personalized display name as the visible text,
        the official symbol in the data role (charts, indicator lines and
        evaluations always use the official symbol)."""
        display = self._database.get_display_name(symbol) or symbol
        item = QTableWidgetItem(display)
        item.setData(Qt.ItemDataRole.UserRole, symbol)
        return item

    @staticmethod
    def _numeric_item(table, row, col, text, value):
        """A right-aligned cell that sorts numerically (like Operations)."""
        item = NumericItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if value is not None:
            item.setData(Qt.ItemDataRole.UserRole, value)
        table.setItem(row, col, item)
        return item

    @staticmethod
    def _colored_item(text, color):
        """A cell with a colored background and white bold text - the same
        look as the Operations list (the TREND and LINE columns)."""
        item = QTableWidgetItem(str(text))
        item.setBackground(color)
        item.setForeground(QColor('#FFFFFF'))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        return item

    def _symbol_from_row(self, table, row):
        item = table.item(row, 0)
        if not item:
            return None
        # the cell shows the personalized name; the official symbol rides
        # along in the data role
        return item.data(Qt.ItemDataRole.UserRole) or item.text()

    def on_row_double_clicked(self, row, _col):
        symbol = self._symbol_from_row(self.table, row)
        if symbol and self._main_window:
            self._open_asset_chart(symbol, self._touching_evals.get(symbol))

    def on_surpassed_double_clicked(self, row, _col):
        symbol = self._symbol_from_row(self.surpassed_table, row)
        if symbol and self._main_window:
            self._open_asset_chart(symbol, self._surpassed_evals.get(symbol))

    def _open_asset_chart(self, symbol, ev):
        """Open the asset's chart with a draggable indicator line at the
        reported supertrend level, colored BY THE TREND (Up = green, Down =
        red - the trend is the supertrend's signal), like the Operations
        entry/exit lines: it is a normal hline drawing (moved/deleted by
        hand like any other), and the next scanner double-click replaces
        the previous one."""
        self._remove_indicator_lines()
        self._main_window.load_chart(symbol)
        self._main_window.raise_()
        self._main_window.activateWindow()
        if ev is None:
            return
        tab = self._main_window.chart_tabs.tabs.get(symbol)
        if tab is None:
            return
        color = SCANNER_UP_LINE if ev['trend'] == 'Up' else SCANNER_DOWN_LINE
        tab.chart_view.add_tagged_hline(
            ev['line_value'], color,
            {'supertrend_scanner': True, 'trend': ev['trend']})
        self._database.save_drawings(symbol, tab.chart_view.get_drawings())
        self._indicator_symbol = symbol

    def _remove_indicator_lines(self):
        """Remove the previous scanner indicator line (from the open chart
        or from the stored drawings when the chart is closed)."""
        symbol = self._indicator_symbol
        if symbol is None:
            return
        self._indicator_symbol = None
        tab = self._main_window.chart_tabs.tabs.get(symbol)
        if tab is not None:
            tab.chart_view.remove_tagged_hlines('supertrend_scanner', True)
            self._database.save_drawings(symbol, tab.chart_view.get_drawings())
        else:
            drawings = self._database.load_drawings(symbol)
            kept = [d for d in drawings
                    if not (d.get('type') == 'hline'
                            and (d.get('params') or {}).get('supertrend_scanner'))]
            if len(kept) != len(drawings):
                self._database.save_drawings(symbol, kept)