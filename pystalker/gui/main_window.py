"""
PyStalker - Main Window
Porting of Qtstalker to Python/PyQt6
"""
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QMenuBar, QMenu, QToolBar, QStatusBar, QProgressBar,
    QMessageBox, QFileDialog, QComboBox, QLabel, QDialog, QInputDialog,
    QDialogButtonBox, QApplication
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QIcon

from .navigator import AssetNavigator
from .chart_view import ChartView
from .indicator_view import IndicatorView
from .chart_tab import ChartTabWidget
from ..core.data import BarData, ChartAssets
from ..core.providers import DataManager
from ..core.database import Database

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
        
        self.init_ui()
        self.load_saved_symbols()
        self.restore_session()
        self.restore_settings()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(main_splitter)
        
        self.navigator = AssetNavigator()
        self.navigator.setMinimumWidth(200)
        self.navigator.setMaximumWidth(400)
        self.navigator.asset_selected.connect(self.on_asset_selected)
        main_splitter.addWidget(self.navigator)
        
        self.chart_tabs = ChartTabWidget()
        self.chart_tabs.chart_closed.connect(self.on_chart_closed)
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
        
        import_csv = QAction(load_icon('import'), "Import CSV...", self)
        import_csv.triggered.connect(self.on_import_csv)
        file_menu.addAction(import_csv)
        
        file_menu.addSeparator()
        
        exit_action = QAction(load_icon('stop'), "E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
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
        
        clear_trendlines_action = QAction("Clear Trendlines", self)
        clear_trendlines_action.triggered.connect(self.on_clear_trendlines)
        draw_menu.addAction(clear_trendlines_action)
        
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
        
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction(load_icon('help'), "About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def init_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)
        
        download_action = QAction(load_icon('download'), "Download from Yahoo", self)
        download_action.setToolTip("Download stock data from Yahoo Finance")
        download_action.triggered.connect(self.on_open_chart)
        toolbar.addAction(download_action)
        
        toolbar.addSeparator()
        
        timeframe_label = toolbar.addWidget(QLabel())
        timeframe_label.setText("Timeframe: ")
        
        self.timeframe_combo = TimeframeComboBox()
        self.timeframe_combo.currentTextChanged.connect(self.on_timeframe_changed)
        toolbar.addWidget(self.timeframe_combo)
        
        toolbar.addSeparator()
        
        zoom_in = QAction(load_icon('up'), "Zoom In", toolbar)
        zoom_in.setToolTip("Zoom In")
        zoom_in.triggered.connect(self.zoom_in)
        toolbar.addAction(zoom_in)
        
        zoom_out = QAction(load_icon('prev'), "Zoom Out", toolbar)
        zoom_out.setToolTip("Zoom Out")
        zoom_out.triggered.connect(self.zoom_out)
        toolbar.addAction(zoom_out)
        
        reset_view = QAction(load_icon('home'), "Reset", toolbar)
        reset_view.setToolTip("Reset View")
        reset_view.triggered.connect(self.reset_zoom)
        toolbar.addAction(reset_view)
        
        toolbar.addSeparator()
        
        crosshair_action = QAction(load_icon('crosshair'), "Crosshair", toolbar)
        crosshair_action.setCheckable(True)
        crosshair_action.setChecked(True)
        crosshair_action.triggered.connect(self.on_toggle_crosshair)
        toolbar.addAction(crosshair_action)
    
    def on_open_chart(self):
        from PyQt6.QtWidgets import QInputDialog
        
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
        
        tab = self.chart_tabs.add_chart_tab(symbol, interval)
        tab.load_data(bar_data.to_dataframe(), symbol, interval)
        self.current_symbol = symbol
        
        self.status_bar.showMessage(f"Downloaded {symbol} ({bar_data.count()} bars)")
        self.save_session()
    
    def on_download_error(self, error_msg):
        if self.download_dialog and self.download_dialog.isVisible():
            self.download_dialog.reject()
        QMessageBox.critical(self, "Error", f"Failed to fetch data: {error_msg}")
        self.status_bar.showMessage("Download failed")
    
    def load_chart(self, symbol: str, interval: str = '1d'):
        from ..core.indicators import IndicatorManager
        
        asset = self.assets.get_asset(symbol)
        if not asset:
            cached_data = self.database.load_bars(symbol, interval)
            if cached_data:
                self.assets.add_asset(symbol, cached_data)
                asset = cached_data
        
        if not asset:
            return
        
        self.current_symbol = symbol
        df = asset.to_dataframe()
        
        tab = self.chart_tabs.add_chart_tab(symbol, interval)
        tab.load_data(df, symbol, interval)
        
        saved_indicators = self.database.load_chart_indicators(symbol)
        for ind in saved_indicators:
            indicator = IndicatorManager.calculate_indicator(ind['name'], df, ind.get('params'))
            if indicator:
                color = ind.get('color')
                tab.add_indicator(ind['name'], ind['type'], ind.get('params', {}))
                tab.indicators[-1]['color'] = color if color else '#00BFFF'
                if ind['type'] == 'overlay':
                    for line in indicator.lines:
                        if color:
                            line.color = color
                        tab.chart_view.add_indicator_line(line)
                else:
                    tab.indicator_view.add_indicator_panel(indicator, df)
        
        if saved_indicators:
            tab.chart_view.plot_candlesticks(df, symbol)
        
        view_state = self.database.load_chart_view_state(symbol)
        if view_state:
            tab.chart_view.set_view_state({
                'x_range': (view_state.get('x_min'), view_state.get('x_max')),
                'y_range': (view_state.get('y_min'), view_state.get('y_max'))
            })
        
        self.save_session()
    
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
    
    def on_chart_closed(self, symbol: str):
        self.save_session()
    
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
            if indicator_name:
                self.add_indicator_to_chart(indicator_name, params, color)
    
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
        from ..core.indicators import IndicatorManager
        
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        
        asset = self.assets.get_asset(tab.symbol)
        if not asset:
            return
        
        df = asset.to_dataframe()
        
        tab.clear_indicators()
        
        for ind in indicators:
            indicator_name = ind['name']
            params = ind.get('params', {})
            color = ind.get('color', '#00BFFF')
            
            indicator = IndicatorManager.calculate_indicator(indicator_name, df, params)
            if not indicator:
                continue
            
            indicator_type = ind['type']
            tab.add_indicator(indicator_name, indicator_type, params)
            tab.indicators[-1]['color'] = color
            
            if indicator_type == 'overlay':
                for line in indicator.lines:
                    line.color = color
                    tab.chart_view.add_indicator_line(line)
                tab.chart_view.plot_candlesticks(df, tab.symbol)
            else:
                tab.indicator_view.add_indicator_panel(indicator, df)
        
        self.database.save_chart_indicators(tab.symbol, tab.get_indicators())
    
    def add_indicator_to_chart(self, indicator_name: str, params: dict = None, color: str = None):
        from ..core.indicators import IndicatorManager, Indicator
        
        tab = self.chart_tabs.get_current_tab()
        if not tab or not tab.symbol:
            return
        
        asset = self.assets.get_asset(tab.symbol)
        if not asset:
            return
        
        df = asset.to_dataframe()
        indicator = IndicatorManager.calculate_indicator(indicator_name, df, params)
        
        if not indicator:
            return
        
        indicator_type = indicator.indicator_type
        tab.add_indicator(indicator_name, indicator_type, params or {})
        
        if color:
            tab.indicators[-1]['color'] = color
        
        if indicator_type == 'overlay':
            for line in indicator.lines:
                if color:
                    line.color = color
                tab.chart_view.add_indicator_line(line)
            tab.chart_view.plot_candlesticks(df, tab.symbol)
        else:
            if color and indicator.lines:
                indicator.lines[0].color = color
            tab.indicator_view.add_indicator_panel(indicator, df)
        
        self.database.save_chart_indicators(tab.symbol, tab.get_indicators())
    
    def on_indicator_added(self, indicator_name: str):
        self.add_indicator_to_chart(indicator_name)
    
    def on_indicator_removed(self, indicator_name: str):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.indicator_view.remove_indicator_panel(indicator_name)
    
    def on_clear_indicators(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.clear_indicators()
            tab.indicator_view.clear_all()
    
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
    
    def on_toggle_crosshair(self, checked: bool):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.set_crosshair_enabled(checked)
    
    def load_saved_symbols(self):
        symbols = self.database.get_symbols()
        for symbol in symbols:
            self.navigator.add_asset(symbol)
    
    def restore_session(self):
        open_tabs, current_tab = self.database.load_session()
        
        for symbol in open_tabs:
            cached_data = self.database.load_bars(symbol)
            if cached_data:
                self.assets.add_asset(symbol, cached_data)
                self.load_chart(symbol)
        
        if current_tab and current_tab in open_tabs:
            idx = list(open_tabs).index(current_tab)
            self.chart_tabs.setCurrentIndex(idx)
    
    def save_session(self):
        open_tabs = self.chart_tabs.get_open_tabs()
        current_tab = self.chart_tabs.get_current_symbol_from_tabs()
        self.database.save_session(open_tabs, current_tab)
        
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
            tab.chart_view.start_trendline_drawing()
            tab.chart_view.setFocus()
    
    def on_clear_trendlines(self):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            for tl in tab.chart_view.trend_lines:
                if 'item' in tl:
                    tab.chart_view.plot_widget.removeItem(tl['item'])
            tab.chart_view.trend_lines.clear()
            if tab.chart_view.preview_line is not None:
                tab.chart_view.plot_widget.removeItem(tab.chart_view.preview_line)
                tab.chart_view.preview_line = None
    
    def set_snap_mode(self, mode):
        tab = self.chart_tabs.get_current_tab()
        if tab:
            tab.chart_view.snap_mode = mode
            mode_text = f"Snap: {mode}" if mode else "Snap: None"
            tab.chart_view.info_label.setText(mode_text + " | O: -- H: -- L: -- C: --")
    
    def restore_settings(self):
        from PyQt6.QtCore import QSettings
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
        
        from PyQt6.QtCore import QSettings
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