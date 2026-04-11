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
        
        self.splitter.setSizes([800, 0])
        self.indicator_view.hide()
        
        layout.addWidget(self.splitter)
        
        self.chart_view.range_changed.connect(self.on_chart_range_changed)
        self.indicator_view.range_changed.connect(self.on_indicator_range_changed)
        self.chart_view.colors_changed.connect(self.on_colors_changed)
        self.chart_view.indicator_visibility_changed.connect(self.on_indicator_visibility_changed)
        
        self.symbol = None
        self.interval = '1d'
        self.df = None
        self.indicators = []
        self._updating = False
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_splitter_visibility()
    
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
        unique_name = self._generate_unique_name(name)
        self.indicators.append({
            'name': unique_name,
            'indicator_name': name,
            'type': indicator_type,
            'params': params,
            'visible': True
        })
        self._update_splitter_visibility()
    
    def _generate_unique_name(self, base_name):
        existing_names = [ind.get('name', ind.get('indicator_name', '')) for ind in self.indicators]
        if base_name not in existing_names:
            return base_name
        
        counter = 1
        while f"{base_name}_{counter}" in existing_names:
            counter += 1
        return f"{base_name}_{counter}"
    
    def get_indicators(self):
        return self.indicators
    
    def update_overlay_visibility(self, name, visible):
        for ind in self.indicators:
            if ind.get('name') == name:
                ind['visible'] = visible
                break
    
    def clear_indicators(self):
        self.indicators.clear()
        self.chart_view.clear_indicators()
        self.indicator_view.clear_all()
        self._update_splitter_visibility()
    
    def _update_splitter_visibility(self):
        # Only show indicator panel if there are non-overlay (separate) indicators
        separate_indicators = [ind for ind in self.indicators if ind.get('type') != 'overlay']
        
        if len(separate_indicators) == 0:
            self.indicator_view.hide()
            self.splitter.setSizes([self.splitter.height(), 0])
        elif not self.indicator_view.isVisible():
            self.indicator_view.show()
            total_height = self.splitter.height()
            chart_height = int(total_height * 0.75)
            indicator_height = total_height - chart_height
            self.splitter.setSizes([chart_height, indicator_height])
    
    def on_colors_changed(self):
        pass
    
    def on_indicator_visibility_changed(self, unique_name: str, visible: bool):
        """Called when visibility is toggled from the chart legend"""
        # Update the indicators list
        for ind in self.indicators:
            if ind.get('name') == unique_name:
                ind['visible'] = visible
                break
        
        # Save to database
        if hasattr(self, 'symbol') and self.symbol:
            from ..core.database import Database
            db = Database()
            db.save_chart_indicators(self.symbol, self.indicators)
            db.close()
    
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
    colors_changed_global = pyqtSignal(str, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.tabCloseRequested.connect(self.on_tab_close)
        self.currentChanged.connect(self.on_current_changed)
        self.tabs = {}
    
    def on_current_changed(self, index):
        if index >= 0:
            tab = self.widget(index)
            if tab and not tab.isVisible():
                tab.show()
        self.current_changed.emit(index)
    
    def add_chart_tab(self, symbol: str, interval: str = '1d', set_current: bool = True) -> ChartTab:
        if symbol in self.tabs:
            tab = self.tabs[symbol]
            index = indexOf(tab)
            if set_current:
                self.setCurrentIndex(index)
            return tab
        
        tab = ChartTab()
        tab.chart_view.colors_changed.connect(
            lambda: self.colors_changed_global.emit(tab.chart_view.bull_color, tab.chart_view.bear_color)
        )
        self.tabs[symbol] = tab
        index = self.addTab(tab, symbol)
        if set_current:
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