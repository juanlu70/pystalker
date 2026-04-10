"""
PyStalker - Chart View using PyQtGraph for high performance
"""
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QWheelEvent, QMouseEvent, QKeyEvent
import pyqtgraph as pg
import pandas as pd

from ..core.indicators import PlotLine


class TrendLineItem(pg.GraphicsObject):
    def __init__(self, points, x_min=0, x_max=1000, color='#FFD700', width=2):
        pg.GraphicsObject.__init__(self)
        self.points = points
        self.x_min = x_min
        self.x_max = x_max
        self.color = color
        self.width = width
        self.generatePicture()
    
    def setXRange(self, x_min, x_max):
        self.x_min = x_min
        self.x_max = x_max
        self.generatePicture()
        self.update()
    
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        p.setPen(pg.mkPen(self.color, width=self.width))
        
        if len(self.points) >= 2:
            x1, y1 = self.points[0]
            x2, y2 = self.points[1]
            
            if x2 != x1:
                slope = (y2 - y1) / (x2 - x1)
                y_at_xmin = y1 + slope * (self.x_min - x1)
                y_at_xmax = y1 + slope * (self.x_max - x1)
                
                p.drawLine(pg.QtCore.QPointF(self.x_min, y_at_xmin),
                          pg.QtCore.QPointF(self.x_max, y_at_xmax))
        
        p.end()
    
    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)
    
    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


class ChartView(QWidget):
    indicator_added = pyqtSignal(str)
    range_changed = pyqtSignal(float, float, object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.df = None
        self.symbol = None
        self.overlay_lines = []
        self.indicator_curves = []
        self.trend_lines = []
        self.drawing_trendline = False
        self.trendline_points = []
        self.snap_mode = None
        self.preview_line = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', 'w')
        pg.setConfigOption('useOpenGL', True)
        pg.setConfigOption('enableExperimental', True)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#1e1e1e')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', 'Price', color='w')
        self.plot_widget.setLabel('bottom', 'Time', color='w')
        
        self.view_box = self.plot_widget.plotItem.vb
        
        self.view_box.sigXRangeChanged.connect(self.update_date_ticks)
        self.view_box.sigYRangeChanged.connect(self.update_info_position)
        
        layout.addWidget(self.plot_widget)
        
        self.info_text = pg.TextItem("", color='#FFFF00', anchor=(0, 0))
        self.info_text.setFont(pg.QtGui.QFont('monospace', 10))
        self.plot_widget.addItem(self.info_text, ignoreBounds=True)
        
        plot_widget_proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved, 
                                           rateLimit=60, slot=self.mouse_moved)
        
        self.candlestick_item = None
        self.volume_item = None
        self.visible_bars = 200
        self.scroll_speed = 50
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
    
    def start_trendline_drawing(self):
        self.drawing_trendline = True
        self.trendline_points = []
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.info_text.setText("Trendline: Click first point (Press ESC to cancel)")
        self.update_info_position()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_T:
            self.start_trendline_drawing()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancel_trendline()
        elif event.key() == Qt.Key.Key_O:
            self.snap_mode = 'open'
            self.info_text.setText("Snap mode: Open")
        elif event.key() == Qt.Key.Key_H:
            self.snap_mode = 'high'
            self.info_text.setText("Snap mode: High")
        elif event.key() == Qt.Key.Key_L:
            self.snap_mode = 'low'
            self.info_text.setText("Snap mode: Low")
        elif event.key() == Qt.Key.Key_C:
            self.snap_mode = 'close'
            self.info_text.setText("Snap mode: Close")
        elif event.key() == Qt.Key.Key_N:
            self.snap_mode = None
            self.info_text.setText("Snap mode: None")
        else:
            super().keyPressEvent(event)
    
    def cancel_trendline(self):
        self.drawing_trendline = False
        self.trendline_points = []
        if self.preview_line is not None:
            self.plot_widget.removeItem(self.preview_line)
            self.preview_line = None
        self.plot_widget.setMouseEnabled(x=True, y=False)
        self.info_text.setText("")
    
    def mousePressEvent(self, event: QMouseEvent):
        if self.drawing_trendline and event.button() == Qt.MouseButton.LeftButton:
            self.handle_trendline_click(event)
            event.accept()
            return
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self.drawing_trendline and len(self.trendline_points) == 1:
            self.handle_trendline_move(event)
        super().mouseMoveEvent(event)
    
    def handle_trendline_click(self, event):
        pos = self.plot_widget.plotItem.vb.mapSceneToView(event.pos())
        x = pos.x()
        y = pos.y()
        
        x_idx = int(round(x))
        if self.df is not None and 0 <= x_idx < len(self.df):
            if self.snap_mode == 'open':
                y = float(self.df['Open'].iloc[x_idx])
            elif self.snap_mode == 'high':
                y = float(self.df['High'].iloc[x_idx])
            elif self.snap_mode == 'low':
                y = float(self.df['Low'].iloc[x_idx])
            elif self.snap_mode == 'close':
                y = float(self.df['Close'].iloc[x_idx])
        
        self.trendline_points.append((x_idx, y))
        
        if len(self.trendline_points) == 1:
            self.info_text.setText(f"Trendline: First point at bar {x_idx}. Click second point.")
            self.update_info_position()
        elif len(self.trendline_points) == 2:
            if self.preview_line is not None:
                self.plot_widget.removeItem(self.preview_line)
                self.preview_line = None
            
            if self.trend_lines:
                color = ['#FFD700', '#00CED1', '#FF69B4', '#00FF7F', '#FF6347'][len(self.trend_lines) % 5]
            else:
                color = '#FFD700'
            
            x_min = -10
            x_max = len(self.df) + 10 if self.df is not None else 1000
            
            trendline = TrendLineItem(self.trendline_points.copy(), x_min, x_max, color, 2)
            self.plot_widget.addItem(trendline)
            self.trend_lines.append({
                'item': trendline,
                'points': self.trendline_points.copy(),
                'color': color
            })
            self.trendline_points = []
            self.drawing_trendline = False
            self.plot_widget.setMouseEnabled(x=True, y=False)
            self.info_text.setText("Trendline drawn. Press T to draw another.")
            self.update_info_position()
    
    def handle_trendline_move(self, event):
        pos = self.plot_widget.plotItem.vb.mapSceneToView(event.pos())
        x = pos.x()
        y = pos.y()
        
        x_idx = int(round(x))
        if self.df is not None and 0 <= x_idx < len(self.df):
            if self.snap_mode == 'open':
                y = float(self.df['Open'].iloc[x_idx])
            elif self.snap_mode == 'high':
                y = float(self.df['High'].iloc[x_idx])
            elif self.snap_mode == 'low':
                y = float(self.df['Low'].iloc[x_idx])
            elif self.snap_mode == 'close':
                y = float(self.df['Close'].iloc[x_idx])
        
        if self.preview_line is not None:
            self.plot_widget.removeItem(self.preview_line)
            self.preview_line = None
        
        x_min = -10
        x_max = len(self.df) + 10 if self.df is not None else 1000
        self.preview_line = TrendLineItem([self.trendline_points[0], (x_idx, y)], x_min, x_max, '#FFFFFF', 1)
        self.plot_widget.addItem(self.preview_line)
    
    def mouse_moved(self, evt):
        pos = evt[0]
        if self.plot_widget.sceneBoundingRect().contains(pos):
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
            x = mouse_point.x()
            
            if self.df is not None and len(self.df) > 0:
                x_idx = int(round(x))
                if 0 <= x_idx < len(self.df):
                    row = self.df.iloc[x_idx]
                    
                    info_parts = []
                    info_parts.append(f"Bar: {x_idx}")
                    info_parts.append(f"O: {row['Open']:.2f}")
                    info_parts.append(f"H: {row['High']:.2f}")
                    info_parts.append(f"L: {row['Low']:.2f}")
                    info_parts.append(f"C: {row['Close']:.2f}")
                    
                    if hasattr(self.df.index[x_idx], 'strftime'):
                        info_parts.append(f"D: {self.df.index[x_idx].strftime('%Y-%m-%d')}")
                    
                    for line in self.overlay_lines:
                        if len(line.data) > x_idx:
                            val = line.data[x_idx]
                            if not np.isnan(val):
                                info_parts.append(f"{line.name}: {val:.2f}")
                    
                    self.info_text.setText("  ".join(info_parts))
                    self.update_info_position()
    
    def wheelEvent(self, event: QWheelEvent):
        if self.df is None or len(self.df) == 0:
            return
        
        delta = event.angleDelta().y()
        
        current_range = self.view_box.viewRange()
        x_range = current_range[0]
        
        shift = self.scroll_speed if delta < 0 else -self.scroll_speed
        
        new_left = x_range[0] + shift
        new_right = x_range[1] + shift
        
        if new_left < -5:
            new_left = -5
            new_right = new_left + (x_range[1] - x_range[0])
        
        if new_right > len(self.df) + 5:
            new_right = len(self.df) + 5
            new_left = new_right - (x_range[1] - x_range[0])
        
        self.plot_widget.setXRange(new_left, new_right)
        event.accept()
    
    def zoom_in(self):
        current_range = self.view_box.viewRange()
        x_range = current_range[0]
        current_width = x_range[1] - x_range[0]
        new_width = current_width * 0.8
        center = (x_range[0] + x_range[1]) / 2
        self.plot_widget.setXRange(center - new_width/2, center + new_width/2)
    
    def zoom_out(self):
        current_range = self.view_box.viewRange()
        x_range = current_range[0]
        current_width = x_range[1] - x_range[0]
        new_width = current_width * 1.25
        center = (x_range[0] + x_range[1]) / 2
        self.plot_widget.setXRange(center - new_width/2, center + new_width/2)
    
    def reset_zoom(self):
        if self.df is not None and len(self.df) > 0:
            start_idx = max(0, len(self.df) - self.visible_bars)
            self.plot_widget.setXRange(start_idx, len(self.df))
            self.plot_widget.autoRange()
    
    def plot_candlesticks(self, df: pd.DataFrame, symbol: str):
        self.df = df
        self.symbol = symbol
        
        self.plot_widget.clear()
        self.candlestick_item = None
        self.volume_item = None
        self.indicator_curves.clear()
        
        if df is None or df.empty:
            return
        
        self.plot_widget.setTitle(symbol, color='w', size='14pt')
        
        candle_data = []
        for i in range(len(df)):
            candle_data.append((
                i,
                float(df['Open'].iloc[i]),
                float(df['High'].iloc[i]),
                float(df['Low'].iloc[i]),
                float(df['Close'].iloc[i])
            ))
        
        candle_data_to_use = candle_data
        self.candlestick_item = CandlestickItem(candle_data_to_use)
        self.plot_widget.addItem(self.candlestick_item)
        
        if 'Volume' in df.columns:
            volume_data = []
            for i in range(len(df)):
                close = float(df['Close'].iloc[i])
                open_val = float(df['Open'].iloc[i])
                vol = float(df['Volume'].iloc[i])
                color = '#26a69a' if close >= open_val else '#ef5350'
                volume_data.append((i, vol, color))
            
            self.volume_item = VolumeItem(volume_data)
            self.plot_widget.addItem(self.volume_item)
        
        for plot_line in self.overlay_lines:
            if len(plot_line.data) == len(df):
                valid_mask = ~np.isnan(plot_line.data)
                valid_indices = np.where(valid_mask)[0]
                valid_data = plot_line.data[valid_mask]
                
                if len(valid_indices) > 0:
                    curve = pg.PlotDataItem(valid_indices, valid_data,
                                           pen=pg.mkPen(color=plot_line.color, width=plot_line.width + 1),
                                           name=plot_line.name)
                    self.plot_widget.addItem(curve)
                    self.indicator_curves.append(curve)
        
        if len(self.overlay_lines) > 0:
            self.plot_widget.addLegend()
        
        start_idx = max(0, len(df) - self.visible_bars)
        self.plot_widget.setXRange(start_idx, len(df))
        self.update_date_ticks()
        self.update_info_position()
        
        self.adjust_volume_height()
        
        for tl in self.trend_lines:
            if 'item' in tl:
                self.plot_widget.addItem(tl['item'])
    
    def adjust_volume_height(self):
        if self.df is None or len(self.df) == 0 or 'Volume' not in self.df.columns:
            return
        
        if self.volume_item is None:
            return
        
        view_range = self.view_box.viewRange()
        x_min, x_max = int(max(0, view_range[0][0])), int(min(len(self.df) - 1, view_range[0][1]))
        
        if x_min >= x_max:
            return
        
        visible_df = self.df.iloc[x_min:x_max+1]
        if visible_df.empty:
            return
        
        max_volume = float(visible_df['Volume'].max())
        min_price = float(visible_df['Low'].min())
        max_price = float(visible_df['High'].max())
        
        price_range = max_price - min_price
        volume_scale = price_range * 0.2 / max_volume if max_volume > 0 else 0
        
        self.volume_item.setScale(volume_scale)
        
        min_visible_price = min_price - price_range * 0.05
        max_visible_price = max_price + price_range * 0.05
        self.plot_widget.setYRange(min_visible_price, max_visible_price)
    
    def update_date_ticks(self):
        if self.df is None or len(self.df) == 0:
            return
        
        view_range = self.view_box.viewRange()
        left = max(0, int(view_range[0][0]))
        right = min(len(self.df) - 1, int(view_range[0][1]))
        
        num_ticks = 10
        
        if right - left < num_ticks:
            num_ticks = max(1, right - left)
        
        step = max(1, (right - left) // num_ticks)
        
        ticks = []
        for i in range(left, right + 1, step):
            if i < len(self.df.index):
                idx = self.df.index[i]
                if hasattr(idx, 'strftime'):
                    ticks.append((i, idx.strftime('%Y-%m-%d')))
                else:
                    ticks.append((i, str(idx)[:10]))
        
        if ticks:
            ax = self.plot_widget.getAxis('bottom')
            ax.setTicks([ticks])
        
        self.range_changed.emit(left, right, ticks)
        self.update_info_position()
    
    def update_info_position(self):
        if self.df is not None and len(self.df) > 0:
            view_range = self.view_box.viewRange()
            x_min, x_max = view_range[0]
            y_min, y_max = view_range[1]
            padding = (y_max - y_min) * 0.02
            self.info_text.setPos(x_min + 2, y_max - padding)
    
    def add_indicator_line(self, plot_line: PlotLine):
        self.overlay_lines.append(plot_line)
        if self.df is not None:
            self.plot_candlesticks(self.df, self.symbol)
    
    def clear_indicators(self):
        self.overlay_lines.clear()
        if self.df is not None:
            self.plot_candlesticks(self.df, self.symbol)
    
    def update_view_range(self, left, right):
        self.view_box.sigXRangeChanged.disconnect(self.update_date_ticks)
        self.plot_widget.setXRange(left, right)
        self.view_box.sigXRangeChanged.connect(self.update_date_ticks)
        self.update_date_ticks()
        self.adjust_volume_height()
    
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


class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.picture = None
        self.generatePicture()
    
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        
        body_width = 0.7
        
        for i, (t, open_val, high, low, close) in enumerate(self.data):
            if close >= open_val:
                pen = pg.mkPen('#26a69a', width=1)
                brush = pg.mkBrush('#26a69a')
            else:
                pen = pg.mkPen('#ef5350', width=1)
                brush = pg.mkBrush('#ef5350')
            
            p.setPen(pen)
            p.setBrush(brush)
            
            p.drawLine(pg.QtCore.QPointF(t, low), pg.QtCore.QPointF(t, high))
            
            body_height = abs(close - open_val) if close != open_val else 0.001
            body_top = min(open_val, close)
            p.drawRect(pg.QtCore.QRectF(t - body_width/2, body_top, body_width, body_height))
        
        p.end()
    
    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)
    
    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


class VolumeItem(pg.GraphicsObject):
    def __init__(self, data):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.scale = 1.0
        self.picture = None
        self.generatePicture()
    
    def setScale(self, scale):
        self.scale = scale
        self.generatePicture()
        self.update()
    
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        
        bar_width = 0.7
        
        for i, (t, vol, color) in enumerate(self.data):
            pen = pg.mkPen(color, width=1)
            brush = pg.mkBrush(color)
            
            p.setPen(pen)
            p.setBrush(brush)
            
            bar_height = vol * self.scale
            y_offset = 0
            p.drawRect(pg.QtCore.QRectF(t - bar_width/2, y_offset, bar_width, bar_height))
        
        p.end()
    
    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)
    
    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())