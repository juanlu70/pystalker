"""
PyStalker - Chart Tab Widget for managing multiple chart tabs
"""
from PyQt6.QtWidgets import QTabWidget, QWidget, QVBoxLayout, QSplitter
from PyQt6.QtCore import pyqtSignal, Qt
from .chart_view import ChartView
from .indicator_view import IndicatorView


class ChartTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        
        self.chart_view = ChartView()
        self.splitter.addWidget(self.chart_view)
        
        self.indicator_view = IndicatorView()
        self.splitter.addWidget(self.indicator_view)
        
        self.splitter.setSizes([600, 200])
        
        layout.addWidget(self.splitter)
        
        self.chart_view.range_changed.connect(self.on_chart_range_changed)
        self.indicator_view.range_changed.connect(self.on_indicator_range_changed)
        
        self.symbol = None
        self.interval = '1d'
        self.df = None
        self.indicators = []
        self._updating = False
    
    def load_data(self, df, symbol, interval='1d'):
        self.symbol = symbol
        self.interval = interval
        self.df = df
        self.chart_view.plot_candlesticks(df, symbol)
    
    def on_chart_range_changed(self, left, right, ticks):
        if self._updating:
            return
        self._updating = True
        self.indicator_view.update_views(left, right)
        if ticks:
            self.indicator_view.update_ticks(ticks)
        self._updating = False
    
    def on_indicator_range_changed(self, left, right, ticks):
        if self._updating:
            return
        self._updating = True
        self.chart_view.update_view_range(left, right)
        self._updating = False
    
    def add_indicator(self, name, indicator_type, params):
        self.indicators.append({
            'name': name,
            'type': indicator_type,
            'params': params
        })
    
    def get_indicators(self):
        return self.indicators
    
    def clear_indicators(self):
        self.indicators.clear()
        self.chart_view.clear_indicators()
        self.indicator_view.clear_all()
    
    def get_view_state(self):
        chart_state = self.chart_view.get_view_state()
        indicators_state = self.indicator_view.get_panels_state()
        splitter_state = self.splitter.saveState()
        return {
            'chart': chart_state,
            'indicators': indicators_state,
            'splitter': splitter_state
        }
    
    def set_view_state(self, state):
        if state:
            if 'chart' in state:
                self.chart_view.set_view_state(state['chart'])
            if 'indicators' in state:
                self.indicator_view.set_panels_state(state['indicators'])
            if 'splitter' in state:
                self.splitter.restoreState(state['splitter'])


class ChartTabWidget(QTabWidget):
    chart_closed = pyqtSignal(str)
    current_changed = pyqtSignal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.on_tab_close)
        self.currentChanged.connect(self.on_current_changed)
        self.tabs = {}
    
    def add_chart_tab(self, symbol: str, interval: str = '1d') -> ChartTab:
        if symbol in self.tabs:
            tab = self.tabs[symbol]
            index = self.indexOf(tab)
            self.setCurrentIndex(index)
            return tab
        
        tab = ChartTab()
        self.tabs[symbol] = tab
        index = self.addTab(tab, symbol)
        self.setCurrentIndex(index)
        return tab
    
    def get_current_tab(self) -> ChartTab:
        index = self.currentIndex()
        if index >= 0:
            return self.widget(index)
        return None
    
    def get_current_symbol(self) -> str:
        tab = self.get_current_tab()
        if tab:
            return tab.symbol
        return None
    
    def on_tab_close(self, index):
        tab = self.widget(index)
        if tab and tab.symbol:
            symbol = tab.symbol
            del self.tabs[symbol]
            self.removeTab(index)
            self.chart_closed.emit(symbol)
    
    def on_current_changed(self, index):
        self.current_changed.emit(index)
    
    def get_open_tabs(self) -> list:
        return list(self.tabs.keys())
    
    def get_current_symbol_from_tabs(self) -> str:
        tab = self.get_current_tab()
        if tab:
            return tab.symbol
        return None