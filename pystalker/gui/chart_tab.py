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
        self.splitter.setChildrenCollapsible(False)
        
        self.chart_view = ChartView()
        self.splitter.addWidget(self.chart_view)
        
        layout.addWidget(self.splitter)
        
        self.chart_view.range_changed.connect(self.on_chart_range_changed)
        self.chart_view.colors_changed.connect(self.on_colors_changed)
        self.chart_view.indicator_visibility_changed.connect(self.on_indicator_visibility_changed)
        
        self.symbol = None
        self.interval = '1d'
        self.df = None
        self.indicators = []
        self._updating = False
        self._indicator_panels = {}
        self._indicator_connected = False
    
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
        for panel in self._indicator_panels.values():
            panel.update_view(left, right)
            if ticks:
                panel.update_ticks(ticks)
        self._updating = False
    
    def on_indicator_range_changed(self, left, right, ticks):
        if self._updating:
            return
        self._updating = True
        self.chart_view.update_view_range(left, right)
        for panel in self._indicator_panels.values():
            panel.update_view(left, right)
            if ticks:
                panel.update_ticks(ticks)
        self._updating = False
    
    def add_indicator_panel(self, indicator, df):
        from .indicator_view import IndicatorPanel
        panel = IndicatorPanel(indicator, df)
        panel.range_changed.connect(self.on_indicator_range_changed)
        self._indicator_panels[indicator.name] = panel
        self.splitter.addWidget(panel)
        self._distribute_splitter_sizes()
    
    def remove_indicator_panel(self, name):
        if name in self._indicator_panels:
            panel = self._indicator_panels[name]
            panel.range_changed.disconnect(self.on_indicator_range_changed)
            panel.setParent(None)
            panel.deleteLater()
            del self._indicator_panels[name]
            self._distribute_splitter_sizes()
    
    def clear_indicator_panels(self):
        for name in list(self._indicator_panels.keys()):
            self.remove_indicator_panel(name)
    
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
        self.clear_indicator_panels()
        self._update_splitter_visibility()
    
    def _distribute_splitter_sizes(self):
        n_panels = len(self._indicator_panels)
        total_height = self.splitter.height()
        if total_height == 0:
            total_height = 800
        if n_panels == 0:
            self.splitter.setSizes([total_height])
        else:
            chart_portion = 0.65
            indicator_portion = (1.0 - chart_portion) / n_panels
            chart_h = int(total_height * chart_portion)
            panel_h = int(total_height * indicator_portion)
            sizes = [chart_h] + [panel_h] * n_panels
            self.splitter.setSizes(sizes)
    
    def _update_splitter_visibility(self):
        separate_indicators = [ind for ind in self.indicators if ind.get('type') != 'overlay']
        if len(separate_indicators) == 0:
            self.clear_indicator_panels()
    
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
        panels_state = {}
        for name, panel in self._indicator_panels.items():
            panels_state[name] = panel.get_view_state()
        splitter_state = self.splitter.saveState().data().hex() if self.splitter.saveState().data() else ''
        return {
            'chart': chart_state,
            'indicators': panels_state,
            'splitter': splitter_state
        }
    
    def set_view_state(self, state):
        if state:
            if 'chart' in state:
                self.chart_view.set_view_state(state['chart'])
            if 'indicators' in state:
                for name, panel_state in state.get('indicators', {}).items():
                    if name in self._indicator_panels:
                        self._indicator_panels[name].set_view_state(panel_state)
            if 'splitter' in state and state['splitter']:
                from PyQt6.QtCore import QByteArray
                try:
                    ba = QByteArray.fromHex(bytes.fromhex(state['splitter']))
                    self.splitter.restoreState(ba)
                except Exception:
                    pass


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
                if tab.chart_view.df is not None and not tab.chart_view.df.empty:
                    tab.chart_view._apply_default_view()
                    tab.chart_view.update_date_ticks()
                    tab.chart_view.adjust_volume_height()
        self.current_changed.emit(index)
    
    def add_chart_tab(self, symbol: str, interval: str = '1d', set_current: bool = True) -> ChartTab:
        if symbol in self.tabs:
            tab = self.tabs[symbol]
            index = self.indexOf(tab)
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