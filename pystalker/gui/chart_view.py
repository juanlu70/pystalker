"""
PyStalker - Chart View using PyQtGraph for high performance
"""
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QWheelEvent, QMouseEvent, QKeyEvent
import pyqtgraph as pg
import pandas as pd
import numpy as np

from ..core.indicators import PlotLine


class OverlayLine:
    def __init__(self, plot_line, visible=True, unique_name=None):
        self.plot_line = plot_line
        self.visible = visible
        self.unique_name = unique_name or plot_line.name


class IndicatorLegendItem(QWidget):
    clicked = pyqtSignal()
    
    def __init__(self, name, visible=True, color='#FFFFFF', parent=None):
        super().__init__(parent)
        self.name = name
        self.visible = visible
        self.color = color
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(5)
        
        self.visible_btn = QPushButton("👁" if visible else "🚫")
        self.visible_btn.setFixedSize(30, 25)
        self.visible_btn.clicked.connect(self.toggle_visibility)
        layout.addWidget(self.visible_btn)
        
        self.color_label = QLabel()
        self.color_label.setFixedSize(20, 20)
        self.color_label.setStyleSheet(f"background-color: {color}; border: 1px solid white;")
        layout.addWidget(self.color_label)
        
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("color: white;")
        layout.addWidget(self.name_label)
        
        layout.addStretch()
        
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def toggle_visibility(self):
        self.visible = not self.visible
        self.visible_btn.setText("👁" if self.visible else "🚫")
        self.clicked.emit()
    
    def set_visible_state(self, visible):
        self.visible = visible
        self.visible_btn.setText("👁" if visible else "🚫")
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_visibility()


class PriceAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f'{v:.2f}' for v in values]


class TrendLineItem(pg.GraphicsObject):
    def __init__(self, points, x_min=0, x_max=1000, color='#FFD700', width=2):
        pg.GraphicsObject.__init__(self)
        self.points = list(points)
        self.x_min = x_min
        self.x_max = x_max
        self.color = color
        self.width = width
        self.show_endpoints = False
        self.generatePicture()
    
    def setXRange(self, x_min, x_max):
        self.x_min = x_min
        self.x_max = x_max
        self.generatePicture()
        self.update()
    
    def update_point(self, index, x, y):
        if 0 <= index < len(self.points):
            self.points[index] = (x, y)
            self.generatePicture()
            self.update()
    
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        pen = pg.mkPen(self.color, width=self.width)
        p.setPen(pen)
        
        if len(self.points) >= 2:
            x1, y1 = self.points[0]
            x2, y2 = self.points[1]
            
            if x2 != x1:
                slope = (y2 - y1) / (x2 - x1)
            else:
                slope = 0
            
            y_at_xmax = y1 + slope * (self.x_max - x1) if x2 != x1 else y1
            
            p.drawLine(pg.QtCore.QPointF(x1, y1),
                       pg.QtCore.QPointF(self.x_max, y_at_xmax))
        
        p.end()
    
    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)
        if not self.show_endpoints:
            return
        p.setPen(pg.mkPen(self.color, width=2))
        p.setBrush(pg.QtGui.QBrush(pg.QtGui.QColor(self.color), Qt.BrushStyle.SolidPattern))
        if hasattr(self, 'parentItem') and self.parentItem():
            vb = self.parentItem().getViewBox()
        else:
            vb = None
            try:
                vb = self.getViewBox()
            except Exception:
                pass
        if vb:
            pixel_size = vb.viewPixelSize()
            rx = 6 * pixel_size[0]
            ry = 6 * pixel_size[1]
        else:
            rx = ry = 0.3
        for x, y in self.points:
            p.drawEllipse(pg.QtCore.QPointF(x, y), rx, ry)
    
    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())


class ChartView(QWidget):
    indicator_added = pyqtSignal(str)
    indicator_visibility_changed = pyqtSignal(str, bool)
    range_changed = pyqtSignal(float, float, object)
    colors_changed = pyqtSignal()
    drawModeToggled = pyqtSignal(bool)
    drawingDoubleClicked = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.df = None
        self.symbol = None
        self.overlay_lines = []
        self.indicator_curves = []
        self.drawings = []
        self.drawing_trendline = False
        self.trendline_points = []
        self.snap_mode = None
        self.preview_line = None
        self._dragging_drawing = None
        self._dragging_point_idx = None
        self.bull_color = '#26a69a'
        self.bear_color = '#ef5350'
        self._ignore_context_menu = False
        self._draw_mode = False
        self._show_endpoints = False
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', 'w')
        pg.setConfigOption('useOpenGL', True)
        pg.setConfigOption('enableExperimental', True)
        
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('#1e1e1e')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        
        left_axis = self.plot_widget.getAxis('left')
        left_axis.setStyle(showValues=False)
        
        price_axis = PriceAxisItem(orientation='right')
        price_axis.setStyle(showValues=True)
        price_axis.setZValue(1000)
        self.plot_widget.setAxisItems({'right': price_axis})
        
        self.view_box = self.plot_widget.plotItem.vb
        
        self.plot_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.plot_widget.customContextMenuRequested.connect(self.show_context_menu)
        
        self.view_box.sigXRangeChanged.connect(self.update_date_ticks)
        self.view_box.sigYRangeChanged.connect(self.update_info_position)
        self.view_box.sigXRangeChanged.connect(self.adjust_volume_height)
        self.view_box.sigYRangeChanged.connect(self.adjust_volume_height)
        self.view_box.sigXRangeChanged.connect(self.update_ohlc_legend_position)
        
        self.volume_view_box = pg.ViewBox()
        self.volume_view_box.setYRange(0, 1, padding=0)
        self.plot_widget.scene().addItem(self.volume_view_box)
        self.plot_widget.plotItem.vb.setXLink(self.volume_view_box)
        
        layout.addWidget(self.plot_widget)
        
        self.info_text = pg.TextItem("", color='#FFFF00', anchor=(0, 0))
        self.info_text.setFont(pg.QtGui.QFont('monospace', 10))
        self.plot_widget.addItem(self.info_text, ignoreBounds=True)
        
        plot_widget_proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved, 
                                           rateLimit=60, slot=self.mouse_moved)
        self._mouse_proxy = plot_widget_proxy
        
        self.candlestick_item = None
        self.volume_item = None
        self.visible_bars = 450
        self.scroll_speed = 50
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
    
    def start_trendline_drawing(self):
        if not self._draw_mode:
            return
        self.drawing_trendline = True
        self.trendline_points = []
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.info_text.setText("Trendline: Click first point (Press ESC to cancel)")
        self.update_info_position()
    
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_T:
            if self._draw_mode:
                self.drawing_trendline = True
                self.trendline_points = []
                self.info_text.setText("Drawing trendline - Click to set start point")
                self.update_info_position()
            else:
                self.start_trendline_drawing()
        elif event.key() == Qt.Key.Key_Escape:
            if self._draw_mode:
                if self.drawing_trendline:
                    self.cancel_trendline()
                else:
                    self._draw_mode = False
                    self.draw_mode = False
                    self.drawModeToggled.emit(False)
            else:
                self.cancel_trendline()
        elif event.key() == Qt.Key.Key_Y:
            self.show_last_year()
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
    
    def show_context_menu(self, pos):
        # Prevent context menu from showing multiple times
        if self._ignore_context_menu:
            return
        
        from PyQt6.QtWidgets import QMenu, QColorDialog
        
        menu = QMenu(self)
        
        change_bull_color = menu.addAction("Change Bull Color")
        change_bear_color = menu.addAction("Change Bear Color")
        
        action = menu.exec(self.plot_widget.mapToGlobal(pos))
        
        if action == change_bull_color:
            menu.close()
            self._ignore_context_menu = True
            color = QColorDialog.getColor(pg.QtGui.QColor(self.bull_color), self, "Select Bull Color")
            if color.isValid():
                self.bull_color = color.name()
                self.plot_candlesticks(self.df, self.symbol)
                self.colors_changed.emit()
            # Reset flag after a short delay to prevent re-triggering
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, lambda: setattr(self, '_ignore_context_menu', False))
        elif action == change_bear_color:
            menu.close()
            self._ignore_context_menu = True
            color = QColorDialog.getColor(pg.QtGui.QColor(self.bear_color), self, "Select Bear Color")
            if color.isValid():
                self.bear_color = color.name()
                self.plot_candlesticks(self.df, self.symbol)
                self.colors_changed.emit()
            # Reset flag after a short delay to prevent re-triggering
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, lambda: setattr(self, '_ignore_context_menu', False))
        elif action == change_bear_color:
            menu.close()  # Close menu before opening dialog
            color = QColorDialog.getColor(pg.QtGui.QColor(self.bear_color), self, "Select Bear Color")
            if color.isValid():
                self.bear_color = color.name()
                self.plot_candlesticks(self.df, self.symbol)
                self.colors_changed.emit()
    
    def set_colors(self, bull_color: str, bear_color: str):
        self.bull_color = bull_color
        self.bear_color = bear_color
    
    def snap_drawing_points(self, drawing):
        if self.df is None or self.df.empty:
            return
        snap = drawing.get('snap', '')
        if not snap:
            snap = self.snap_mode
        column_map = {'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}
        col = column_map.get(snap)
        if not col:
            return
        new_points = []
        for px, py in drawing['points']:
            x_idx = int(round(px))
            if 0 <= x_idx < len(self.df):
                y = float(self.df[col].iloc[x_idx])
                new_points.append((x_idx, y))
            else:
                new_points.append((px, py))
        drawing['points'] = new_points
        drawing['item'].points = new_points
        drawing['item'].generatePicture()
        drawing['item'].update()
    
    @property
    def draw_mode(self):
        return self._draw_mode
    
    @draw_mode.setter
    def draw_mode(self, enabled):
        self._draw_mode = enabled
        self._show_endpoints = enabled
        if enabled:
            self.plot_widget.setMouseEnabled(x=False, y=False)
            self.info_text.setText("DRAW MODE - Left click: start/end trendline | ESC: exit")
            self.update_info_position()
        else:
            self.releaseMouse()
            self.plot_widget.setMouseEnabled(x=True, y=True)
            self.drawing_trendline = False
            self.trendline_points = []
            if self.preview_line is not None:
                self.plot_widget.removeItem(self.preview_line)
                self.preview_line = None
            self._dragging_drawing = None
            self._dragging_point_idx = None
            self.info_text.setText("")
        for drawing in self.drawings:
            if 'item' in drawing:
                drawing['item'].show_endpoints = enabled
                drawing['item'].update()
    
    def cancel_trendline(self):
        self.drawing_trendline = False
        self.trendline_points = []
        if self.preview_line is not None:
            self.plot_widget.removeItem(self.preview_line)
            self.preview_line = None
        if self._draw_mode:
            self.info_text.setText("DRAW MODE - Left click: start/end trendline | ESC: exit")
            self.update_info_position()
        else:
            self.plot_widget.setMouseEnabled(x=True, y=True)
            self.info_text.setText("")
    
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._draw_mode:
                if self.drawing_trendline:
                    self.handle_trendline_click(event)
                    event.accept()
                    return
                hit = self._hit_test_drawing_endpoint(event)
                if hit:
                    self._dragging_drawing = hit[0]
                    self._dragging_point_idx = hit[1]
                    self.grabMouse()
                    event.accept()
                    return
                hit_line = self._hit_test_drawing_line(event)
                if hit_line:
                    self._dragging_drawing = hit_line
                    hit_endpoint = self._hit_test_drawing_endpoint(event)
                    if hit_endpoint:
                        self._dragging_drawing = hit_endpoint[0]
                        self._dragging_point_idx = hit_endpoint[1]
                    else:
                        self._dragging_point_idx = 0
                    self.grabMouse()
                    event.accept()
                    return
                self.draw_mode = False
                self.drawModeToggled.emit(False)
                event.accept()
                return
            elif self.drawing_trendline:
                self.handle_trendline_click(event)
                event.accept()
                return
            else:
                hit_endpoint = self._hit_test_drawing_endpoint(event)
                hit_line = self._hit_test_drawing_line(event)
                if hit_endpoint:
                    self.draw_mode = True
                    self.drawModeToggled.emit(True)
                    self._dragging_drawing = hit_endpoint[0]
                    self._dragging_point_idx = hit_endpoint[1]
                    self.grabMouse()
                    event.accept()
                    return
                elif hit_line:
                    self.draw_mode = True
                    self.drawModeToggled.emit(True)
                    event.accept()
                    return
        super().mousePressEvent(event)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_drawing is not None:
            self._dragging_drawing = None
            self._dragging_point_idx = None
            self.releaseMouse()
            event.accept()
            return
        super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            hit_endpoint = self._hit_test_drawing_endpoint(event)
            hit_line = self._hit_test_drawing_line(event)
            if hit_endpoint:
                self.drawingDoubleClicked.emit(hit_endpoint[0])
                event.accept()
                return
            elif hit_line:
                self.drawingDoubleClicked.emit(hit_line)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging_drawing is not None and self._draw_mode:
            self._handle_trendline_drag(event)
            return
        if self.drawing_trendline and len(self.trendline_points) == 1:
            self.handle_trendline_move(event)
        super().mouseMoveEvent(event)
    
    def _get_next_drawing_color(self):
        return '#FFFFFF'
    
    def _hit_test_drawing_endpoint(self, event):
        from PyQt6.QtCore import QPointF
        pos = self.plot_widget.plotItem.vb.mapSceneToView(QPointF(event.pos()))
        mx, my = pos.x(), pos.y()
        view_range = self.view_box.viewRange()
        x_range = view_range[0][1] - view_range[0][0]
        y_range = view_range[1][1] - view_range[1][0]
        view_w = self.view_box.size().width()
        view_h = self.view_box.size().height()
        hit_radius_x = (x_range / view_w) * 10 if view_w > 0 else 1
        hit_radius_y = (y_range / view_h) * 10 if view_h > 0 else 1
        
        for drawing in self.drawings:
            if 'item' not in drawing:
                continue
            for i, (px, py) in enumerate(drawing['points']):
                if abs(mx - px) < hit_radius_x and abs(my - py) < hit_radius_y:
                    return (drawing, i)
        return None
    
    def _hit_test_drawing_line(self, event):
        from PyQt6.QtCore import QPointF
        pos = self.plot_widget.plotItem.vb.mapSceneToView(QPointF(event.pos()))
        mx, my = pos.x(), pos.y()
        view_range = self.view_box.viewRange()
        y_range = view_range[1][1] - view_range[1][0]
        view_h = self.view_box.size().height()
        x_range = view_range[0][1] - view_range[0][0]
        view_w = self.view_box.size().width()
        threshold_y = (y_range / view_h) * 4 if view_h > 0 else 1
        threshold_x = (x_range / view_w) * 4 if view_w > 0 else 1
        
        for drawing in self.drawings:
            if 'item' not in drawing or len(drawing.get('points', [])) < 2:
                continue
            p1 = drawing['points'][0]
            p2 = drawing['points'][1]
            x1, y1 = p1
            x2, y2 = p2
            dx = x2 - x1
            dy = y2 - y1
            length_sq = dx * dx + dy * dy
            if length_sq == 0:
                continue
            t = ((mx - x1) * dx + (my - y1) * dy) / length_sq
            t = max(0, t)
            proj_y = y1 + t * dy
            dist_x = abs(mx - (x1 + t * dx))
            dist_y = abs(my - proj_y)
            if dist_y < threshold_y and dist_x < threshold_x * 3:
                return drawing
        return None
    
    def _handle_trendline_drag(self, event):
        from PyQt6.QtCore import QPointF
        pos = self.plot_widget.plotItem.vb.mapSceneToView(QPointF(event.pos()))
        x = pos.x()
        y = pos.y()
        x_idx = int(round(x))
        snap = self._dragging_drawing.get('snap', '') or self.snap_mode
        if self.df is not None and 0 <= x_idx < len(self.df):
            if snap == 'open':
                y = float(self.df['Open'].iloc[x_idx])
            elif snap == 'high':
                y = float(self.df['High'].iloc[x_idx])
            elif snap == 'low':
                y = float(self.df['Low'].iloc[x_idx])
            elif snap == 'close':
                y = float(self.df['Close'].iloc[x_idx])
        self._dragging_drawing['points'][self._dragging_point_idx] = (x_idx, y)
        self._dragging_drawing['item'].update_point(self._dragging_point_idx, x_idx, y)
        self.plot_widget.update()
    
    def handle_trendline_click(self, event):
        from PyQt6.QtCore import QPointF
        pos = self.plot_widget.plotItem.vb.mapSceneToView(QPointF(event.pos()))
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
            print(f"[DEBUG] Point 1 set: bar={x_idx}, y={y:.2f}", flush=True)
            if self._draw_mode:
                self.info_text.setText(f"[P1] bar={x_idx} y={y:.2f} | Click to set end point")
            else:
                self.info_text.setText(f"[P1] bar={x_idx} y={y:.2f} | Click second point.")
            self.update_info_position()
        elif len(self.trendline_points) == 2:
            p1 = self.trendline_points[0]
            print(f"[DEBUG] Point 2 set: bar={x_idx}, y={y:.2f} | Line from ({p1[0]},{p1[1]:.2f}) to ({x_idx},{y:.2f})", flush=True)
            if self.preview_line is not None:
                self.plot_widget.removeItem(self.preview_line)
                self.preview_line = None
            
            color = self._get_next_drawing_color()
            
            x_min = -10
            x_max = len(self.df) + 10 if self.df is not None else 1000
            
            trendline = TrendLineItem(self.trendline_points.copy(), x_min, x_max, color, 2)
            trendline.show_endpoints = self._draw_mode
            self.plot_widget.addItem(trendline)
            self.drawings.append({
                'type': 'trendline',
                'item': trendline,
                'points': self.trendline_points.copy(),
                'color': color,
                'snap': self.snap_mode or '',
                'params': {}
            })
            self.trendline_points = []
            self.drawing_trendline = False
            if self._draw_mode:
                self.info_text.setText("DRAW MODE - Left click: start/end trendline | ESC: exit")
            else:
                self.plot_widget.setMouseEnabled(x=True, y=True)
                self.info_text.setText("Trendline drawn. Press T to draw another.")
    
    def handle_trendline_move(self, event):
        from PyQt6.QtCore import QPointF
        pos = self.plot_widget.plotItem.vb.mapSceneToView(QPointF(event.pos()))
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
                    
                    bar_idx = x_idx
                    info_parts = []
                    dt_str = ""
                    idx = self.df.index[x_idx]
                    if hasattr(idx, 'strftime'):
                        try:
                            dt_str = idx.strftime('%Y-%m-%d %H:%M')
                        except Exception:
                            dt_str = str(idx)
                    info_parts.append(f"{dt_str}  O: {row['Open']:.2f}  H: {row['High']:.2f}  L: {row['Low']:.2f}  C: {row['Close']:.2f}")
                    for overlay_line in self.overlay_lines:
                        plot_line = overlay_line.plot_line
                        if len(plot_line.data) > x_idx:
                            val = plot_line.data[x_idx]
                            if not np.isnan(val):
                                info_parts.append(f"{plot_line.name}: {val:.2f}")
                    
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
    
    def show_last_year(self):
        if self.df is not None and len(self.df) > 0:
            freq = pd.infer_freq(self.df.index) if len(self.df) > 2 else None
            if freq and freq.startswith(('B', 'D')):
                bars_per_year = 252
            else:
                bars_per_year = 365
            start_idx = max(0, len(self.df) - bars_per_year)
            self.plot_widget.setXRange(start_idx, len(self.df))
    
    def plot_candlesticks(self, df: pd.DataFrame, symbol: str):
        self.df = df
        self.symbol = symbol
        
        self.plot_widget.clear()
        self.candlestick_item = None
        self.volume_item = None
        self.indicator_curves.clear()
        
        # Re-add axis and text items that were cleared
        price_axis = PriceAxisItem(orientation='right')
        price_axis.setStyle(showValues=True)
        price_axis.setZValue(1000)
        self.plot_widget.setAxisItems({'right': price_axis})
        self.view_box = self.plot_widget.plotItem.vb
        self.view_box.sigXRangeChanged.connect(self.update_date_ticks)
        self.view_box.sigYRangeChanged.connect(self.update_info_position)
        self.view_box.sigXRangeChanged.connect(self.adjust_volume_height)
        self.view_box.sigYRangeChanged.connect(self.adjust_volume_height)
        self.view_box.sigXRangeChanged.connect(self.update_ohlc_legend_position)
        self.plot_widget.addItem(self.info_text, ignoreBounds=True)
        self._mouse_proxy = pg.SignalProxy(self.plot_widget.scene().sigMouseMoved,
                                           rateLimit=60, slot=self.mouse_moved)
        
        if df is None or df.empty:
            self.info_text.setText("")
            return
        
        self.update_ohlc_legend()
        
        self.plot_widget.setTitle(symbol, color='w', size='14pt')
        
        if len(self.overlay_lines) > 0:
            self.plot_widget.addLegend(offset=(10, 30))
        
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
        self.candlestick_item = CandlestickItem(candle_data_to_use, self.bull_color, self.bear_color)
        self.plot_widget.addItem(self.candlestick_item)
        
        if 'Volume' in df.columns:
            volume_data = []
            for i in range(len(df)):
                close = float(df['Close'].iloc[i])
                open_val = float(df['Open'].iloc[i])
                vol = float(df['Volume'].iloc[i])
                color = self.bull_color if close >= open_val else self.bear_color
                volume_data.append((i, vol, color))
            
            self.volume_item = VolumeItem(volume_data)
            self.plot_widget.addItem(self.volume_item)
        
        for overlay_line in self.overlay_lines:
            plot_line = overlay_line.plot_line
            if len(plot_line.data) == len(df):
                valid_mask = ~np.isnan(plot_line.data)
                valid_indices = np.where(valid_mask)[0]
                valid_data = plot_line.data[valid_mask]
                
                if len(valid_indices) > 0:
                    curve = pg.PlotDataItem(valid_indices, valid_data,
                                           pen=pg.mkPen(color=plot_line.color, width=plot_line.width + 1),
                                           name=plot_line.name)
                    curve.setVisible(overlay_line.visible)
                    self.plot_widget.addItem(curve)
                    self.indicator_curves.append(curve)
        
        start_idx = max(0, len(df) - self.visible_bars)
        self.plot_widget.setXRange(start_idx, len(df))
        self.update_date_ticks()
        self.update_info_position()
        
        self.set_initial_y_range()
        
        self.adjust_volume_height()
        
        for drawing in self.drawings:
            if 'item' in drawing:
                self.plot_widget.addItem(drawing['item'])
    
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
            y_range = y_max - y_min
            view_height = self.view_box.size().height()
            if view_height > 0:
                pts_per_pixel = y_range / view_height
                font_size = self.info_text.textItem.font().pointSizeF()
                font_pixels = font_size * 1.333
                offset = 1.5 * font_pixels * pts_per_pixel
            else:
                offset = y_range * 0.03
            self.info_text.setPos(x_min + 2, y_max - offset)
    
    def update_ohlc_legend(self):
        if self.df is not None and len(self.df) > 0:
            last_row = self.df.iloc[-1]
            last_idx = self.df.index[-1]
            dt_str = ""
            if hasattr(last_idx, 'strftime'):
                try:
                    dt_str = last_idx.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    dt_str = str(last_idx)
            text = f"{dt_str}  O: {last_row['Open']:.2f}  H: {last_row['High']:.2f}  L: {last_row['Low']:.2f}  C: {last_row['Close']:.2f}"
            self.info_text.setText(text)
            self.update_info_position()
    
    def update_ohlc_legend_position(self):
        try:
            self.update_info_position()
        except Exception:
            pass
    
    def adjust_volume_height(self):
        if self.df is None or len(self.df) == 0 or 'Volume' not in self.df.columns:
            return
        
        if self.volume_item is None:
            return
        
        view_range = self.view_box.viewRange()
        y_min, y_max = view_range[1]
        
        x_min, x_max = int(max(0, view_range[0][0])), int(min(len(self.df) - 1, view_range[0][1]))
        
        if x_min >= x_max:
            return
        
        visible_df = self.df.iloc[x_min:x_max+1]
        if visible_df.empty:
            return
        
        max_volume = float(visible_df['Volume'].max())
        
        price_range = y_max - y_min
        volume_height_percentage = 0.2
        volume_scale = (price_range * volume_height_percentage) / max_volume if max_volume > 0 else 0
        
        self.volume_item.setScale(volume_scale)
        self.volume_item.setYOffset(y_min - price_range * 0.05)
    
    def set_initial_y_range(self):
        if self.df is None or len(self.df) == 0:
            return
        
        start_idx = max(0, len(self.df) - self.visible_bars)
        visible_df = self.df.iloc[start_idx:]
        
        if visible_df.empty:
            return
        
        min_price = float(visible_df['Low'].min())
        max_price = float(visible_df['High'].max())
        price_range = max_price - min_price
        
        if price_range == 0:
            price_range = max_price * 0.1 if max_price > 0 else 1.0
            min_price -= price_range / 2
            max_price += price_range / 2
            price_range = max_price - min_price
        
        y_min = min_price - price_range * 0.05
        y_max = max_price + price_range * 0.05
        
        self.plot_widget.setYRange(y_min, y_max, padding=0)
    
    def add_indicator_line(self, plot_line, visible=True, unique_name=None):
        self.overlay_lines.append(OverlayLine(plot_line, visible, unique_name or plot_line.name))
        if self.df is not None:
            self.plot_candlesticks(self.df, self.symbol)
    
    def toggle_indicator_visibility(self, unique_name: str):
        """Toggle visibility of an indicator by its unique name"""
        for overlay_line in self.overlay_lines:
            if overlay_line.unique_name == unique_name:
                overlay_line.visible = not overlay_line.visible
                self.indicator_visibility_changed.emit(unique_name, overlay_line.visible)
                self.plot_candlesticks(self.df, self.symbol)
                break
    
    def set_indicator_visibility_from_panel(self, unique_name: str, visible: bool):
        """Set visibility from external source (like edit dialog)"""
        for overlay_line in self.overlay_lines:
            if overlay_line.unique_name == unique_name:
                overlay_line.visible = visible
                if self.df is not None:
                    self.plot_candlesticks(self.df, self.symbol)
                break
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
        if state and self.df is not None:
            x_range = state.get('x_range')
            y_range = state.get('y_range')
            data_len = len(self.df)
            
            if x_range:
                x_min, x_max = x_range
                
                if x_min >= -data_len * 0.1 and x_max <= data_len * 1.1:
                    self.plot_widget.setXRange(x_min, x_max)
                else:
                    self._apply_default_view()
            else:
                self._apply_default_view()
            
            if y_range and y_range[0] != y_range[1]:
                view_width = x_range[1] - x_range[0] if x_range else data_len
                data_width = data_len
                if view_width > data_width * 2:
                    self._apply_default_view()
                else:
                    self.plot_widget.setYRange(y_range[0], y_range[1], padding=0)
            else:
                self.set_initial_y_range()
        else:
            self._apply_default_view()
    
    def _apply_default_view(self):
        if self.df is not None and len(self.df) > 0:
            self.show_last_year()
            self.set_initial_y_range()
    
    def get_drawings(self):
        result = []
        for drawing in self.drawings:
            result.append({
                'type': drawing.get('type', 'trendline'),
                'color': drawing.get('color', '#FFD700'),
                'snap': drawing.get('snap', ''),
                'params': drawing.get('params', {}),
                'points': [list(p) for p in drawing.get('points', [])]
            })
        return result
    
    def restore_drawings(self, drawings_data):
        for d in drawings_data:
            points = [tuple(p) for p in d.get('points', [])]
            if len(points) < 2:
                continue
            color = d.get('color', '#FFD700')
            x_min = -10
            x_max = len(self.df) + 10 if self.df is not None else 1000
            item = TrendLineItem(points, x_min, x_max, color, 2)
            self.plot_widget.addItem(item)
            self.drawings.append({
                'type': d.get('type', 'trendline'),
                'item': item,
                'points': points,
                'color': color,
                'snap': d.get('snap', ''),
                'params': d.get('params', {})
            })
        for drawing in self.drawings:
            self.snap_drawing_points(drawing)


class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data, bull_color='#26a69a', bear_color='#ef5350'):
        pg.GraphicsObject.__init__(self)
        self.data = data
        self.bull_color = bull_color
        self.bear_color = bear_color
        self.picture = None
        self.generatePicture()
    
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        
        body_width = 0.7
        
        for i, (t, open_val, high, low, close) in enumerate(self.data):
            if close >= open_val:
                color = self.bull_color
            else:
                color = self.bear_color
            
            pen = pg.mkPen(color, width=1)
            brush = pg.QtGui.QBrush(pg.QtGui.QColor(color), Qt.BrushStyle.SolidPattern)
            
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
        self.y_offset = 0
        self.picture = None
        self.generatePicture()
    
    def setScale(self, scale):
        self.scale = scale
        self.generatePicture()
        self.update()
    
    def setYOffset(self, offset):
        self.y_offset = offset
        self.generatePicture()
        self.update()
    
    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        p = pg.QtGui.QPainter(self.picture)
        
        bar_width = 0.7
        
        for i, (t, vol, color) in enumerate(self.data):
            pen = pg.mkPen(color, width=1)
            brush = pg.QtGui.QBrush(pg.QtGui.QColor(color), Qt.BrushStyle.SolidPattern)
            
            p.setPen(pen)
            p.setBrush(brush)
            
            bar_height = vol * self.scale
            p.drawRect(pg.QtCore.QRectF(t - bar_width/2, self.y_offset, bar_width, bar_height))
        
        p.end()
    
    def paint(self, p, *args):
        p.drawPicture(0, 0, self.picture)
    
    def boundingRect(self):
        return pg.QtCore.QRectF(self.picture.boundingRect())