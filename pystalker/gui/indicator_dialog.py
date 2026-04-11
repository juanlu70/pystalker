"""
PyStalker - Indicator Dialog for configuring indicator parameters
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, 
    QSpinBox, QDoubleSpinBox, QDialogButtonBox, QGroupBox,
    QFormLayout, QPushButton, QColorDialog, QListWidget,
    QInputDialog, QMessageBox, QCheckBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from ..core.indicators import IndicatorManager


class IndicatorDialog(QDialog):
    def __init__(self, parent=None, existing_indicators=None):
        super().__init__(parent)
        self.setWindowTitle("Add Indicator")
        self.setMinimumWidth(450)
        self.setMinimumHeight(350)
        
        self.param_widgets = {}
        self.current_indicator = None
        self.line_colors = {}
        self.existing_indicators = existing_indicators or []
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        indicator_group = QGroupBox("Select Indicator")
        indicator_layout = QFormLayout()
        
        type_label = QLabel("Type:")
        self.type_combo = QComboBox()
        
        overlay_indicators = IndicatorManager.get_overlay_indicators()
        separate_indicators = IndicatorManager.get_separate_indicators()
        
        self.type_combo.addItem("-- Overlay Indicators --")
        for name in overlay_indicators.keys():
            self.type_combo.addItem(name)
        
        self.type_combo.addItem("-- Separate Indicators --")
        for name in separate_indicators.keys():
            self.type_combo.addItem(name)
        
        self.type_combo.currentTextChanged.connect(self.on_indicator_changed)
        indicator_layout.addRow(type_label, self.type_combo)
        indicator_group.setLayout(indicator_layout)
        layout.addWidget(indicator_group)
        
        self.params_group = QGroupBox("Parameters")
        self.params_layout = QFormLayout()
        self.params_group.setLayout(self.params_layout)
        layout.addWidget(self.params_group)
        
        self.params_group.setVisible(False)
        
        self.colors_group = QGroupBox("Line Colors")
        self.colors_layout = QFormLayout()
        self.colors_group.setLayout(self.colors_layout)
        layout.addWidget(self.colors_group)
        
        self.colors_group.setVisible(False)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.on_indicator_changed(self.type_combo.currentText())
    
    def choose_line_color(self, line_name):
        current_color = self.line_colors.get(line_name, '#00BFFF')
        color = QColorDialog.getColor(QColor(current_color), self, f"Select Color for {line_name}")
        if color.isValid():
            self.line_colors[line_name] = color.name()
            self._update_color_labels()
    
    def _update_color_labels(self):
        for line_name, label in self._color_labels.items():
            c = self.line_colors.get(line_name, '#00BFFF')
            label.setStyleSheet(f"background-color: {c}; border: 1px solid white;")
    
    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
    
    def on_indicator_changed(self, indicator_name):
        if indicator_name.startswith("--"):
            self.params_group.setVisible(False)
            self.colors_group.setVisible(False)
            return
        
        self.current_indicator = indicator_name
        
        self._clear_layout(self.params_layout)
        self._clear_layout(self.colors_layout)
        
        self.param_widgets.clear()
        self.line_colors.clear()
        self._color_labels = {}
        
        all_indicators = IndicatorManager.ALL_INDICATORS
        if indicator_name not in all_indicators:
            return
        
        params = all_indicators[indicator_name]['params']
        self.params_group.setVisible(True)
        
        line_defaults = IndicatorManager.LINE_DEFAULTS.get(indicator_name, [])
        for line_def in line_defaults:
            self.line_colors[line_def['name']] = line_def['color']
        
        for param_name, default_value in params.items():
            label = QLabel(f"{param_name}:")
            
            if isinstance(default_value, float):
                spinbox = QDoubleSpinBox()
                spinbox.setRange(0.1, 9999.9)
                spinbox.setSingleStep(0.1)
                spinbox.setDecimals(1)
                spinbox.setValue(default_value)
            elif isinstance(default_value, int):
                spinbox = QSpinBox()
                spinbox.setRange(1, 9999)
                spinbox.setSingleStep(1)
                spinbox.setValue(default_value)
            else:
                spinbox = QSpinBox()
                spinbox.setRange(0, 9999)
                spinbox.setValue(default_value if isinstance(default_value, int) else 20)
            
            self.param_widgets[param_name] = spinbox
            self.params_layout.addRow(label, spinbox)
        
        if len(line_defaults) > 1:
            self.colors_group.setVisible(True)
            for line_def in line_defaults:
                line_name = line_def['name']
                color_label = QLabel()
                color_label.setFixedSize(60, 25)
                color_label.setStyleSheet(f"background-color: {self.line_colors[line_name]}; border: 1px solid white;")
                color_label.setCursor(Qt.CursorShape.PointingHandCursor)
                color_label.mousePressEvent = lambda e, n=line_name: self.choose_line_color(n)
                self._color_labels[line_name] = color_label
                
                btn = QPushButton(f"Choose {line_name} Color")
                btn.clicked.connect(lambda checked, n=line_name: self.choose_line_color(n))
                
                row_layout = QHBoxLayout()
                row_layout.addWidget(color_label)
                row_layout.addWidget(btn)
                row_layout.addStretch()
                self.colors_layout.addRow(f"{line_name}:", row_layout)
        else:
            self.colors_group.setVisible(False)
            self.line_colors.clear()
        
        self.params_group.setVisible(True)
    
    def get_indicator_name(self):
        text = self.type_combo.currentText()
        if text.startswith("--"):
            return None
        return text
    
    def get_indicator_params(self):
        params = {}
        for param_name, widget in self.param_widgets.items():
            if isinstance(widget, QDoubleSpinBox):
                params[param_name] = widget.value()
            else:
                params[param_name] = widget.value()
        return params
    
    def get_indicator_color(self):
        if self.line_colors:
            first_color = list(self.line_colors.values())[0]
            return first_color
        return '#00BFFF'
    
    def get_indicator_colors(self):
        return dict(self.line_colors)


class EditIndicatorsDialog(QDialog):
    def __init__(self, indicators, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Indicators")
        self.setMinimumWidth(550)
        self.setMinimumHeight(400)
        
        import copy
        self.indicators = copy.deepcopy(indicators)  # Deep copy to preserve all fields
        self.result_data = None
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        list_group = QGroupBox("Indicators on Chart (Click to toggle visibility)")
        list_layout = QVBoxLayout()
        
        self.indicator_list = QListWidget()
        for ind in self.indicators:
            visible_icon = "👁" if ind.get('visible', True) else "🚫"
            color_box = f" [{ind.get('color', '#FFFFFF')}]"
            display_name = ind.get('name', ind.get('indicator_name', 'Unknown'))
            self.indicator_list.addItem(f"{visible_icon} {display_name}{color_box} - {ind.get('params', {})}")
        list_layout.addWidget(self.indicator_list)
        
        btn_layout = QHBoxLayout()
        
        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self.edit_selected)
        btn_layout.addWidget(edit_btn)
        
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self.remove_selected)
        btn_layout.addWidget(remove_btn)
        
        list_layout.addLayout(btn_layout)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept_changes)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def edit_selected(self):
        current_row = self.indicator_list.currentRow()
        if current_row < 0:
            return
        
        ind = self.indicators[current_row]
        
        from ..core.indicators import IndicatorManager
        all_indicators = IndicatorManager.ALL_INDICATORS
        
        dialog = IndicatorDialog(self)
        indicator_name = ind.get('indicator_name', ind.get('name', 'Unknown'))
        dialog.type_combo.setCurrentText(indicator_name)
        dialog.on_indicator_changed(indicator_name)
        
        if ind.get('colors'):
            dialog.line_colors = dict(ind['colors'])
            dialog._update_color_labels()
        elif ind.get('color'):
            line_defaults = IndicatorManager.LINE_DEFAULTS.get(indicator_name, [])
            if len(line_defaults) <= 1:
                dialog.line_colors = {}
            else:
                dialog.line_colors = {ld['name']: ind['color'] for ld in line_defaults}
            dialog._update_color_labels()
        
        for param_name, value in ind.get('params', {}).items():
            if param_name in dialog.param_widgets:
                dialog.param_widgets[param_name].setValue(value)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.indicators[current_row] = {
                'name': ind.get('name', dialog.get_indicator_name()),
                'indicator_name': dialog.get_indicator_name(),
                'type': IndicatorManager.ALL_INDICATORS.get(dialog.get_indicator_name(), {}).get('type', 'overlay'),
                'params': dialog.get_indicator_params(),
                'color': dialog.get_indicator_color(),
                'colors': dialog.get_indicator_colors(),
                'visible': ind.get('visible', True)
            }
            self.refresh_list()
    
    def toggle_visibility(self, item):
        current_row = self.indicator_list.currentRow()
        if current_row < 0:
            return
        
        ind = self.indicators[current_row]
        ind['visible'] = not ind.get('visible', True)
        self.refresh_list()
    
    def remove_selected(self):
        current_row = self.indicator_list.currentRow()
        if current_row >= 0:
            del self.indicators[current_row]
            self.refresh_list()
    
    def refresh_list(self):
        self.indicator_list.clear()
        for ind in self.indicators:
            visible_icon = "👁" if ind.get('visible', True) else "🚫"
            display_name = ind.get('name', ind.get('indicator_name', 'Unknown'))
            colors = ind.get('colors', {})
            if colors:
                color_str = ', '.join(f"{k}: {v}" for k, v in colors.items())
            else:
                color_str = ind.get('color', '#FFFFFF')
            self.indicator_list.addItem(f"{visible_icon} {display_name} [{color_str}] - {ind.get('params', {})}")
    
    def accept_changes(self):
        self.result_data = self.indicators
        self.accept()
    
    def get_indicators(self):
        return self.result_data