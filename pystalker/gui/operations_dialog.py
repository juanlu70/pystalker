"""
PyStalker - Operations dialog (Trading > Operations)

A trading journal: annotate operations (bot or manual, spot or futures,
paper or real, planned or already started) and list the current and past
ones with their live state - the current price from the program's data,
the directional percent gain (+/-) and the final PNL (percent x leverage
for closed operations). Planned operations are still only a project that
may or may not start: they keep a plain gain/PNL look (no green/red).
Double-click a row (or Edit) to fix mistakes, Delete removes a record.
The operations are stored in the `operations` table of the database.
"""
from PyQt6.QtCore import Qt, QDateTime
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QFormLayout, QDateTimeEdit, QMessageBox
)

# Long / winning: green background. Short / losing: red background.
LONG_COLOR = QColor('#2e7d32')
SHORT_COLOR = QColor('#c62828')

# operation entry/exit lines drawn on the asset's chart
ENTRY_LONG_LINE = '#00FF00'    # bright green entry line for longs
ENTRY_SHORT_LINE = '#FF0000'   # bright red entry line for shorts
EXIT_LINE = '#55AAFF'          # bright blue exit line (RGB 85, 170, 255)

BOT_OPTIONS = ['No bot', 'Bot']
MARKET_OPTIONS = ['Spot', 'Futures']
SIDE_OPTIONS = ['Long', 'Short']
LEVERAGE_PRESETS = ['1', '2', '3', '5', '10', '20', '25', '50', '100', 'Combined']


def leverage_value(text):
    """The numeric leverage, or None for 'Combined' or other free text."""
    try:
        value = float(str(text).strip())
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def move_percent(side, entry_price, price):
    """Directional percent move of the operation: + when winning.

    Long: (price - entry) / entry. Short: (entry - price) / entry.
    """
    if not entry_price or not price:
        return None
    if side == 'Short':
        return (entry_price - price) / entry_price * 100
    return (price - entry_price) / entry_price * 100


class OperationFormDialog(QDialog):
    """Create / edit a trading operation (the New operation window)."""

    def __init__(self, operation=None, parent=None):
        super().__init__(parent)
        self._operation = operation or {}
        editing = bool(self._operation)
        self.setWindowTitle("Edit operation" if editing else "New operation")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        form_box = QGroupBox("Operation details")
        form = QFormLayout(form_box)

        self.bot_combo = QComboBox()
        self.bot_combo.addItems(BOT_OPTIONS)
        form.addRow("Bot:", self.bot_combo)

        self.market_combo = QComboBox()
        self.market_combo.addItems(MARKET_OPTIONS)
        form.addRow("Market:", self.market_combo)

        self.paper_check = QCheckBox("Paper trading")
        form.addRow("", self.paper_check)

        self.planned_check = QCheckBox("Planned (a project that may or may not start)")
        self.planned_check.setToolTip(
            "The operation has not started yet - it is still only a project\n"
            "that may start soon or never. Its gain and PNL are shown with\n"
            "the plain look (no green/red) because there are no real gains yet.\n"
            "Uncheck it (here or in the list) when the operation actually starts.")
        form.addRow("", self.planned_check)

        self.asset_edit = QLineEdit()
        self.asset_edit.setPlaceholderText("official ticker (or any name - resolved automatically)")
        form.addRow("Asset:", self.asset_edit)

        self.side_combo = QComboBox()
        self.side_combo.addItems(SIDE_OPTIONS)
        form.addRow("Long/Short:", self.side_combo)

        self.entry_price_edit = QLineEdit()
        self.entry_price_edit.setPlaceholderText("e.g. 83043")
        form.addRow("Entry price:", self.entry_price_edit)

        self.volume_edit = QLineEdit()
        self.volume_edit.setPlaceholderText("e.g. 2500 (optional)")
        self.volume_edit.setToolTip(
            "The invested amount in the quote currency (usually USDT).\n"
            "Margin for futures - the final PNL multiplies it by the leverage;\n"
            "the full position value for spot or 'Combined' leverage.")
        form.addRow("Volume:", self.volume_edit)

        self.leverage_combo = QComboBox()
        self.leverage_combo.setEditable(True)
        self.leverage_combo.addItems(LEVERAGE_PRESETS)
        self.leverage_combo.setCurrentText('1')
        form.addRow("Leverage:", self.leverage_combo)

        self.entry_dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.entry_dt.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.entry_dt.setCalendarPopup(True)
        form.addRow("Entry date & hour:", self.entry_dt)

        layout.addWidget(form_box)

        exit_box = QGroupBox("Exit")
        exit_form = QFormLayout(exit_box)

        self.open_check = QCheckBox("Open operation")
        self.open_check.setChecked(True)
        self.open_check.setToolTip(
            "While checked the operation runs: the exit price is only a reference\n"
            "and the exit date stays empty. Uncheck when the operation is closed\n"
            "(the exit price is then required).")
        self.open_check.toggled.connect(self._on_open_toggled)
        exit_form.addRow(self.open_check)

        self.exit_price_edit = QLineEdit()
        self.exit_price_edit.setPlaceholderText("e.g. 91200 (reference while open)")
        self.exit_price_edit.setToolTip(
            "The exit price: a reference/target while the operation is open,\n"
            "the final price once it is closed.")
        exit_form.addRow("Exit price:", self.exit_price_edit)

        self.exit_dt = QDateTimeEdit(QDateTime.currentDateTime())
        self.exit_dt.setDisplayFormat('yyyy-MM-dd HH:mm')
        self.exit_dt.setCalendarPopup(True)
        exit_form.addRow("Exit date & hour:", self.exit_dt)

        layout.addWidget(exit_box)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok_button = QPushButton("Save")
        ok_button.clicked.connect(self._on_save)
        buttons.addWidget(ok_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self._operation_data = None
        if editing:
            self._prefill()
        self._on_open_toggled()

    def _on_open_toggled(self):
        # the exit price is always editable (a reference while open); the exit
        # date is the closing timestamp, so it only exists once closed
        self.exit_dt.setEnabled(not self.open_check.isChecked())

    def _prefill(self):
        op = self._operation
        self.bot_combo.setCurrentText(op.get('bot') or 'No bot')
        self.market_combo.setCurrentText(op.get('market') or 'Spot')
        self.paper_check.setChecked(bool(op.get('paper')))
        self.planned_check.setChecked(bool(op.get('planned')))
        self.asset_edit.setText(op.get('asset') or '')
        self.side_combo.setCurrentText(op.get('side') or 'Long')
        self.entry_price_edit.setText(f"{op.get('entry_price') or ''}")
        self.volume_edit.setText(f"{op.get('volume') or ''}")
        self.leverage_combo.setCurrentText(str(op.get('leverage') or '1'))
        dt = QDateTime.fromString(str(op.get('entry_date') or ''), 'yyyy-MM-dd HH:mm')
        self.entry_dt.setDateTime(dt if dt.isValid() else QDateTime.currentDateTime())
        self.open_check.setChecked(bool(op.get('open', 1)))
        if op.get('exit_price') is not None:
            self.exit_price_edit.setText(f"{op['exit_price']}")
        dt = QDateTime.fromString(str(op.get('exit_date') or ''), 'yyyy-MM-dd HH:mm')
        self.exit_dt.setDateTime(dt if dt.isValid() else QDateTime.currentDateTime())

    def _on_save(self):
        asset = self.asset_edit.text().strip()
        if not asset:
            QMessageBox.warning(self, "Operation", "The asset name cannot be empty.")
            return
        try:
            entry_price = float(self.entry_price_edit.text().strip())
            if entry_price <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Operation", "The entry price must be a positive number.")
            return
        exit_price = None
        exit_text = self.exit_price_edit.text().strip()
        if exit_text:
            try:
                exit_price = float(exit_text)
                if exit_price <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Operation", "The exit price must be a positive number.")
                return
        if not self.open_check.isChecked() and exit_price is None:
            QMessageBox.warning(self, "Operation",
                                "The exit price is required to close the operation.")
            return

        volume = None
        volume_text = self.volume_edit.text().strip()
        if volume_text:
            try:
                volume = float(volume_text)
                if volume <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.warning(self, "Operation",
                                    "The volume must be a positive number (the invested amount).")
                return

        open_flag = self.open_check.isChecked()
        self._operation_data = {
            'bot': self.bot_combo.currentText(),
            'market': self.market_combo.currentText(),
            'paper': self.paper_check.isChecked(),
            'asset': asset,
            'side': self.side_combo.currentText(),
            'entry_price': entry_price,
            'volume': volume,
            'leverage': self.leverage_combo.currentText().strip(),
            'entry_date': self.entry_dt.dateTime().toString('yyyy-MM-dd HH:mm'),
            'exit_price': exit_price,
            'exit_date': self.exit_dt.dateTime().toString('yyyy-MM-dd HH:mm') if not open_flag else None,
            'open': open_flag,
            'planned': self.planned_check.isChecked(),
        }
        self.accept()

    def get_operation(self):
        """The operation dict once the dialog was accepted."""
        return self._operation_data


class NumericItem(QTableWidgetItem):
    """Table item that sorts by its numeric UserRole ('-' sorts last)."""

    def __lt__(self, other):
        a = self.data(Qt.ItemDataRole.UserRole)
        b = other.data(Qt.ItemDataRole.UserRole)
        if a is None and b is None:
            return False
        if a is None:
            return True
        if b is None:
            return False
        return a < b


class OperationsDialog(QDialog):
    """The main Trading > Operations window: the list of operations."""

    COLUMNS = ['ENTRY', 'ASSET', 'PAPER', 'PLANNED', 'LONG/SHORT', 'ENTRY PRICE', 'VOLUME',
               'LEVERAGE', 'CURRENT PRICE', 'GAIN %', 'EXIT', 'EXIT PRICE', 'FINAL PNL']

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Operations")
        self.setModal(False)
        self.setMinimumSize(1250, 500)
        self._main_window = main_window
        self._updating = False

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        new_button = QPushButton("New operation")
        new_button.clicked.connect(self.on_new_operation)
        controls.addWidget(new_button)
        edit_button = QPushButton("Edit")
        edit_button.clicked.connect(self.on_edit_operation)
        controls.addWidget(edit_button)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.on_delete_operation)
        controls.addWidget(delete_button)
        controls.addStretch()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        controls.addWidget(refresh_button)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont('monospace', 9))
        header = self.table.horizontalHeader()
        for column in range(10):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemDoubleClicked.connect(self.on_edit_operation)
        self.table.cellClicked.connect(self.on_cell_clicked)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: gray;")
        layout.addWidget(self.summary_label)

        self.refresh()

    # -- data ---------------------------------------------------------------

    def _resolve_asset(self, asset_name):
        """The program's actual symbol for a typed asset name (case-insensitive),
        from the in-memory assets or the database - matching both the official
        symbols and the personalized display names; None when unknown."""
        name = (asset_name or '').strip()
        if not name:
            return None
        assets = self._main_window.assets
        if assets.get_asset(name) is not None:
            return name
        for symbol in assets.assets:
            if symbol.lower() == name.lower():
                return symbol
        database = self._main_window.database
        for symbol in database.get_symbols():
            if symbol.lower() == name.lower():
                return symbol
        for symbol in database.get_symbols():
            if (database.get_display_name(symbol) or '').lower() == name.lower():
                return symbol
        return None

    def _current_price(self, asset_name):
        """Last close of the asset from the program's data (memory or
        database), case-insensitive; None when the asset is unknown."""
        symbol = self._resolve_asset(asset_name)
        if symbol is None:
            return None
        data = self._main_window.assets.get_asset(symbol)
        if data is not None and data.bars:
            return data.bars[-1].close
        bars = self._main_window.database.load_bars(symbol)
        if bars is not None and bars.bars:
            return bars.bars[-1].close
        return None

    # -- table --------------------------------------------------------------

    @staticmethod
    def _fmt_price(value):
        """Plain price text without trailing zeros or scientific notation."""
        s = f"{value:.8f}".rstrip('0').rstrip('.')
        return s or '0'

    @staticmethod
    def _colored_item(text, color, value=None, bold=True):
        item = NumericItem(text)
        if value is not None:
            item.setData(Qt.ItemDataRole.UserRole, value)
        item.setBackground(color)
        item.setForeground(QColor('#FFFFFF'))
        if bold:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        return item

    @staticmethod
    def _numeric_item(text, value):
        item = NumericItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if value is not None:
            item.setData(Qt.ItemDataRole.UserRole, value)
        return item

    def _add_row(self, op):
        # the closed state is the explicit "open" flag; the exit price can
        # exist as a reference while the operation still runs. A planned
        # operation is still only a project that may or may not start: its
        # gain and PNL keep the plain look (no green/red) because there are
        # no real gains yet
        closed = not bool(op.get('open', 1))
        planned = bool(op.get('planned'))
        side = op.get('side') or 'Long'
        entry_price = op.get('entry_price')
        volume = op.get('volume')
        exit_price = op.get('exit_price')
        current_price = self._current_price(op.get('asset'))

        # directional price move: entry -> current while open, entry -> exit
        # once closed
        raw_gain = move_percent(side, entry_price, exit_price if closed else current_price)

        # the leverage multiplies the gain (unknown for 'Combined' or free
        # text: the raw price move is shown then)
        lev = leverage_value(op.get('leverage'))
        gain = raw_gain * lev if (raw_gain is not None and lev) else raw_gain

        # final PNL: computed with the exit price whenever there is one - the
        # actual result once closed, the potential PNL at the reference exit
        # price while open (shown plain, without the green/red background);
        # '-' when there is no exit price
        pnl = None
        pnl_money = False
        if exit_price is not None:
            raw_at_exit = move_percent(side, entry_price, exit_price)
            if raw_at_exit is not None:
                if volume:
                    pnl = raw_at_exit / 100.0 * volume * (lev or 1.0)
                    pnl_money = True
                else:
                    pnl = raw_at_exit * lev if lev else raw_at_exit

        row = self.table.rowCount()
        self.table.insertRow(row)

        # plain item: the entry column sorts by its ISO date text; the
        # operation id rides along in UserRole+1
        entry_item = QTableWidgetItem(op.get('entry_date') or '')
        entry_item.setData(Qt.ItemDataRole.UserRole + 1, op.get('id'))
        self.table.setItem(row, 0, entry_item)

        # the asset column shows the personalized display name when the asset
        # is in the program (the stored text keeps what the user typed)
        resolved = self._resolve_asset(op.get('asset'))
        if resolved is not None:
            asset_text = self._main_window.database.get_display_name(resolved) or resolved
        else:
            asset_text = op.get('asset') or ''
        self.table.setItem(row, 1, QTableWidgetItem(asset_text))

        paper_item = NumericItem('')
        paper_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsSelectable)
        paper_item.setCheckState(Qt.CheckState.Checked if op.get('paper')
                                 else Qt.CheckState.Unchecked)
        paper_item.setData(Qt.ItemDataRole.UserRole, 1 if op.get('paper') else 0)
        paper_item.setToolTip("Paper trading - click to toggle")
        self.table.setItem(row, 2, paper_item)

        planned_item = NumericItem('')
        planned_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
        planned_item.setCheckState(Qt.CheckState.Checked if planned
                                   else Qt.CheckState.Unchecked)
        planned_item.setData(Qt.ItemDataRole.UserRole, 1 if planned else 0)
        planned_item.setToolTip(
            "Planned operation - still only a project that may or may not start,\n"
            "so its gains are not real yet. Click to toggle: uncheck when it starts.")
        self.table.setItem(row, 3, planned_item)

        side_color = LONG_COLOR if side == 'Long' else SHORT_COLOR
        self.table.setItem(row, 4, self._colored_item(side, side_color))

        self.table.setItem(row, 5, self._numeric_item(self._fmt_price(entry_price), entry_price))

        if volume is not None:
            self.table.setItem(row, 6, self._numeric_item(self._fmt_price(volume), volume))
        else:
            self.table.setItem(row, 6, self._numeric_item('-', None))

        leverage_text = str(op.get('leverage') or '').strip()
        if leverage_text:
            display = f"{lev:g}x" if lev else leverage_text
            self.table.setItem(row, 7, self._numeric_item(display, lev))
        else:
            self.table.setItem(row, 7, self._numeric_item('-', None))

        if current_price is not None:
            self.table.setItem(row, 8, self._numeric_item(self._fmt_price(current_price), current_price))
        else:
            self.table.setItem(row, 8, self._numeric_item('-', None))

        if gain is not None:
            if planned:
                # planned operation: the projected gain keeps the plain look
                item = self._numeric_item(f"{gain:+.2f}%", gain)
                item.setToolTip("Planned operation - projected gain, not a real result")
                self.table.setItem(row, 9, item)
            else:
                color = LONG_COLOR if gain >= 0 else SHORT_COLOR
                self.table.setItem(row, 9, self._colored_item(f"{gain:+.2f}%", color, gain))
        else:
            self.table.setItem(row, 9, self._numeric_item('-', None))

        self.table.setItem(row, 10, QTableWidgetItem(op.get('exit_date') or ''))
        if exit_price is not None:
            self.table.setItem(row, 11, self._numeric_item(self._fmt_price(exit_price), exit_price))
        else:
            self.table.setItem(row, 11, QTableWidgetItem(''))

        if pnl is not None:
            suffix = '' if pnl_money else '%'
            text = f"{pnl:+.2f}{suffix}"
            if closed and not planned:
                color = LONG_COLOR if pnl >= 0 else SHORT_COLOR
                self.table.setItem(row, 12, self._colored_item(text, color, pnl))
            else:
                # open operation: the potential PNL at the reference exit,
                # plain (no background) while the operation runs; planned
                # operation: a projection, plain until it really starts
                item = self._numeric_item(text, pnl)
                item.setToolTip("Potential PNL at the reference exit price" if not planned
                                else "Planned operation - projected PNL, not a real result")
                self.table.setItem(row, 12, item)
        else:
            self.table.setItem(row, 12, self._numeric_item('-', None))

    def refresh(self):
        """Reload the list from the database (entry date, newest first)."""
        operations = self._main_window.database.load_operations()
        self._updating = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for op in operations:
            self._add_row(op)
        self.table.setSortingEnabled(True)
        self._updating = False
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)

        open_count = sum(1 for op in operations if bool(op.get('open', 1)))
        planned_count = sum(1 for op in operations if bool(op.get('planned')))
        self.summary_label.setText(
            f"{len(operations)} operation(s): {open_count} open, "
            f"{len(operations) - open_count} closed, {planned_count} planned")

    def _on_item_changed(self, item):
        """Persist the paper/planned checkboxes toggled directly in the list."""
        if self._updating or item.column() not in (2, 3):
            return
        op_id = self.table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole + 1)
        checked = item.checkState() == Qt.CheckState.Checked
        for op in self._main_window.database.load_operations():
            if op.get('id') == op_id:
                op['paper' if item.column() == 2 else 'planned'] = checked
                self._main_window.database.update_operation(op_id, op)
                break
        if item.column() == 3:
            # the planned flag drives the row's gain/PNL colors: rebuild so
            # unchecking it (the operation starts) brings the colors back
            self.refresh()

    # -- actions ------------------------------------------------------------

    def _selected_op_id(self):
        selected = self.table.selectedItems()
        if not selected:
            return None
        item = self.table.item(selected[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole + 1) if item else None

    def _selected_op(self):
        op_id = self._selected_op_id()
        if op_id is None:
            return None
        for op in self._main_window.database.load_operations():
            if op.get('id') == op_id:
                return op
        return None

    def on_cell_clicked(self, row, column):
        """Clicking the asset name opens that asset's chart."""
        if column == 1:
            self._open_asset_chart(self.table.item(row, 1).text())

    def _open_asset_chart(self, asset_name):
        symbol = self._resolve_asset(asset_name)
        if symbol is None:
            QMessageBox.warning(self, "Operations",
                                f"The asset \"{asset_name}\" is not in the program.\n"
                                "Download it first to see its chart.")
            return
        self._main_window.load_chart(symbol)

    # -- operation lines on the asset's chart -------------------------------

    def _op_line_entries(self, op_id, op):
        """The operation's hline drawing entries (tagged with its id)."""
        entries = []
        entry_color = ENTRY_LONG_LINE if op.get('side') == 'Long' else ENTRY_SHORT_LINE
        entries.append(('entry', op.get('entry_price'), entry_color))
        if op.get('exit_price') is not None:
            entries.append(('exit', op['exit_price'], EXIT_LINE))
        return [(kind, price, color) for kind, price, color in entries if price]

    def _sync_operation_lines(self, op_id, op):
        """(Re)draw the operation's entry/exit lines on its asset's chart:
        remove the old tagged lines, add the new prices. Works whether the
        chart is open (draws live) or not (updates the stored drawings, so
        the lines appear when the chart is opened)."""
        symbol = self._resolve_asset(op.get('asset'))
        if symbol is None:
            return                      # the asset is not in the program
        self._remove_op_lines(symbol, op_id)
        tab = self._main_window.chart_tabs.tabs.get(symbol)
        if tab is not None:
            chart_view = tab.chart_view
            for kind, price, color in self._op_line_entries(op_id, op):
                chart_view.add_operation_hline(price, color, op_id, kind)
            self._main_window.database.save_drawings(symbol, chart_view.get_drawings())
        else:
            drawings = self._main_window.database.load_drawings(symbol)
            for kind, price, color in self._op_line_entries(op_id, op):
                drawings.append({'type': 'hline', 'color': color, 'snap': '',
                                 'params': {'operation_id': op_id, 'op_kind': kind},
                                 'points': [[0, price]], 'width': 1})
            self._main_window.database.save_drawings(symbol, drawings)

    def _remove_op_lines(self, symbol, op_id):
        """Remove an operation's lines from the open chart and the store."""
        tab = self._main_window.chart_tabs.tabs.get(symbol)
        if tab is not None:
            tab.chart_view.remove_operation_hlines(op_id)
            self._main_window.database.save_drawings(symbol, tab.chart_view.get_drawings())
        else:
            drawings = self._main_window.database.load_drawings(symbol)
            kept = [d for d in drawings
                    if not (d.get('type') == 'hline'
                            and (d.get('params') or {}).get('operation_id') == op_id)]
            if len(kept) != len(drawings):
                self._main_window.database.save_drawings(symbol, kept)

    def on_new_operation(self):
        dialog = OperationFormDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            op = dialog.get_operation()
            op = self._with_official_asset(op)
            op_id = self._main_window.database.save_operation(op)
            self._sync_operation_lines(op_id, op)
            self.refresh()

    def _with_official_asset(self, op):
        """Store the official ticker: a typed name that resolves to an asset in
        the program is replaced by its official symbol (the listing shows the
        personalized name either way), so the operation keeps pointing at the
        asset even if the personalized name changes later."""
        resolved = self._resolve_asset(op.get('asset'))
        if resolved:
            op['asset'] = resolved
        return op

    def on_edit_operation(self, item=None):
        # clicking or double-clicking the asset name opens its chart instead
        if item is not None and item.column() == 1:
            return
        op = self._selected_op()
        if op is None:
            QMessageBox.information(self, "Operations", "Select an operation first.")
            return
        dialog = OperationFormDialog(operation=op, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_op = self._with_official_asset(dialog.get_operation())
            self._main_window.database.update_operation(op['id'], new_op)
            self._sync_operation_lines(op['id'], new_op)
            self.refresh()

    def on_delete_operation(self):
        op_id = self._selected_op_id()
        if op_id is None:
            QMessageBox.information(self, "Operations", "Select an operation first.")
            return
        op = self._selected_op()
        answer = QMessageBox.question(self, "Operations", "Delete the selected operation?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._main_window.database.delete_operation(op_id)
            if op is not None:
                symbol = self._resolve_asset(op.get('asset'))
                if symbol is not None:
                    self._remove_op_lines(symbol, op_id)
            self.refresh()