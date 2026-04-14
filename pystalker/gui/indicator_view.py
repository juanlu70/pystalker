"""
PyStalker - Indicator View using PyQtGraph for separate indicator panels
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt
import pyqtgraph as pg
import pandas as pd
import numpy as np

from ..core.indicators import Indicator
from .shared import PriceAxisItem


class IndicatorPanel(QWidget):
    range_changed = pyqtSignal(float, float, object)
    
    def __init__(self, indicator: Indicator, data: pd.DataFrame, parent=None):
        super().__init__(parent)
        self.indicator = indicator
        self.data = data
        self.curves = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', 'w')
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#1e1e1e')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.showAxis('right')
        self.plot_widget.hideAxis('left')
        self.plot_widget.setTitle(None)
        
        self.title_text = pg.TextItem(indicator.name, color='w', anchor=(0, 0))
        self.title_text.setFont(pg.QtGui.QFont('sans-serif', 10))
        self.plot_widget.addItem(self.title_text, ignoreBounds=True)
        
        self.view_box = self.plot_widget.plotItem.vb
        self.view_box.sigXRangeChanged.connect(self.on_range_changed)
        self.view_box.sigYRangeChanged.connect(self.update_info_position)
        
        layout.addWidget(self.plot_widget)
        
        self.info_text = pg.TextItem("", color='#FFFF00', anchor=(1, 0))
        self.info_text.setFont(pg.QtGui.QFont('monospace', 9))
        self.plot_widget.addItem(self.info_text, ignoreBounds=True)
        
        self.plot_indicator()
        
        self._mouse_proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved,
                                           rateLimit=60, slot=self.mouse_moved)
    
    def plot_indicator(self):
        self.plot_widget.clear()
        self.curves.clear()
        
        left_axis = self.plot_widget.getAxis('left')
        left_axis.setStyle(showValues=False)
        
        price_axis = PriceAxisItem(orientation='right')
        price_axis.setStyle(showValues=True)
        price_axis.setZValue(1000)
        self.plot_widget.setAxisItems({'right': price_axis})
        
        self.plot_widget.addItem(self.title_text, ignoreBounds=True)
        self.plot_widget.addItem(self.info_text, ignoreBounds=True)
        self.update_info_position()
        
        self._mouse_proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved,
                                           rateLimit=60, slot=self.mouse_moved)
        
        for hl in self.indicator.hlines:
            level = hl.get('level', 0)
            color = hl.get('color', '#FF6B6B')
            line = pg.InfiniteLine(pos=level, angle=0, pen=pg.mkPen(color=color, width=1, style=Qt.PenStyle.DashLine))
            self.plot_widget.addItem(line)
        
        for line in self.indicator.lines:
            if len(line.data) == len(self.data):
                valid_mask = ~np.isnan(line.data)
                valid_indices = np.where(valid_mask)[0]
                valid_data = line.data[valid_mask]
                
                if len(valid_indices) > 0:
                    curve = self.plot_widget.plot(valid_indices, valid_data,
                                                  pen=pg.mkPen(color=line.color, width=line.width),
                                                  name=line.name)
                    self.curves.append((curve, line.name, line.data))
    
    def mouse_moved(self, evt):
        pos = evt[0]
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
            x = mouse_point.x()
            
            if self.data is not None and len(self.data) > 0:
                x_idx = int(round(x))
                if 0 <= x_idx < len(self.data):
                    info_parts = []
                    for curve, name, data in self.curves:
                        if len(data) > x_idx:
                            val = data[x_idx]
                            if not np.isnan(val):
                                info_parts.append(f"{name}: {val:.2f}")
                    self.info_text.setText("  ".join(info_parts))
                    self.update_info_position()
    
    def update_info_position(self):
        view_range = self.view_box.viewRange()
        x_min, x_max = view_range[0]
        y_min, y_max = view_range[1]
        padding = (y_max - y_min) * 0.05
        padding_x = (x_max - x_min) * 0.02
        self.info_text.setPos(x_max - padding_x, y_max - padding)
        self.title_text.setPos(x_min + 2, y_max - (y_max - y_min) * 0.02)
    
    def on_range_changed(self, view_box):
        view_range = self.view_box.viewRange()
        left = view_range[0][0]
        right = view_range[0][1]
        self.range_changed.emit(left, right, None)
    
    def update_view(self, left, right):
        self.view_box.sigXRangeChanged.disconnect(self.on_range_changed)
        self.plot_widget.setXRange(left, right)
        self.view_box.sigXRangeChanged.connect(self.on_range_changed)
    
    def update_ticks(self, ticks):
        if ticks:
            ax = self.plot_widget.getAxis('bottom')
            ax.setTicks([ticks])
    
    def get_view_state(self):
        view_range = self.view_box.viewRange()
        return {
            'x_range': (view_range[0][0], view_range[0][1]),
            'y_range': (view_range[1][0], view_range[1][1])
        }
    
    def set_view_state(self, state):
        if state:
            x_range = state.get('x_range')
            y_range = state.get('y_range')
            if x_range:
                self.plot_widget.setXRange(x_range[0], x_range[1])
            if y_range:
                self.plot_widget.setYRange(y_range[0], y_range[1])


class IndicatorView(QWidget):
    indicator_added = pyqtSignal(str)
    indicator_removed = pyqtSignal(str)
    range_changed = pyqtSignal(float, float, object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.panels = {}
        self._updating = False
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
    
    def add_indicator_panel(self, indicator: Indicator, data: pd.DataFrame):
        if indicator.name in self.panels:
            return
        
        panel = IndicatorPanel(indicator, data)
        panel.range_changed.connect(self.on_panel_range_changed)
        self.panels[indicator.name] = panel
        self.layout().addWidget(panel)
        
        self.indicator_added.emit(indicator.name)
    
    def on_panel_range_changed(self, left, right, ticks):
        if self._updating:
            return
        self.range_changed.emit(left, right, ticks)
    
    def remove_indicator_panel(self, name: str):
        if name in self.panels:
            panel = self.panels[name]
            self.layout().removeWidget(panel)
            panel.deleteLater()
            del self.panels[name]
            
            self.indicator_removed.emit(name)
    
    def clear_all(self):
        for name in list(self.panels.keys()):
            self.remove_indicator_panel(name)
    
    def update_views(self, left, right):
        self._updating = True
        for panel in self.panels.values():
            panel.update_view(left, right)
        self._updating = False
    
    def update_ticks(self, ticks):
        for panel in self.panels.values():
            panel.update_ticks(ticks)
    
    def get_panels_state(self):
        state = {}
        for name, panel in self.panels.items():
            state[name] = panel.get_view_state()
        return state
    
    def set_panels_state(self, state):
        for name, panel_state in state.items():
            if name in self.panels:
                self.panels[name].set_view_state(panel_state)