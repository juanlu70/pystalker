"""
PyStalker - Main Window
Porting of Qtstalker to Python/PyQt6
"""
from pathlib import Path
import pandas as pd
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QMenuBar, QMenu, QToolBar, QStatusBar, QProgressBar,
    QMessageBox, QFileDialog, QComboBox, QLabel, QDialog, QInputDialog,
    QDialogButtonBox, QApplication, QDateEdit, QPushButton
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QByteArray, QTimer, QSettings, QDate
from PyQt6.QtGui import QAction, QIcon

from .navigator import AssetNavigator
from .chart_view import ChartView, OverlayLine
from .chart_tab import ChartTabWidget
from ..core.data import BarData, ChartAssets
from ..core.providers import DataManager
from ..core.database import Database
from ..core.indicators import IndicatorManager, Indicator

ICONS_DIR = Path(__file__).parent.parent.parent / 'assets'

def load_icon(name: str) -> QIcon:
    xpm_path = ICONS_DIR / f'{name}.xpm'
    if xpm_path.exists():
        return QIcon(str(xpm_path))
    return QIcon()

class DownloadThread(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, data_manager, symbol, interval='1d'):
        super().__init__()
        self.data_manager = data_manager
        self.symbol = symbol
        self.interval = interval
    
    def run(self):
        try:
            bar_data = self.data_manager.fetch_yahoo(self.symbol, interval=self.interval)
            self.finished.emit(bar_data)
        except Exception as e:
            self.error.emit(str(e))


class DownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Downloading...")
        self.setFixedSize(300, 120)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        
        layout = QVBoxLayout(self)
        
        self.label = QLabel("Initializing download...")
        layout.addWidget(self.label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.button_box.rejected.connect(self.on_cancel)
        layout.addWidget(self.button_box)
        
        self.cancelled = False
    
    def set_symbol(self, symbol):
        self.label.setText(f"Downloading {symbol} from Yahoo Finance...")
    
    def on_cancel(self):
        self.cancelled = True
        self.reject()


class PyStalkerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.assets = ChartAssets()
        self.data_manager = DataManager()
        self.database = Database()
        self.current_symbol = None
        self.indicator_dialog = None
        
        self.setWindowTitle("PyStalker - Stock Charting Tool")
        self.setMinimumSize(1024, 768)
        
        self.setWindowState(Qt.WindowState.WindowMaximized)
        
        self.init_ui()
        self.load_saved_symbols()
        
        QTimer.singleShot(100, self.restore_session_lazy)
    
    def restore_session_lazy(self):
        self.statusBar().showMessage("Loading session...")
        progress = QProgressBar(self)
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        self.statusBar().addPermanentWidget(progress)
        
        QApplication.processEvents()
        
        settings = self.database.load_settings()
        
        bull_color = settings.get('bull_color', '#55aaff')
        bear_color = settings.get('bear_color', '#ef5350')
        
        main_splitter_state = settings.get('main_splitter_state')
        if main_splitter_state:
            self.main_splitter.restoreState(QByteArray.fromBase64(main_splitter_state.encode()))
        
        open_tabs, current_tab = self.database.load_session()
        
        total = len(open_tabs)
        if total > 0:
            if current_tab and current_tab in open_tabs:
                open_tabs.remove(current_tab)
                open_tabs.insert(0, current_tab)
            
            # Load and show the current (first) tab immediately
            symbol = open_tabs[0]
            self.statusBar().showMessage(f"Loading {symbol}...")
            QApplication.processEvents()
            
            cached_data = self.database.load_bars(symbol)
            if cached_data:
                self.assets.add_asset(symbol, cached_data)
                self.load_chart(symbol, from_session_restore=True, bull_color=bull_color, bear_color=bear_color)
            
            tab = self.chart_tabs.tabs.get(symbol)
            splitter_state = settings.get(f'splitter_state_{symbol}')
            if splitter_state and tab:
                tab.splitter.restoreState(QByteArray.fromBase64(splitter_state.encode()))
            
            progress.setRange(0, total)
            progress.setValue(1)
            
            # Load remaining tabs one at a time via deferred events
            background_tabs = open_tabs[1:]
            self._bg_queue = [(sym, bull_color, bear_color, settings) for sym in background_tabs]
            self._bg_progress = progress
            self._bg_total = total
            self._bg_index = 0
            if self._bg_queue:
                QTimer.singleShot(0, self._load_next_bg_tab)
            else:
                self._finish_bg_loading()
        else:
            self.statusBar().removeWidget(progress)
            self.statusBar().showMessage("Ready", 2000)
            self.restore_settings()
    
    def _load_next_bg_tab(self):
        if not self._bg_queue:
            self._finish_bg_loading()
            return
        
        symbol, bull_color, bear_color, settings = self._bg_queue.pop(0)
        self._bg_index += 1
        
        self.statusBar().showMessage(f"Loading {symbol}...")
        
        cached_data = self.database.load_bars(symbol)
        if cached_data:
            self.assets.add_asset(symbol, cached_data)
            self.load_chart(symbol, from_session_restore=True, bull_color=bull_color, bear_color=bear_color, set_current=False)
        
        tab = self.chart_tabs.tabs.get(symbol)
        if tab:
            tab.hide()
        
        splitter_state = settings.get(f'splitter_state_{symbol}')
        if splitter_state and tab:
            tab.splitter.restoreState(QByteArray.fromBase64(splitter_state.encode()))
        
        self._bg_progress.setValue(self._bg_index + 1)
        
        if self._bg_queue:
            QTimer.singleShot(0, self._load_next_bg_tab)
        else:
            self._finish_bg_loading()
    
    def _finish_bg_loading(self):
        self.statusBar().removeWidget(self._bg_progress)
        self.statusBar().showMessage("Ready", 2000)
        self.restore_settings()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter = main_splitter
        main_layout.addWidget(main_splitter)
        
        self.navigator = AssetNavigator()
        self.navigator.setMinimumWidth(200)
        self.navigator.setMaximumWidth(400)
        self.navigator.asset_selected.connect(self.on_asset_selected)
        self.navigator.spread_selected.connect(self.on_spread_selected)
        self.navigator.spread_removed.connect(self.on_spread_removed)
        self.navigator.asset_removed.connect(self.on_asset_removed)
        self.navigator.copy_graph.connect(self.on_copy_graph)
        self.navigator.rename_graph.connect(self.on_rename_graph)
        main_splitter.addWidget(self.navigator)
        
        self.chart_tabs = ChartTabWidget()
        self.chart_tabs.chart_closed.connect(self.on_chart_closed)
        self.chart_tabs.colors_changed_global.connect(self.on_colors_changed_global)
        self.chart_tabs.current_changed.connect(self.on_chart_tab_changed)
        self.chart_tabs.indicatorPanelDoubleClicked.connect(self.on_indicator_panel_double_clicked)
        main_splitter.addWidget(self.chart_tabs)
        
        main_splitter.setSizes([250, 750])
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(20)
        self.progress_bar.hide()
        self.status_bar.addPermanentWidget(self.progress_bar)
        
        self.status_bar.showMessage("Ready")
        
        self.init_menubar()
        self.init_toolbar()
    
    def init_menubar(self):
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("&File")
        
        download_yahoo = QAction(load_icon('download'), "Download from Yahoo...", self)
        download_yahoo.setShortcut("Ctrl+D")
        download_yahoo.triggered.connect(self.on_open_chart)
        file_menu.addAction(download_yahoo)
        
        update_all_action = QAction(load_icon('update_data'), "Update All Stock Data", self)
        update_all_action.setShortcut("Ctrl+U")
        update_all_action.triggered.connect(self.on_update_all)
        file_menu.addAction(update_all_action)
        
        import_csv = QAction(load_icon('import'), "Import CSV...", self)
        import_csv.triggered.connect(self.on_import_csv)
        file_menu.addAction(import_csv)
        
        file_menu.addSeparator()
        
        create_spread_action = QAction("Create Spread...", self)
        create_spread_action.triggered.connect(self.on_create_spread)
        file_menu.addAction(create_spread_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction(load_icon('stop'), "E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        chart_menu = menubar.addMenu("&Chart Style")
        
        self.chart_style_group = None
        self.chart_style_actions = {}
        for style, label in [('candlestick', 'Candlestick'), ('line', 'Line (Close)'), ('heikin_ashi', 'Heikin Ashi')]:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(style)
            action.triggered.connect(lambda checked, s=style: self.on_chart_style(s))
            chart_menu.addAction(action)
            self.chart_style_actions[style] = action
        self.chart_style_actions['candlestick'].setChecked(True)
        
        indicator_menu = menubar.addMenu("&Indicators")
        
        add_indicator_action = QAction(load_icon('indicator'), "Add Indicator...", self)
        add_indicator_action.setShortcut("Ctrl+I")
        add_indicator_action.triggered.connect(self.on_add_indicator)
        indicator_menu.addAction(add_indicator_action)
        
        edit_indicators_action = QAction("Edit Indicators...", self)
        edit_indicators_action.setShortcut("Ctrl+E")
        edit_indicators_action.triggered.connect(self.on_edit_indicators)
        indicator_menu.addAction(edit_indicators_action)
        
        clear_indicators_action = QAction("Clear All Indicators", self)
        clear_indicators_action.triggered.connect(self.on_clear_indicators)
        indicator_menu.addAction(clear_indicators_action)
        
        draw_menu = menubar.addMenu("&Draw")
        
        trendline_action = QAction("Draw Trendline", self)
        trendline_action.setShortcut("T")
        trendline_action.triggered.connect(self.on_draw_trendline)
        draw_menu.addAction(trendline_action)
        
        hline_action = QAction("Draw Horizontal Line", self)
        hline_action.triggered.connect(self.on_draw_hline)
        draw_menu.addAction(hline_action)
        
        vline_action = QAction("Draw Vertical Line", self)
        vline_action.triggered.connect(self.on_draw_vline)
        draw_menu.addAction(vline_action)
        
        asc_channel_action = QAction("Draw Ascending Channel", self)
        asc_channel_action.triggered.connect(self.on_draw_asc_channel)
        draw_menu.addAction(asc_channel_action)
        
        desc_channel_action = QAction("Draw Descending Channel", self)
        desc_channel_action.triggered.connect(self.on_draw_desc_channel)
        draw_menu.addAction(desc_channel_action)
        
        draw_menu.addSeparator()
        
        clear_trendlines_action = QAction("Clear Drawings", self)
        clear_trendlines_action.triggered.connect(self.on_clear_drawings)
        draw_menu.addAction(clear_trendlines_action)
        
        edit_drawings_action = QAction("Edit Drawings...", self)
        edit_drawings_action.triggered.connect(self.on_edit_drawings)
        draw_menu.addAction(edit_drawings_action)
        
        snap_menu = draw_menu.addMenu("Snap Mode")
        
        snap_none_action = QAction("None", self)
        snap_none_action.triggered.connect(lambda: self.set_snap_mode(None))
        snap_menu.addAction(snap_none_action)
        
        snap_open_action = QAction("Open", self)
        snap_open_action.triggered.connect(lambda: self.set_snap_mode('open'))
        snap_menu.addAction(snap_open_action)
        
        snap_high_action = QAction("High", self)
        snap_high_action.triggered.connect(lambda: self.set_snap_mode('high'))
        snap_menu.addAction(snap_high_action)
        
        snap_low_action = QAction("Low", self)
        snap_low_action.triggered.connect(lambda: self.set_snap_mode('low'))
        snap_menu.addAction(snap_low_action)
        
        snap_close_action = QAction("Close", self)
        snap_close_action.triggered.connect(lambda: self.set_snap_mode('close'))
        snap_menu.addAction(snap_close_action)
        
        view_menu = menubar.addMenu("&View")
        
        timeframe_menu = view_menu.addMenu("Timeframe")
        
        timeframes = ['1m', '5m', '10m', '15m', '30m', '1h', '1d', '1wk', '1mo']
        for tf in timeframes:
            action = QAction(tf, self)
            action.triggered.connect(lambda checked, t=tf: self.on_timeframe_changed(t))
            timeframe_menu.addAction(action)
        
        zoom_menu = view_menu.addMenu("Zoom")
        
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut("+")
        zoom_in_action.triggered.connect(self.zoom_in)
        zoom_menu.addAction(zoom_in_action)
        
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut("-")
        zoom_out_action.triggered.connect(self.zoom_out)
        zoom_menu.addAction(zoom_out_action)
        
        reset_zoom_action = QAction("Reset Zoom", self)
        reset_zoom_action.setShortcut("Home")
        reset_zoom_action.triggered.connect(self.reset_zoom)
        zoom_menu.addAction(reset_zoom_action)
        
        reset_graph_action = QAction("Reset Graph (Y)", self)
        reset_graph_action.setShortcut("Y")
        reset_graph_action.triggered.connect(self.show_last_year)
        view_menu.addAction(reset_graph_action)
        
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction(load_icon('help'), "About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def init_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setObjectName("MainToolbar")
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)
        
        download_action = QAction(load_icon('download'), "Download from Yahoo", self)
        download_action.setToolTip("Download stock data from Yahoo Finance")
        download_action.triggered.connect(self.on_open_chart)
        toolbar.addAction(download_action)
        
        update_all_action = QAction(load_icon('update_data'), "Update All Stock Data", self)
        update_all_action.setToolTip("Update all stock data from Yahoo Finance")
        update_all_action.triggered.connect(self.on_update_all)
        toolbar.addAction(update_all_action)
        
        toolbar.addSeparator()
        
        timeframe_label = toolbar.addWidget(QLabel())
        timeframe_label.setText("Timeframe: ")
        
        self.timeframe_combo = TimeframeComboBox()
        self.timeframe_combo.currentTextChanged.connect(self.on_timeframe_changed)
        toolbar.addWidget(self.timeframe_combo)
        
        toolbar.addSeparator()
        
        zoom_in = QAction(load_icon('zoom_in'), "Zoom In", toolbar)
        zoom_in.setToolTip("Zoom In")
        zoom_in.triggered.connect(self.zoom_in)
        toolbar.addAction(zoom_in)
        
        zoom_out = QAction(load_icon('zoom_out'), "Zoom Out", toolbar)
        zoom_out.setToolTip("Zoom Out")
        zoom_out.triggered.connect(self.zoom_out)
        toolbar.addAction(zoom_out)
        
        reset_view = QAction(load_icon('home'), "Reset", toolbar)
        reset_view.setToolTip("Reset View")
        reset_view.triggered.connect(self.reset_zoom)
        toolbar.addAction(reset_view)
        
        reset_graph = QAction(load_icon('reset_graph'), "Reset Graph (Y)", toolbar)
        reset_graph.setToolTip("Reset Graph - Show Last Year")
        reset_graph.triggered.connect(self.show_last_year)
        toolbar.addAction(reset_graph)
        
        toolbar.addSeparator()
        
        self.draw_mode_action = QAction(load_icon('trend'), "Draw Mode", toolbar)
        self.draw_mode_action.setCheckable(True)
        self.draw_mode_action.setChecked(False)
        self.draw_mode_action.setToolTip("Toggle Draw Mode (disables panning/zooming)")
        self.draw_mode_action.triggered.connect(self.on_toggle_draw_mode)
        toolbar.addAction(self.draw_mode_action)
        
        asc_channel_action = QAction(load_icon('asc_channel'), "Ascending Channel", toolbar)
        asc_channel_action.setToolTip("Draw Ascending Channel")
        asc_channel_action.triggered.connect(self.on_draw_asc_channel)
        toolbar.addAction(asc_channel_action)
        
        desc_channel_action = QAction(load_icon('desc_channel'), "Descending Channel", toolbar)
        desc_channel_action.setToolTip("Draw Descending Channel")
        desc_channel_action.triggered.connect(self.on_draw_desc_channel)
        toolbar.addAction(desc_channel_action)
        
        toolbar.addSeparator()
        
        self.undo_action = QAction("Undo", toolbar)
        self.undo_action.setToolTip("Undo last drawing change (Ctrl+Z)")
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.triggered.connect(self.on_undo)
        toolbar.addAction(self.undo_action)
        
        toolbar.addSeparator()
        
        crosshair_action = QAction(load_icon('crosshair'), "Crosshair", toolbar)
        crosshair_action.setCheckable(True)
        crosshair_action.setChecked(True)
        crosshair_action.triggered.connect(self.on_toggle_crosshair)
        toolbar.addAction(crosshair_action)
        
        toolbar.addSeparator()
        
        limit_label = QLabel(" Limit: ")
        toolbar.addWidget(limit_label)
        
        self.limit_date_edit = QDateEdit()
        self.limit_date_edit.setCalendarPopup(True)
        self.limit_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.limit_date_edit.setDate(QDate.currentDate())
        self.limit_date_edit.setSpecialValueText("None")
        self.limit_date_edit.setEnabled(False)
        toolbar.addWidget(self.limit_date_edit)
        
        self.limit_advance_action = QAction(load_icon("play"), "Advance 1 day", toolbar)
        self.limit_advance_action.setToolTip("Advance limit date by 1 trading day")
        self.limit_advance_action.triggered.connect(self.on_limit_date_advance)
        toolbar.addAction(self.limit_advance_action)
        
        self.limit_date_action = QAction("Set", toolbar)
        self.limit_date_action.setToolTip("Apply limit date to chart")
        self.limit_date_action.triggered.connect(self.on_limit_date_apply)
        toolbar.addAction(self.limit_date_action)
        
        self.limit_clear_action = QAction("Clear", toolbar)
        self.limit_clear_action.setToolTip("Remove limit date filter")
        self.limit_clear_action.triggered.connect(self.on_limit_date_clear)
        toolbar.addAction(self.limit_clear_action)
    
    def on_limit_date_apply(self):
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        qdate = self.limit_date_edit.date()
        if not qdate.isValid():
            return
        limit_date = qdate.toPyDate()
        chart_view = tab.chart_view
        chart_view.set_limit_date(limit_date)
        self._apply_limit_filter(tab)
    
    def on_limit_date_clear(self):
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        chart_view = tab.chart_view
        chart_view.clear_limit_date()
        self._apply_limit_filter(tab)
    
    def on_limit_date_advance(self):
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        chart_view = tab.chart_view
        if chart_view._full_df is None or chart_view._full_df.empty:
            return
        current_limit = chart_view._limit_date
        if current_limit is None:
            return
        df = chart_view._full_df
        future = df[df.index.date > current_limit] if hasattr(df.index, 'date') else df[df.index > pd.Timestamp(current_limit)]
        if future.empty:
            return
        next_date = future.index[0]
        if hasattr(next_date, 'date'):
            next_date = next_date.date()
        chart_view.set_limit_date(next_date)
        self.limit_date_edit.setDate(QDate(next_date.year, next_date.month, next_date.day))
        self._apply_limit_filter(tab)
    
    def _apply_limit_filter(self, tab):
        from ..core.indicators import IndicatorManager
        chart_view = tab.chart_view
        filtered_df = chart_view.df
        if filtered_df is None or filtered_df.empty:
            return
        
        for panel_name in list(tab._indicator_panels.keys()):
            panel = tab._indicator_panels.pop(panel_name)
            panel.range_changed.disconnect(tab.on_indicator_range_changed)
            panel.setParent(None)
            panel.deleteLater()
        tab._distribute_splitter_sizes()
        
        chart_view.overlay_lines.clear()
        chart_view.indicator_curves.clear()
        
        for ind in tab.indicators:
            colors = ind.get('colors', {})
            hlines = ind.get('hlines', [])
            params = dict(ind.get('params', {}))
            if hlines:
                params['hlines'] = hlines
            unique_name = ind.get('name', ind.get('indicator_name', ''))
            indicator = IndicatorManager.calculate_indicator(ind['indicator_name'], filtered_df, params, colors=colors)
            if indicator:
                visible = ind.get('visible', True)
                if ind['type'] == 'overlay':
                    for line in indicator.lines:
                        chart_view.overlay_lines.append(OverlayLine(line, visible, unique_name or line.name))
                else:
                    if visible:
                        tab.add_indicator_panel(indicator, filtered_df)
        
        chart_view.plot_candlesticks(chart_view._full_df, chart_view.symbol)
    
    def on_open_chart(self):
        text, ok = QInputDialog.getText(self, "Download from Yahoo Finance", 
                                         "Enter ticker symbol (e.g., AAPL, MSFT, GOOGL):")
        if ok and text:
            symbol = text.strip().upper()
            if symbol:
                self.fetch_symbol(symbol)
    
    def on_import_csv(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import CSV", "", "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            try:
                data = self.data_manager.fetch_csv(file_path)
                self.assets.add_asset(data.symbol, data)
                self.navigator.add_asset(data.symbol)
                self.load_chart(data.symbol)
                self.status_bar.showMessage(f"Imported {data.symbol} ({data.count()} bars)")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import CSV: {e}")
    
    def on_create_spread(self):
        from .spread_dialog import SpreadDialog
        symbols = self.assets.get_symbols()
        if len(symbols) < 2:
            QMessageBox.information(self, "Create Spread", "You need at least 2 assets loaded to create a spread.")
            return
        spreads = self.database.load_spreads()
        dialog = SpreadDialog(symbols, spreads, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            symbol1 = dialog.get_symbol1()
            symbol2 = dialog.get_symbol2()
            start_date = dialog.get_start_date()
            spread_name = dialog.get_spread_name()
            self.database.save_spread(spread_name, symbol1, symbol2, start_date)
            self.navigator.add_spread(spread_name)
            self.on_spread_selected(spread_name)
    
    def on_spread_selected(self, name: str):
        spread = self.database.load_spread(name)
        if not spread:
            return
        symbol1 = spread['symbol1']
        symbol2 = spread['symbol2']
        start_date = spread['start_date']
        
        asset1 = self.assets.get_asset(symbol1)
        asset2 = self.assets.get_asset(symbol2)
        if not asset1:
            cached = self.database.load_bars(symbol1)
            if cached:
                self.assets.add_asset(symbol1, cached)
                asset1 = cached
        if not asset2:
            cached = self.database.load_bars(symbol2)
            if cached:
                self.assets.add_asset(symbol2, cached)
                asset2 = cached
        if not asset1 or not asset2:
            QMessageBox.warning(self, "Spread", f"Asset data not found. Please load {symbol1} and {symbol2} first.")
            return
        
        from ..core.spread import calculate_spread
        result = calculate_spread(asset1.to_dataframe(), asset2.to_dataframe(), start_date)
        if result is None:
            QMessageBox.warning(self, "Spread", "No overlapping data found for the selected assets and date range.")
            return
        
        dates, series1, series2 = result
        
        s1 = series1.values
        s2 = series2.values
        
        spread_df = pd.DataFrame({
            'Open': s1,
            'High': np.maximum(s1, s2),
            'Low': np.minimum(s1, s2),
            'Close': s1,
            'Volume': 0,
            'Series2': s2
        }, index=dates)
        
        from ..core.data import BarData, Bar
        bars = []
        for i in range(len(spread_df)):
            idx = spread_df.index[i]
            if hasattr(idx, 'to_pydatetime'):
                dt = idx.to_pydatetime()
            else:
                from datetime import datetime
                dt = datetime.fromtimestamp(int(idx))
            bars.append(Bar(
                date=dt,
                open=float(spread_df['Open'].iloc[i]),
                high=float(spread_df['High'].iloc[i]),
                low=float(spread_df['Low'].iloc[i]),
                close=float(spread_df['Close'].iloc[i]),
                volume=0.0
            ))
        bar_data = BarData(name)
        bar_data.bars = bars
        bar_data.is_spread = True
        bar_data.spread_symbol1 = symbol1
        bar_data.spread_symbol2 = symbol2
        bar_data._df = spread_df
        self.assets.add_asset(name, bar_data)
        
        self.database.save_bars(bar_data)
        self.database.save_spread_lines(name, symbol1, symbol2, '#00BFFF', '#FF6B6B')
        
        existing_tab = self.chart_tabs.tabs.get(name)
        if existing_tab:
            self.chart_tabs.setCurrentWidget(existing_tab)
            return
        
        self.load_chart(name)
        
        for s, action in self.chart_style_actions.items():
            action.setChecked(s == 'line')
    
    def on_spread_removed(self, name: str):
        self.database.delete_spread(name)
        self.database.delete_symbol(name)
        self.assets.remove_asset(name)
    
    def on_asset_removed(self, symbol: str):
        if symbol in self.chart_tabs.tabs:
            tab = self.chart_tabs.tabs[symbol]
            idx = self.chart_tabs.indexOf(tab)
            if idx >= 0:
                self.chart_tabs.removeTab(idx)
            del self.chart_tabs.tabs[symbol]
        self.assets.remove_asset(symbol)
        self.database.delete_symbol(symbol)
    
    def on_spread_start_date_change(self):
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol or not tab.chart_view.is_spread:
            return
        name = tab.symbol
        spread = self.database.load_spread(name)
        if not spread:
            return
        
        from PyQt6.QtWidgets import QDateEdit, QDialog, QVBoxLayout, QDialogButtonBox
        from PyQt6.QtCore import QDate
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Start Date")
        layout = QVBoxLayout(dialog)
        date_edit = QDateEdit()
        date_edit.setCalendarPopup(True)
        current_date = QDate.fromString(spread['start_date'], "yyyy-MM-dd")
        if not current_date.isValid():
            current_date = QDate.currentDate().addYears(-1)
        date_edit.setDate(current_date)
        date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addWidget(date_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        
        new_date = date_edit.date().toString("yyyy-MM-dd")
        self.database.save_spread(name, spread['symbol1'], spread['symbol2'], new_date)
        
        if name in self.chart_tabs.tabs:
            del self.chart_tabs.tabs[name]
            idx = self.chart_tabs.indexOf(tab)
            self.chart_tabs.removeTab(idx)
        self.assets.remove_asset(name)
        self.database.delete_symbol(name)
        
        self.on_spread_selected(name)
    
    def on_update_all(self):
        symbols = self.database.get_symbols()
        if not symbols:
            QMessageBox.information(self, "Update All Stock Data", "No symbols in the database. Download some data first.")
            return
        
        progress = QProgressBar(self)
        progress.setRange(0, len(symbols))
        progress.setValue(0)
        progress.setMaximumHeight(20)
        progress.setTextVisible(True)
        self.status_bar.addPermanentWidget(progress)
        self.status_bar.showMessage(f"Updating {len(symbols)} symbols...")
        QApplication.processEvents()
        
        errors = []
        for i, symbol in enumerate(symbols):
            if self.database.is_copy(symbol):
                continue
            
            self.status_bar.showMessage(f"Updating {symbol} ({i+1}/{len(symbols)})...")
            QApplication.processEvents()
            
            try:
                bar_data = self.data_manager.fetch_yahoo(symbol)
                if bar_data and bar_data.count() > 0:
                    self.database.save_bars(bar_data)
                    self.assets.add_asset(symbol, bar_data)
                    self.navigator.add_asset(symbol)
                    
                    tab = self.chart_tabs.tabs.get(symbol)
                    if tab:
                        df = bar_data.to_dataframe()
                        indicators = tab.get_indicators()
                        tab.chart_view.overlay_lines.clear()
                        tab.clear_indicator_panels()
                        tab.load_data(df, symbol)
                        
                        for ind in indicators:
                            colors = ind.get('colors', {})
                            indicator = IndicatorManager.calculate_indicator(ind['indicator_name'], df, ind.get('params'), colors=colors)
                            if indicator:
                                if ind.get('type') == 'overlay':
                                    visible = ind.get('visible', True)
                                    for line in indicator.lines:
                                        tab.chart_view.add_indicator_line(line, visible=visible, unique_name=ind['name'])
                                else:
                                    if ind.get('visible', True):
                                        tab.add_indicator_panel(indicator, df)
                        
                        tab.chart_view.plot_candlesticks(df, symbol)
                        tab.chart_view._needs_view_reset = True
                    
                    self._refresh_copies_of(symbol, bar_data)
            except Exception as e:
                errors.append((symbol, str(e)))
            
            progress.setValue(i + 1)
            QApplication.processEvents()
        
        self.status_bar.removeWidget(progress)
        
        if errors:
            error_msg = "\n".join(f"{s}: {e}" for s, e in errors)
            QMessageBox.warning(self, "Update Errors", f"Some symbols failed to update:\n{error_msg}")
        
        self.status_bar.showMessage(f"Updated {len(symbols) - len(errors)}/{len(symbols)} symbols", 3000)
    
    def fetch_symbol(self, symbol: str, interval: str = '1d'):
        self.download_dialog = DownloadDialog(self)
        self.download_dialog.set_symbol(symbol)
        
        self.download_thread = DownloadThread(self.data_manager, symbol, interval)
        self.download_thread.finished.connect(lambda data: self.on_download_finished(symbol, interval, data))
        self.download_thread.error.connect(self.on_download_error)
        
        self.download_thread.start()
        self.download_dialog.exec()
        
        if self.download_dialog.cancelled:
            self.download_thread.terminate()
            self.download_thread.wait()
    
    def on_download_finished(self, symbol, interval, bar_data):
        if self.download_dialog and self.download_dialog.isVisible():
            self.download_dialog.accept()
        
        self.assets.add_asset(symbol, bar_data)
        self.database.save_bars(bar_data, interval)
        
        if symbol not in self.navigator.get_assets():
            self.navigator.add_asset(symbol)
        
        self.load_chart(symbol, interval)
        self.current_symbol = symbol
        
        self.status_bar.showMessage(f"Downloaded {symbol} ({bar_data.count()} bars)")
        self._refresh_copies_of(symbol, bar_data)
    
    def on_download_error(self, error_msg):
        if self.download_dialog and self.download_dialog.isVisible():
            self.download_dialog.reject()
        QMessageBox.critical(self, "Error", f"Failed to fetch data: {error_msg}")
        self.status_bar.showMessage("Download failed")
    
    def load_chart(self, symbol: str, interval: str = '1d', from_session_restore: bool = False, bull_color: str = None, bear_color: str = None, set_current: bool = True):
        asset = self.assets.get_asset(symbol)
        if not asset:
            cached_data = self.database.load_bars(symbol, interval)
            if cached_data:
                self.assets.add_asset(symbol, cached_data)
                asset = cached_data
        
        if not asset:
            return
        
        source = self._get_source_asset(asset)
        if not source and getattr(asset, 'source_symbol', ''):
            source = self.database.load_bars(asset.source_symbol, interval)
            if source:
                self.assets.add_asset(asset.source_symbol, source)
        self.current_symbol = symbol
        df = source.to_dataframe() if source else asset.to_dataframe()
        
        tab, is_new = self.chart_tabs.add_chart_tab(symbol, interval, set_current=set_current)
        
        if bull_color and bear_color:
            tab.chart_view.set_colors(bull_color, bear_color)
        
        if is_new:
            tab.chart_view.drawModeToggled.connect(self.on_draw_mode_toggled)
            tab.chart_view.drawingDoubleClicked.connect(self.on_drawing_double_clicked)
            tab.chart_view.spreadStartDateChangeRequested.connect(self.on_spread_start_date_change)
        
        if asset.is_spread:
            tab.chart_view.is_spread = True
            tab.chart_view.spread_symbol1 = asset.spread_symbol1
            tab.chart_view.spread_symbol2 = asset.spread_symbol2
            tab.chart_view.spread_color1 = asset.spread_color1
            tab.chart_view.spread_color2 = asset.spread_color2
            tab.chart_view.line_color = asset.spread_color1
            tab.chart_view.chart_style = 'line'
            self.database.save_chart_style(symbol, 'line')
        
        tab.load_data(df, symbol, interval)
        
        if not is_new:
            saved_style = self.database.load_chart_style(symbol)
            if saved_style != tab.chart_view.chart_style:
                tab.chart_view.set_chart_style(saved_style)
            if not from_session_restore:
                self.save_session()
            return
        
        saved_indicators = self.database.load_chart_indicators(symbol)
        for ind in saved_indicators:
            colors = ind.get('colors', {})
            hlines = ind.get('hlines', [])
            params = dict(ind.get('params', {}))
            if hlines:
                params['hlines'] = hlines
            indicator = IndicatorManager.calculate_indicator(ind['indicator_name'], df, params, colors=colors)
            if indicator:
                color = ind.get('color')
                visible = ind.get('visible', True)
                tab.add_indicator(ind['indicator_name'], ind['type'], ind.get('params', {}))
                tab.indicators[-1]['name'] = ind['name']
                tab.indicators[-1]['color'] = color if color else '#00BFFF'
                tab.indicators[-1]['colors'] = colors
                tab.indicators[-1]['visible'] = visible
                tab.indicators[-1]['hlines'] = [{'level': hl['level'], 'color': hl['color']} for hl in indicator.hlines]
                
                if ind['type'] == 'overlay':
                    for line in indicator.lines:
                        tab.chart_view.add_indicator_line(line, visible=visible, unique_name=ind['name'])
                else:
                    if visible:
                        tab.add_indicator_panel(indicator, df)
        
        if saved_indicators:
            tab.chart_view.plot_candlesticks(df, symbol)
        
        saved_drawings = self.database.load_drawings(symbol)
        if saved_drawings:
            tab.chart_view.restore_drawings(saved_drawings)
        
        saved_style = self.database.load_chart_style(symbol)
        if saved_style != tab.chart_view.chart_style:
            tab.chart_view.set_chart_style(saved_style)
            for s, action in self.chart_style_actions.items():
                action.setChecked(s == saved_style)
        
        if not from_session_restore:
            self.save_session()
        
        self.limit_date_edit.setEnabled(True)
        if tab.chart_view._full_df is not None and len(tab.chart_view._full_df) > 0:
            last_date = tab.chart_view._full_df.index[-1]
            if hasattr(last_date, 'date'):
                last_date = last_date.date()
            self.limit_date_edit.setDate(QDate(last_date.year, last_date.month, last_date.day))
    
    def on_asset_selected(self, symbol: str):
        if symbol in self.assets.get_symbols():
            self.load_chart(symbol)
        else:
            cached_data = self.database.load_bars(symbol)
            if cached_data:
                self.assets.add_asset(symbol, cached_data)
                self.load_chart(symbol)
            else:
                self.fetch_symbol(symbol)
    
    def _get_source_asset(self, asset):
        if getattr(asset, 'source_symbol', ''):
            source = self.assets.get_asset(asset.source_symbol)
            if source:
                return source
        return None

    def _resolve_df(self, asset):
        source = self._get_source_asset(asset)
        if source:
            return source.to_dataframe()
        return asset.to_dataframe()

    def on_copy_graph(self, symbol: str):
        asset = self.assets.get_asset(symbol)
        if not asset:
            cached_data = self.database.load_bars(symbol)
            if cached_data:
                self.assets.add_asset(symbol, cached_data)
                asset = cached_data
        if not asset:
            return
        
        existing = self.database.get_symbols()
        n = 1
        new_symbol = f"{symbol}-{n}"
        while new_symbol in existing:
            n += 1
            new_symbol = f"{symbol}-{n}"
        
        new_bar_data = BarData(new_symbol)
        new_bar_data.source_symbol = symbol
        
        self.database.save_bars(new_bar_data)
        self.assets.add_asset(new_symbol, new_bar_data)
        self.navigator.add_asset(new_symbol)
        self.load_chart(new_symbol)
    
    def _refresh_copies_of(self, source_symbol, bar_data):
        for sym, asset in list(self.assets.assets.items()):
            if getattr(asset, 'source_symbol', '') == source_symbol:
                tab = self.chart_tabs.tabs.get(sym)
                if tab:
                    df = self._resolve_df(asset)
                    indicators = tab.get_indicators()
                    tab.chart_view.overlay_lines.clear()
                    tab.clear_indicator_panels()
                    tab.load_data(df, sym)
                    for ind in indicators:
                        colors = ind.get('colors', {})
                        indicator = IndicatorManager.calculate_indicator(ind['indicator_name'], df, ind.get('params'), colors=colors)
                        if indicator:
                            if ind.get('type') == 'overlay':
                                visible = ind.get('visible', True)
                                for line in indicator.lines:
                                    tab.chart_view.add_indicator_line(line, visible=visible, unique_name=ind['name'])
                            else:
                                if ind.get('visible', True):
                                    tab.add_indicator_panel(indicator, df)
                    tab.chart_view.plot_candlesticks(df, sym)
                    tab.chart_view._needs_view_reset = True

    def on_rename_graph(self, symbol: str):
        from PyQt6.QtWidgets import QInputDialog
        new_symbol, ok = QInputDialog.getText(self, "Rename Graph", f"New name for {symbol}:", text=symbol)
        if not ok or not new_symbol:
            return
        new_symbol = new_symbol.strip().upper()
        if not new_symbol or new_symbol == symbol:
            return
        if new_symbol in self.assets.get_symbols():
            return
        
        self.database.rename_symbol(symbol, new_symbol)
        asset = self.assets.get_asset(symbol)
        if asset:
            asset.symbol = new_symbol
            self.assets.remove_asset(symbol)
            self.assets.add_asset(new_symbol, asset)
        
        self.navigator.rename_asset(symbol, new_symbol)
        
        if symbol in self.chart_tabs.tabs:
            tab = self.chart_tabs.tabs[symbol]
            tab.symbol = new_symbol
            del self.chart_tabs.tabs[symbol]
            self.chart_tabs.tabs[new_symbol] = tab
            idx = self.chart_tabs.indexOf(tab)
            self.chart_tabs.setTabText(idx, new_symbol)
        
        self.save_session()
    
    def on_chart_closed(self, symbol: str):
        self.save_session()
    
    def on_colors_changed_global(self, bull_color: str, bear_color: str):
        for symbol, tab in self.chart_tabs.tabs.items():
            tab.chart_view.set_colors(bull_color, bear_color)
            if tab.df is not None and not tab.df.empty:
                tab.chart_view.plot_candlesticks(tab.df, tab.symbol)
    
    def on_timeframe_changed(self, timeframe: str):
        if self.current_symbol:
            self.fetch_symbol(self.current_symbol, timeframe)
    
    def on_add_indicator(self):
        from .indicator_dialog import IndicatorDialog
        
        tab = self.chart_tabs.get_current_tab()
        existing = tab.get_indicators() if tab else []
        
        dialog = IndicatorDialog(self, existing)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            indicator_name = dialog.get_indicator_name()
            params = dialog.get_indicator_params()
            color = dialog.get_indicator_color()
            colors = dialog.get_indicator_colors()
            if indicator_name:
                self.add_indicator_to_chart(indicator_name, params, color, colors)
    
    def on_edit_indicators(self):
        from .indicator_dialog import EditIndicatorsDialog
        
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        
        current_indicators = tab.get_indicators()
        if not current_indicators:
            QMessageBox.information(self, "Edit Indicators", "No indicators on current chart.")
            return
        
        dialog = EditIndicatorsDialog(current_indicators, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_indicators = dialog.get_indicators()
            self.redraw_all_indicators(new_indicators)
    
    def redraw_all_indicators(self, indicators):
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        
        asset = self.assets.get_asset(tab.symbol)
        if not asset:
            return
        
        df = asset.to_dataframe()
        
        tab.clear_indicators()
        
        for ind in indicators:
            indicator_name = ind['indicator_name']
            params = dict(ind.get('params', {}))
            color = ind.get('color', '#00BFFF')
            colors = ind.get('colors', {})
            visible = ind.get('visible', True)
            hlines = ind.get('hlines', [])
            if hlines:
                params['hlines'] = hlines
            
            indicator = IndicatorManager.calculate_indicator(indicator_name, df, params, colors=colors)
            if not indicator:
                continue
            
            indicator_type = ind['type']
            tab.add_indicator(indicator_name, indicator_type, params)
            tab.indicators[-1]['name'] = ind['name']
            tab.indicators[-1]['color'] = color
            tab.indicators[-1]['colors'] = colors
            tab.indicators[-1]['visible'] = visible
            tab.indicators[-1]['hlines'] = ind.get('hlines', [])
            
            if indicator_type == 'overlay':
                for line in indicator.lines:
                    tab.chart_view.add_indicator_line(line, visible=visible, unique_name=ind['name'])
                tab.chart_view.plot_candlesticks(df, tab.symbol)
            else:
                if visible:
                    tab.add_indicator_panel(indicator, df)
        
        self.database.save_chart_indicators(tab.symbol, tab.get_indicators())
    
    def add_indicator_to_chart(self, indicator_name: str, params: dict = None, color: str = None, colors: dict = None):
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        
        asset = self.assets.get_asset(tab.symbol)
        if not asset:
            return
        
        df = self._resolve_df(asset)
        
        params = params or {}
        indicator = IndicatorManager.calculate_indicator(indicator_name, df, params, colors=colors)
        
        if not indicator:
            return
        
        indicator_type = indicator.indicator_type
        tab.add_indicator(indicator_name, indicator_type, params or {})
        first_color = color if color else (list(colors.values())[0] if colors else '#00BFFF')
        tab.indicators[-1]['color'] = first_color
        tab.indicators[-1]['colors'] = colors if colors else {}
        tab.indicators[-1]['visible'] = True
        tab.indicators[-1]['hlines'] = [{'level': hl['level'], 'color': hl['color']} for hl in indicator.hlines]
        
        if indicator_type == Indicator.OVERLAY:
            for line in indicator.lines:
                tab.chart_view.add_indicator_line(line, visible=True, unique_name=tab.indicators[-1]['name'])
        else:
            tab.add_indicator_panel(indicator, df)
        
        self.database.save_chart_indicators(tab.symbol, tab.get_indicators())
    
    def on_clear_indicators(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.clear_indicators()
            tab.clear_indicator_panels()
    
    def zoom_in(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.zoom_in()
    
    def zoom_out(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.zoom_out()
    
    def reset_zoom(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.reset_zoom()
    
    def show_last_year(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.show_last_year()
    
    def on_toggle_crosshair(self, checked: bool):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.set_crosshair_enabled(checked)
    
    def on_chart_style(self, style):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.set_chart_style(style)
            for s, action in self.chart_style_actions.items():
                action.setChecked(s == style)

    def on_chart_tab_changed(self, index):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            style = tab.chart_view.chart_style
            for s, action in self.chart_style_actions.items():
                action.setChecked(s == style)
            self.limit_date_edit.setEnabled(tab.chart_view.df is not None)
            if tab.chart_view._limit_date is not None:
                self.limit_date_edit.setDate(QDate(tab.chart_view._limit_date.year, tab.chart_view._limit_date.month, tab.chart_view._limit_date.day))
            elif tab.chart_view._full_df is not None and len(tab.chart_view._full_df) > 0:
                last_date = tab.chart_view._full_df.index[-1]
                if hasattr(last_date, 'date'):
                    last_date = last_date.date()
                self.limit_date_edit.setDate(QDate(last_date.year, last_date.month, last_date.day))
        else:
            self.limit_date_edit.setEnabled(False)
    
    def on_indicator_panel_double_clicked(self, indicator_name: str):
        from .indicator_dialog import IndicatorDialog
        
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        
        ind = None
        for i in tab.indicators:
            if i.get('name') == indicator_name:
                ind = i
                break
        if not ind:
            return
        
        asset = self.assets.get_asset(tab.symbol)
        if not asset:
            return
        df = asset.to_dataframe()
        
        dialog = IndicatorDialog(self, existing_indicators=tab.get_indicators())
        indicator_name_key = ind.get('indicator_name', ind.get('name', ''))
        idx = dialog.type_combo.findText(indicator_name_key)
        if idx >= 0:
            dialog.type_combo.setCurrentIndex(idx)
        dialog.on_indicator_changed(indicator_name_key)
        
        if ind.get('colors'):
            dialog.line_colors = dict(ind['colors'])
            dialog._update_color_labels()
        elif ind.get('color'):
            line_defaults = IndicatorManager.LINE_DEFAULTS.get(indicator_name_key, [])
            if len(line_defaults) <= 1:
                dialog.line_colors = {}
            else:
                dialog.line_colors = {ld['name']: ind['color'] for ld in line_defaults}
            dialog._update_color_labels()
        
        for param_name, value in ind.get('params', {}).items():
            if param_name in dialog.param_widgets:
                dialog.param_widgets[param_name].setValue(value)
        
        saved_hlines = ind.get('hlines', [])
        if saved_hlines and dialog.hline_levels:
            for i_hl, hl in enumerate(saved_hlines):
                if i_hl < len(dialog.hline_levels):
                    dialog.hline_levels[i_hl]['level'].setValue(hl.get('level', 0))
                    dialog.hline_levels[i_hl]['color'] = hl.get('color', '#FF6B6B')
                    dialog.hline_levels[i_hl]['color_label'].setStyleSheet(
                        f"background-color: {hl.get('color', '#FF6B6B')}; border: 1px solid white;")
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_name = dialog.get_indicator_name()
            new_params = dialog.get_indicator_params()
            new_colors = dialog.get_indicator_colors()
            new_hlines = dialog.get_indicator_hlines()
            
            ind['indicator_name'] = new_name
            ind['params'] = new_params
            ind['color'] = dialog.get_indicator_color()
            ind['colors'] = new_colors
            ind['hlines'] = new_hlines
            
            params_with_hlines = dict(new_params)
            if new_hlines:
                params_with_hlines['hlines'] = new_hlines
            
            indicator = IndicatorManager.calculate_indicator(new_name, df, params_with_hlines, colors=new_colors)
            if indicator:
                ind['type'] = indicator.indicator_type
                ind['hlines'] = [{'level': hl['level'], 'color': hl['color']} for hl in indicator.hlines]
                
                tab.remove_indicator_panel(indicator_name)
                
                overlay_lines = [ol for ol in tab.chart_view.overlay_lines if ol.unique_name == ind['name']]
                tab.chart_view.overlay_lines = [ol for ol in tab.chart_view.overlay_lines if ol.unique_name != ind['name']]
                
                if indicator.indicator_type == Indicator.OVERLAY:
                    for line in indicator.lines:
                        tab.chart_view.add_indicator_line(line, visible=ind.get('visible', True), unique_name=ind['name'])
                else:
                    if ind.get('visible', True):
                        tab.add_indicator_panel(indicator, df)
                
                tab.chart_view.plot_candlesticks(df, tab.symbol)
            
            self.database.save_chart_indicators(tab.symbol, tab.get_indicators())
    
    def on_undo(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.undo()
    
    def on_toggle_draw_mode(self, checked: bool):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.draw_mode = checked
    
    def on_draw_mode_toggled(self, enabled: bool):
        self.draw_mode_action.setChecked(enabled)
    
    def on_drawing_double_clicked(self, drawing):
        from .drawing_dialog import DrawingSettingsDialog
        tab = self.chart_tabs.get_current_tab()
        if not tab:
            return
        tab.chart_view.push_undo()
        dialog = DrawingSettingsDialog(drawing, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.is_removed():
                if 'item' in drawing:
                    if drawing.get('type') == 'hline' and hasattr(drawing['item'], 'label'):
                        tab.chart_view.plot_widget.removeItem(drawing['item'].label)
                    tab.chart_view.plot_widget.removeItem(drawing['item'])
                tab.chart_view.drawings.remove(drawing)
            else:
                drawing['color'] = dialog.get_color()
                drawing['snap'] = dialog.get_snap()
                drawing['width'] = dialog.get_width()
                item = drawing['item']
                item.color = drawing['color']
                item.width = drawing['width']
                drawing_type = drawing.get('type', 'trendline')
                if drawing_type == 'hline':
                    new_y = dialog.get_y()
                    if new_y is not None:
                        drawing['points'][0] = (0, new_y)
                        item.setY(new_y)
                    item.setColor(drawing['color'])
                    tab.chart_view._update_hline_labels()
                elif drawing_type == 'vline':
                    new_bar = dialog.get_bar()
                    if new_bar is not None:
                        drawing['points'][0] = (new_bar, 0)
                        item.setX(new_bar)
                elif drawing_type in ('asc_channel', 'desc_channel'):
                    new_p1 = dialog.get_point1()
                    new_p2 = dialog.get_point2()
                    new_height = dialog.get_height()
                    new_middle_color = dialog.get_middle_color()
                    if new_p1 is not None and new_p2 is not None:
                        drawing['points'][0] = new_p1
                        drawing['points'][1] = new_p2
                    if new_height is not None and len(drawing['points']) >= 3:
                        drawing['points'][2] = (0, new_height)
                    if new_middle_color is not None:
                        drawing['middle_color'] = new_middle_color
                        item.middle_color = new_middle_color
                    item.setPoints(drawing['points'])
                    item.generatePicture()
                    item.update()
                    tab.chart_view.snap_drawing_points(drawing)
                else:
                    new_p1 = dialog.get_point1()
                    new_p2 = dialog.get_point2()
                    if new_p1 is not None and new_p2 is not None:
                        drawing['points'][0] = new_p1
                        drawing['points'][1] = new_p2
                        item.update_point(0, new_p1[0], new_p1[1])
                        item.update_point(1, new_p2[0], new_p2[1])
                    item.color = drawing['color']
                    item.width = drawing['width']
                    item.generatePicture()
                    item.update()
                    tab.chart_view.snap_drawing_points(drawing)
    
    def load_saved_symbols(self):
        symbols = self.database.get_symbols()
        for symbol in symbols:
            self.navigator.add_asset(symbol)
        spreads = self.database.load_spreads()
        for spread in spreads:
            self.navigator.add_spread(spread['name'])
    
    def save_session(self):
        open_tabs = self.chart_tabs.get_open_tabs()
        current_tab = self.chart_tabs.get_current_symbol_from_tabs()
        self.database.save_session(open_tabs, current_tab)
        
        settings = {}
        
        current_tab_obj = self.chart_tabs.get_current_tab()
        if current_tab_obj:
            settings['bull_color'] = current_tab_obj.chart_view.bull_color
            settings['bear_color'] = current_tab_obj.chart_view.bear_color
        
        main_splitter_state = self.main_splitter.saveState()
        settings['main_splitter_state'] = bytes(main_splitter_state.toBase64()).decode()
        
        for symbol in open_tabs:
            tab = self.chart_tabs.tabs.get(symbol)
            if tab:
                view_state = tab.get_view_state()
                indicators = tab.get_indicators()
                self.database.save_chart_view_state(symbol, {
                    'x_min': view_state.get('chart', {}).get('x_range', (0, 0))[0],
                    'x_max': view_state.get('chart', {}).get('x_range', (0, 0))[1],
                    'y_min': view_state.get('chart', {}).get('y_range', (0, 0))[0],
                    'y_max': view_state.get('chart', {}).get('y_range', (0, 0))[1]
                })
                self.database.save_chart_indicators(symbol, indicators)
                self.database.save_drawings(symbol, tab.chart_view.get_drawings())
                
                splitter_state = tab.splitter.saveState()
                settings[f'splitter_state_{symbol}'] = bytes(splitter_state.toBase64()).decode()
                
                self.database.save_chart_style(symbol, tab.chart_view.chart_style)
        
        self.database.save_settings(settings)
    
    def show_about(self):
        QMessageBox.about(
            self, 
            "About PyStalker",
            "PyStalker - Python/PyQt6 Stock Charting Tool\n\n"
            "A port of Qtstalker\n\n"
            "Features:\n"
            "- Candlestick charts\n"
            "- Multiple timeframes\n"
            "- Technical indicators (TALib)\n"
            "- Yahoo Finance data\n"
            "- CSV import\n"
            "- Data persistence with SQLite\n"
            "- Trendline drawing\n"
            "- Snap to OHLC values"
        )
    
    def on_draw_trendline(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            if not tab.chart_view.draw_mode:
                tab.chart_view.draw_mode = True
                self.draw_mode_action.setChecked(True)
            tab.chart_view.start_trendline_drawing()
            tab.chart_view.setFocus()
    
    def on_draw_hline(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.start_hline_drawing()
            tab.chart_view.setFocus()
    
    def on_draw_vline(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.start_vline_drawing()
            tab.chart_view.setFocus()
    
    def on_draw_asc_channel(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            if not tab.chart_view.draw_mode:
                tab.chart_view.draw_mode = True
                self.draw_mode_action.setChecked(True)
            tab.chart_view.start_asc_channel_drawing()
            tab.chart_view.setFocus()
    
    def on_draw_desc_channel(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            if not tab.chart_view.draw_mode:
                tab.chart_view.draw_mode = True
                self.draw_mode_action.setChecked(True)
            tab.chart_view.start_desc_channel_drawing()
            tab.chart_view.setFocus()
    
    def on_clear_drawings(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.push_undo()
            for drawing in tab.chart_view.drawings:
                if 'item' in drawing:
                    if drawing.get('type') == 'hline' and hasattr(drawing['item'], 'label'):
                        tab.chart_view.plot_widget.removeItem(drawing['item'].label)
                    tab.chart_view.plot_widget.removeItem(drawing['item'])
            tab.chart_view.drawings.clear()
            if tab.chart_view.preview_line is not None:
                tab.chart_view.plot_widget.removeItem(tab.chart_view.preview_line)
                tab.chart_view.preview_line = None
    
    def on_edit_drawings(self):
        from .drawing_dialog import EditDrawingsDialog
        tab = self.chart_tabs.get_current_tab()
        if not tab:
            return
        drawings = tab.chart_view.drawings
        if not drawings:
            QMessageBox.information(self, "Edit Drawings", "No drawings on current chart.")
            return
        dialog = EditDrawingsDialog(drawings, self)
        tab.chart_view.push_undo()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            for item in dialog.get_removed_items():
                if hasattr(item, 'label'):
                    tab.chart_view.plot_widget.removeItem(item.label)
                tab.chart_view.plot_widget.removeItem(item)
            
            for d in drawings:
                if 'item' in d and d.get('color'):
                    item_obj = d['item']
                    if d.get('type') == 'hline' and hasattr(item_obj, 'setColor'):
                        item_obj.setColor(d['color'])
                    else:
                        item_obj.color = d['color']
                    item_obj.width = d.get('width', 1)
                    if d.get('type') in ('asc_channel', 'desc_channel'):
                        if hasattr(item_obj, 'setPoints'):
                            item_obj.setPoints(d.get('points', []))
                        if d.get('middle_color'):
                            item_obj.middle_color = d['middle_color']
                    else:
                        item_obj.generatePicture()
                        item_obj.update()
                    tab.chart_view.snap_drawing_points(d)
            tab.chart_view._update_hline_labels()
    
    def restore_settings(self):
        settings = QSettings("PyStalker", "PyStalker")
        
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        
        state = settings.value("windowState")
        if state:
            self.restoreState(state)
    
    def closeEvent(self, event):
        self.save_session()
        self.database.close()
        
        settings = QSettings("PyStalker", "PyStalker")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("windowState", self.saveState())
        event.accept()


class TimeframeComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItems(BarData.BAR_LENGTHS)
        self.setCurrentText('1d')
        self.setMinimumWidth(60)