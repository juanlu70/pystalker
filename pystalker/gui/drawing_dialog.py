from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QColorDialog, QComboBox, QDoubleSpinBox, QDialogButtonBox,
    QHeaderView, QLabel, QGroupBox, QFormLayout, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor


class EditTrendlinesDialog(QDialog):
    def __init__(self, drawings, parent=None):
        super().__init__(parent)
        self.drawings = drawings
        self.setWindowTitle("Edit Trendlines")
        self.setMinimumWidth(650)
        self.setMinimumHeight(400)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self._removed_items = []

        if not self.drawings:
            layout.addWidget(QLabel("No trendlines on this chart."))
            btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btn.accepted.connect(self.accept)
            layout.addWidget(btn)
            return

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Color", "Snap", "Points"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        edit_group = QGroupBox("Edit Selected Trendline")
        edit_layout = QFormLayout()

        self.color_label = QLabel()
        self.color_label.setFixedSize(60, 25)
        self.color_label.setStyleSheet("background-color: #FFFFFF; border: 1px solid white;")
        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self._choose_color)
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_label)
        color_row.addWidget(self.color_btn)
        color_row.addStretch()
        edit_layout.addRow("Color:", color_row)

        self.snap_combo = QComboBox()
        self.snap_combo.addItems(["None", "Open", "High", "Low", "Close"])
        edit_layout.addRow("Snap:", self.snap_combo)

        snap_values = {'': 0, 'open': 1, 'high': 2, 'low': 3, 'close': 4}
        self.snap_value_map = {0: '', 1: 'open', 2: 'high', 3: 'low', 4: 'close'}

        self.p1x_spin = QDoubleSpinBox()
        self.p1x_spin.setDecimals(0)
        self.p1x_spin.setRange(0, 999999)
        self.p1y_spin = QDoubleSpinBox()
        self.p1y_spin.setDecimals(2)
        self.p1y_spin.setRange(-999999, 999999)
        self.p2x_spin = QDoubleSpinBox()
        self.p2x_spin.setDecimals(0)
        self.p2x_spin.setRange(0, 999999)
        self.p2y_spin = QDoubleSpinBox()
        self.p2y_spin.setDecimals(2)
        self.p2y_spin.setRange(-999999, 999999)

        p1_layout = QHBoxLayout()
        p1_layout.addWidget(QLabel("Bar:"))
        p1_layout.addWidget(self.p1x_spin)
        p1_layout.addWidget(QLabel("Y:"))
        p1_layout.addWidget(self.p1y_spin)
        edit_layout.addRow("Point 1:", p1_layout)

        p2_layout = QHBoxLayout()
        p2_layout.addWidget(QLabel("Bar:"))
        p2_layout.addWidget(self.p2x_spin)
        p2_layout.addWidget(QLabel("Y:"))
        p2_layout.addWidget(self.p2y_spin)
        edit_layout.addRow("Point 2:", p2_layout)

        apply_btn = QPushButton("Apply Changes")
        apply_btn.clicked.connect(self._apply_changes)
        edit_layout.addRow(apply_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        edit_layout.addRow(remove_btn)

        edit_group.setLayout(edit_layout)
        layout.addWidget(edit_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._populate_table()
        self.table.selectRow(0)
        self.table.currentCellChanged.connect(self._on_selection_changed)
        self._load_selected(0, 0)

    def _populate_table(self):
        self.table.setRowCount(len(self.drawings))
        for i, d in enumerate(self.drawings):
            item_num = QTableWidgetItem(str(i + 1))
            item_num.setFlags(item_num.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, item_num)

            color_item = QTableWidgetItem(d.get('color', '#FFFFFF'))
            color_item.setBackground(QColor(d.get('color', '#FFFFFF')))
            self.table.setItem(i, 1, color_item)

            snap = d.get('snap', '') or 'None'
            snap_item = QTableWidgetItem(snap.capitalize() if snap else 'None')
            self.table.setItem(i, 2, snap_item)

            points = d.get('points', [])
            pts_str = ', '.join(f'({p[0]}, {p[1]:.2f})' for p in points)
            self.table.setItem(i, 3, QTableWidgetItem(pts_str))

    def _on_selection_changed(self, row, col, prev_row, prev_col):
        self._load_selected(row, col)

    def _load_selected(self, row, col):
        if row < 0 or row >= len(self.drawings):
            return
        d = self.drawings[row]
        color = d.get('color', '#FFFFFF')
        self.color_label.setStyleSheet(f"background-color: {color}; border: 1px solid white;")
        self._current_row = row

        snap = d.get('snap', '')
        snap_map = {'': 0, 'open': 1, 'high': 2, 'low': 3, 'close': 4}
        self.snap_combo.setCurrentIndex(snap_map.get(snap, 0))

        points = d.get('points', [])
        if len(points) >= 2:
            self.p1x_spin.setValue(points[0][0])
            self.p1y_spin.setValue(points[0][1])
            self.p2x_spin.setValue(points[1][0])
            self.p2y_spin.setValue(points[1][1])

    def _choose_color(self):
        row = getattr(self, '_current_row', 0)
        if row >= len(self.drawings):
            return
        current = self.drawings[row].get('color', '#FFFFFF')
        color = QColorDialog.getColor(QColor(current), self, "Select Trendline Color")
        if color.isValid():
            self.color_label.setStyleSheet(f"background-color: {color.name()}; border: 1px solid white;")

    def _apply_changes(self):
        row = getattr(self, '_current_row', -1)
        if row < 0 or row >= len(self.drawings):
            return
        d = self.drawings[row]
        d['color'] = self.color_label.palette().color(self.color_label.backgroundRole()).name()
        d['snap'] = self.snap_value_map.get(self.snap_combo.currentIndex(), '')
        d['points'] = [
            (int(self.p1x_spin.value()), self.p1y_spin.value()),
            (int(self.p2x_spin.value()), self.p2y_spin.value())
        ]
        self._populate_table()
        self.table.selectRow(row)

    def _remove_selected(self):
        row = getattr(self, '_current_row', -1)
        if row < 0 or row >= len(self.drawings):
            return
        removed = self.drawings.pop(row)
        if 'item' in removed:
            self._removed_items.append(removed['item'])
        self._populate_table()
        if self.drawings:
            new_row = min(row, len(self.drawings) - 1)
            self.table.selectRow(new_row)
            self._load_selected(new_row, 0)
        else:
            self.accept()

    def get_drawings(self):
        return self.drawings
    
    def get_removed_items(self):
        return self._removed_items