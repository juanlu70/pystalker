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
        self.selected_color = '#00BFFF'
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
        
        color_group = QGroupBox("Line Color")
        color_layout = QHBoxLayout()
        
        self.color_label = QLabel()
        self.color_label.setFixedSize(60, 30)
        self.color_label.setStyleSheet(f"background-color: {self.selected_color}; border: 1px solid white;")
        self.color_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_label.mousePressEvent = lambda e: self.choose_color()
        color_layout.addWidget(self.color_label)
        
        self.color_btn = QPushButton("Choose Color")
        self.color_btn.clicked.connect(self.choose_color)
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        
        color_group.setLayout(color_layout)
        layout.addWidget(color_group)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.on_indicator_changed(self.type_combo.currentText())
    
    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.selected_color), self, "Select Indicator Color")
        if color.isValid():
            self.selected_color = color.name()
            self.color_label.setStyleSheet(f"background-color: {self.selected_color}; border: 1px solid white;")
    
    def on_indicator_changed(self, indicator_name):
        if indicator_name.startswith("--"):
            self.params_group.setVisible(False)
            return
        
        self.current_indicator = indicator_name
        
        for i in reversed(range(self.params_layout.count())):
            widget = self.params_layout.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        self.param_widgets.clear()
        
        all_indicators = IndicatorManager.ALL_INDICATORS
        if indicator_name not in all_indicators:
            return
        
        params = all_indicators[indicator_name]['params']
        self.params_group.setVisible(True)
        
        default_colors = {
            'SMA': '#00BFFF',
            'EMA': '#FFD700',
            'BBANDS': '#FF6B6B',
            'SAR': '#00CED1',
            'MACD': '#4169E1',
            'RSI': '#9370DB',
            'CCI': '#FFD700',
            'ADX': '#DA70D6',
            'ATR': '#00CED1',
            'MOM': '#FF8C00',
            'ROC': '#FFD700',
            'STOCH': '#4169E1',
            'STOCHRSI': '#4169E1',
            'WILLR': '#FFD700',
            'OBV': '#00CED1',
            'MFI': '#9370DB'
        }
        
        self.selected_color = default_colors.get(indicator_name, '#00BFFF')
        self.color_label.setStyleSheet(f"background-color: {self.selected_color}; border: 1px solid white;")
        
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
        return self.selected_color


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
        # Use the base indicator name for the combo
        indicator_name = ind.get('indicator_name', ind.get('name', 'Unknown'))
        dialog.type_combo.setCurrentText(indicator_name)
        dialog.on_indicator_changed(indicator_name)
        
        if ind.get('color'):
            dialog.selected_color = ind['color']
            dialog.color_label.setStyleSheet(f"background-color: {ind['color']}; border: 1px solid white;")
        
        for param_name, value in ind.get('params', {}).items():
            if param_name in dialog.param_widgets:
                dialog.param_widgets[param_name].setValue(value)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Preserve all fields from original indicator
            self.indicators[current_row] = {
                'name': ind.get('name', dialog.get_indicator_name()),
                'indicator_name': dialog.get_indicator_name(),
                'type': IndicatorManager.ALL_INDICATORS.get(dialog.get_indicator_name(), {}).get('type', 'overlay'),
                'params': dialog.get_indicator_params(),
                'color': dialog.get_indicator_color(),
                'visible': ind.get('visible', True)  # Preserve visibility state
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
            color_box = f" [{ind.get('color', '#FFFFFF')}]"
            display_name = ind.get('name', ind.get('indicator_name', 'Unknown'))
            self.indicator_list.addItem(f"{visible_icon} {display_name}{color_box} - {ind.get('params', {})}")
    
    def accept_changes(self):
        self.result_data = self.indicators
        self.accept()
    
    def get_indicators(self):
        return self.result_data