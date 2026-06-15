from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QColorDialog, QComboBox, QSpinBox, QDoubleSpinBox, QDialogButtonBox,
    QHeaderView, QLabel, QGroupBox, QFormLayout, QMessageBox, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from .shared import SNAP_VALUES, SNAP_INDEX_TO_MODE


DRAWING_TYPE_LABELS = {'trendline': 'Trendline', 'hline': 'HLine', 'vline': 'VLine', 'asc_channel': 'Asc Channel', 'desc_channel': 'Desc Channel'}


class EditDrawingsDialog(QDialog):
    def __init__(self, drawings, parent=None):
        super().__init__(parent)
        self.drawings = drawings
        self.setWindowTitle("Edit Drawings")
        self.setMinimumWidth(650)
        self.setMinimumHeight(400)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        self._removed_items = []

        if not self.drawings:
            layout.addWidget(QLabel("No drawings on this chart."))
            btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
            btn.accepted.connect(self.accept)
            layout.addWidget(btn)
            return

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["#", "Type", "Color", "Position"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        edit_group = QGroupBox("Edit Selected Drawing")
        edit_layout = QFormLayout()

        self.color_label = QLabel()
        self.color_label.setFixedSize(60, 25)
        self.color_label.setStyleSheet("background-color: #FFFFFF; border: 1px solid white;")
        self.color_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_label.mousePressEvent = lambda e: self._choose_color()
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
        
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 10)
        self.width_spin.setValue(1)
        edit_layout.addRow("Width:", self.width_spin)

        self.middle_color_label = QLabel()
        self.middle_color_label.setFixedSize(60, 25)
        self.middle_color_label.setStyleSheet("background-color: #808080; border: 1px solid white;")
        self.middle_color_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.middle_color_label.mousePressEvent = lambda e: self._choose_middle_color()
        self.middle_color_btn = QPushButton("Choose Color")
        self.middle_color_btn.clicked.connect(self._choose_middle_color)
        middle_color_row = QHBoxLayout()
        middle_color_row.addWidget(self.middle_color_label)
        middle_color_row.addWidget(self.middle_color_btn)
        middle_color_row.addStretch()
        self.middle_color_row_widget = QWidget()
        middle_color_layout = QVBoxLayout(self.middle_color_row_widget)
        middle_color_layout.setContentsMargins(0, 0, 0, 0)
        middle_color_label_layout = QHBoxLayout()
        middle_color_label_layout.addWidget(QLabel("Middle Color:"))
        middle_color_label_layout.addStretch()
        middle_color_layout.addLayout(middle_color_label_layout)
        middle_color_layout.addLayout(middle_color_row)
        edit_layout.addRow(self.middle_color_row_widget)
        self.middle_color_row_widget.hide()

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

        self.p1_bar_label = QLabel("Bar:")
        self.p1_y_label = QLabel("Y:")
        self.p2_bar_label = QLabel("Bar:")
        self.p2_y_label = QLabel("Y:")

        self.p1_layout = QHBoxLayout()
        self.p1_layout.addWidget(self.p1_bar_label)
        self.p1_layout.addWidget(self.p1x_spin)
        self.p1_layout.addWidget(self.p1_y_label)
        self.p1_layout.addWidget(self.p1y_spin)

        self.p2_layout = QHBoxLayout()
        self.p2_layout.addWidget(self.p2_bar_label)
        self.p2_layout.addWidget(self.p2x_spin)
        self.p2_layout.addWidget(self.p2_y_label)
        self.p2_layout.addWidget(self.p2y_spin)

        self.p1_label = QLabel("Point 1:")
        self.p2_label = QLabel("Point 2:")
        edit_layout.addRow(self.p1_label, self.p1_layout)
        edit_layout.addRow(self.p2_label, self.p2_layout)

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

            dtype = d.get('type', 'trendline')
            type_item = QTableWidgetItem(DRAWING_TYPE_LABELS.get(dtype, dtype))
            self.table.setItem(i, 1, type_item)

            color_item = QTableWidgetItem(d.get('color', '#FFFFFF'))
            color_item.setBackground(QColor(d.get('color', '#FFFFFF')))
            self.table.setItem(i, 2, color_item)

            pos_str = self._format_position(d)
            self.table.setItem(i, 3, QTableWidgetItem(pos_str))

    def _format_position(self, d):
        dtype = d.get('type', 'trendline')
        points = d.get('points', [])
        if dtype == 'hline' and points:
            return f"Y: {points[0][1]:.2f}"
        elif dtype == 'vline' and points:
            return f"Bar: {int(points[0][0])}"
        elif dtype in ('asc_channel', 'desc_channel') and len(points) >= 3:
            return f"BL:({int(points[0][0])}, {points[0][1]:.2f}) BR:({int(points[1][0])}, {points[1][1]:.2f}) H:{points[2][1]:.2f}"
        else:
            return ', '.join(f'({p[0]}, {p[1]:.2f})' for p in points)

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
        self.snap_combo.setCurrentIndex(SNAP_VALUES.get(snap, 0))
        self.width_spin.setValue(d.get('width', 1))

        dtype = d.get('type', 'trendline')
        if dtype in ('asc_channel', 'desc_channel'):
            middle_color = d.get('middle_color', '#808080')
            self.middle_color_label.setStyleSheet(f"background-color: {middle_color}; border: 1px solid white;")
            self.middle_color_row_widget.show()
        else:
            self.middle_color_row_widget.hide()
        points = d.get('points', [])

        if dtype == 'hline':
            self.p1_label.setText("Point 1:")
            self.p1_bar_label.setVisible(False)
            self.p1x_spin.setVisible(False)
            self.p1_y_label.setVisible(True)
            self.p1y_spin.setVisible(True)
            self.p1y_spin.setValue(points[0][1] if points else 0)
            self.p2_label.setVisible(False)
            self.p2_bar_label.setVisible(False)
            self.p2x_spin.setVisible(False)
            self.p2_y_label.setVisible(False)
            self.p2y_spin.setVisible(False)
        elif dtype == 'vline':
            self.p1_label.setText("Point 1:")
            self.p1_bar_label.setVisible(True)
            self.p1x_spin.setVisible(True)
            self.p1_y_label.setVisible(False)
            self.p1y_spin.setVisible(False)
            self.p1x_spin.setValue(points[0][0] if points else 0)
            self.p2_label.setVisible(False)
            self.p2_bar_label.setVisible(False)
            self.p2x_spin.setVisible(False)
            self.p2_y_label.setVisible(False)
            self.p2y_spin.setVisible(False)
        elif dtype in ('asc_channel', 'desc_channel'):
            self.p1_label.setText("BL Point:")
            self.p1_bar_label.setVisible(True)
            self.p1x_spin.setVisible(True)
            self.p1_y_label.setVisible(True)
            self.p1y_spin.setVisible(True)
            self.p2_label.setText("BR Point:")
            self.p2_bar_label.setVisible(True)
            self.p2x_spin.setVisible(True)
            self.p2_y_label.setVisible(True)
            self.p2y_spin.setVisible(True)
            if len(points) >= 3:
                self.p1x_spin.setValue(points[0][0])
                self.p1y_spin.setValue(points[0][1])
                self.p2x_spin.setValue(points[1][0])
                self.p2y_spin.setValue(points[1][1])
        else:
            self.p1_label.setText("Point 1:")
            self.p1_bar_label.setVisible(True)
            self.p1x_spin.setVisible(True)
            self.p1_y_label.setVisible(True)
            self.p1y_spin.setVisible(True)
            self.p2_label.setVisible(True)
            self.p2_bar_label.setVisible(True)
            self.p2x_spin.setVisible(True)
            self.p2_y_label.setVisible(True)
            self.p2y_spin.setVisible(True)
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
        color = QColorDialog.getColor(QColor(current), self, "Select Color")
        if color.isValid():
            self.color_label.setStyleSheet(f"background-color: {color.name()}; border: 1px solid white;")

    def _choose_middle_color(self):
        row = getattr(self, '_current_row', 0)
        if row >= len(self.drawings):
            return
        current = self.drawings[row].get('middle_color', '#808080')
        color = QColorDialog.getColor(QColor(current), self, "Select Middle Line Color")
        if color.isValid():
            self.middle_color_label.setStyleSheet(f"background-color: {color.name()}; border: 1px solid white;")

    def _apply_changes(self):
        row = getattr(self, '_current_row', -1)
        if row < 0 or row >= len(self.drawings):
            return
        d = self.drawings[row]
        d['color'] = self.color_label.palette().color(self.color_label.backgroundRole()).name()
        d['snap'] = SNAP_INDEX_TO_MODE.get(self.snap_combo.currentIndex(), '')
        d['width'] = self.width_spin.value()

        dtype = d.get('type', 'trendline')
        if dtype in ('asc_channel', 'desc_channel'):
            d['middle_color'] = self.middle_color_label.palette().color(self.middle_color_label.backgroundRole()).name()
        if dtype == 'hline':
            d['points'] = [(0, self.p1y_spin.value())]
        elif dtype == 'vline':
            d['points'] = [(int(self.p1x_spin.value()), 0)]
        elif dtype in ('asc_channel', 'desc_channel'):
            d['points'] = [
                (int(self.p1x_spin.value()), self.p1y_spin.value()),
                (int(self.p2x_spin.value()), self.p2y_spin.value()),
                (0, d['points'][2][1])
            ]
        else:
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


class DrawingSettingsDialog(QDialog):
    def __init__(self, drawing, parent=None):
        super().__init__(parent)
        self.drawing = drawing
        self.drawing_type = drawing.get('type', 'trendline')
        self.setWindowTitle(f"{DRAWING_TYPE_LABELS.get(self.drawing_type, 'Drawing')} Settings")
        self.setMinimumWidth(300)
        self._color = drawing.get('color', '#FFFFFF')
        self._middle_color = drawing.get('middle_color', '#808080')
        self._snap = drawing.get('snap', '')
        self._width = drawing.get('width', 1)
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        
        self.color_label = QLabel()
        self.color_label.setFixedSize(60, 25)
        self.color_label.setStyleSheet(f"background-color: {self._color}; border: 1px solid white;")
        self.color_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_label.mousePressEvent = lambda e: self._choose_color()
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_label)
        color_btn = QPushButton("Choose Color")
        color_btn.clicked.connect(self._choose_color)
        color_row.addWidget(color_btn)
        color_row.addStretch()
        form.addRow("Color:", color_row)
        
        self.snap_combo = QComboBox()
        self.snap_combo.addItems(["None", "Open", "High", "Low", "Close"])
        self.snap_combo.setCurrentIndex(SNAP_VALUES.get(self._snap, 0))
        form.addRow("Snap:", self.snap_combo)
        
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 10)
        self.width_spin.setValue(self._width)
        form.addRow("Width:", self.width_spin)
        
        points = self.drawing.get('points', [])
        if self.drawing_type == 'hline' and points:
            self.y_spin = QDoubleSpinBox()
            self.y_spin.setDecimals(2)
            self.y_spin.setRange(-999999, 999999)
            self.y_spin.setValue(points[0][1])
            form.addRow("Y:", self.y_spin)
        elif self.drawing_type == 'vline' and points:
            self.bar_spin = QSpinBox()
            self.bar_spin.setRange(0, 999999)
            self.bar_spin.setValue(int(points[0][0]))
            form.addRow("Bar:", self.bar_spin)
        elif self.drawing_type in ('asc_channel', 'desc_channel') and len(points) >= 3:
            self.p1x_spin = QDoubleSpinBox()
            self.p1x_spin.setDecimals(0)
            self.p1x_spin.setRange(0, 999999)
            self.p1x_spin.setValue(int(points[0][0]))
            self.p1y_spin = QDoubleSpinBox()
            self.p1y_spin.setDecimals(2)
            self.p1y_spin.setRange(-999999, 999999)
            self.p1y_spin.setValue(points[0][1])
            p1_row = QHBoxLayout()
            p1_row.addWidget(QLabel("Bar:"))
            p1_row.addWidget(self.p1x_spin)
            p1_row.addWidget(QLabel("Y:"))
            p1_row.addWidget(self.p1y_spin)
            form.addRow("BL Point:", p1_row)
            
            self.p2x_spin = QDoubleSpinBox()
            self.p2x_spin.setDecimals(0)
            self.p2x_spin.setRange(0, 999999)
            self.p2x_spin.setValue(int(points[1][0]))
            self.p2y_spin = QDoubleSpinBox()
            self.p2y_spin.setDecimals(2)
            self.p2y_spin.setRange(-999999, 999999)
            self.p2y_spin.setValue(points[1][1])
            p2_row = QHBoxLayout()
            p2_row.addWidget(QLabel("Bar:"))
            p2_row.addWidget(self.p2x_spin)
            p2_row.addWidget(QLabel("Y:"))
            p2_row.addWidget(self.p2y_spin)
            form.addRow("BR Point:", p2_row)
            
            self.height_spin = QDoubleSpinBox()
            self.height_spin.setDecimals(2)
            self.height_spin.setRange(-999999, 999999)
            self.height_spin.setValue(points[2][1])
            form.addRow("Height:", self.height_spin)
            
            self.middle_color_label = QLabel()
            self.middle_color_label.setFixedSize(60, 25)
            self.middle_color_label.setStyleSheet(f"background-color: {self._middle_color}; border: 1px solid white;")
            self.middle_color_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.middle_color_label.mousePressEvent = lambda e: self._choose_middle_color()
            middle_color_btn = QPushButton("Choose Color")
            middle_color_btn.clicked.connect(self._choose_middle_color)
            middle_color_row = QHBoxLayout()
            middle_color_row.addWidget(self.middle_color_label)
            middle_color_row.addWidget(middle_color_btn)
            middle_color_row.addStretch()
            form.addRow("Middle Line:", middle_color_row)
        elif len(points) >= 2:
            self.p1x_spin = QDoubleSpinBox()
            self.p1x_spin.setDecimals(0)
            self.p1x_spin.setRange(0, 999999)
            self.p1x_spin.setValue(int(points[0][0]))
            self.p1y_spin = QDoubleSpinBox()
            self.p1y_spin.setDecimals(2)
            self.p1y_spin.setRange(-999999, 999999)
            self.p1y_spin.setValue(points[0][1])
            p1_row = QHBoxLayout()
            p1_row.addWidget(QLabel("Bar:"))
            p1_row.addWidget(self.p1x_spin)
            p1_row.addWidget(QLabel("Y:"))
            p1_row.addWidget(self.p1y_spin)
            form.addRow("Point 1:", p1_row)
            
            self.p2x_spin = QDoubleSpinBox()
            self.p2x_spin.setDecimals(0)
            self.p2x_spin.setRange(0, 999999)
            self.p2x_spin.setValue(int(points[1][0]))
            self.p2y_spin = QDoubleSpinBox()
            self.p2y_spin.setDecimals(2)
            self.p2y_spin.setRange(-999999, 999999)
            self.p2y_spin.setValue(points[1][1])
            p2_row = QHBoxLayout()
            p2_row.addWidget(QLabel("Bar:"))
            p2_row.addWidget(self.p2x_spin)
            p2_row.addWidget(QLabel("Y:"))
            p2_row.addWidget(self.p2y_spin)
            form.addRow("Point 2:", p2_row)
        
        layout.addLayout(form)
        
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove)
        layout.addWidget(remove_btn)
        
        self._removed = False
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _choose_color(self):
        color = QColorDialog.getColor(QColor(self._color), self, "Select Color")
        if color.isValid():
            self._color = color.name()
            self.color_label.setStyleSheet(f"background-color: {self._color}; border: 1px solid white;")
    
    def _choose_middle_color(self):
        color = QColorDialog.getColor(QColor(self._middle_color), self, "Select Middle Line Color")
        if color.isValid():
            self._middle_color = color.name()
            self.middle_color_label.setStyleSheet(f"background-color: {self._middle_color}; border: 1px solid white;")
    
    def get_color(self):
        return self._color
    
    def get_snap(self):
        return SNAP_INDEX_TO_MODE.get(self.snap_combo.currentIndex(), '')
    
    def get_width(self):
        return self.width_spin.value()
    
    def get_y(self):
        if hasattr(self, 'y_spin'):
            return self.y_spin.value()
        return None
    
    def get_bar(self):
        if hasattr(self, 'bar_spin'):
            return self.bar_spin.value()
        return None
    
    def get_point1(self):
        if hasattr(self, 'p1x_spin'):
            return (int(self.p1x_spin.value()), self.p1y_spin.value())
        return None
    
    def get_point2(self):
        if hasattr(self, 'p2x_spin'):
            return (int(self.p2x_spin.value()), self.p2y_spin.value())
        return None
    
    def get_height(self):
        if hasattr(self, 'height_spin'):
            return self.height_spin.value()
        return None
    
    def get_middle_color(self):
        return self._middle_color
    
    def _remove(self):
        self._removed = True
        self.accept()
    
    def is_removed(self):
        return self._removed