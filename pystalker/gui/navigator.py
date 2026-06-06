"""
PyStalker - Asset Navigator Panel with Spreads tab
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QTabWidget,
    QListWidget, QListWidgetItem, QPushButton, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction


class AssetNavigator(QWidget):
    asset_selected = pyqtSignal(str)
    spread_selected = pyqtSignal(str)
    spread_removed = pyqtSignal(str)
    copy_graph = pyqtSignal(str)
    rename_graph = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets = []
        self.spreads = []
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.tabs = QTabWidget()
        
        # Assets tab
        assets_widget = QWidget()
        assets_layout = QVBoxLayout(assets_widget)
        assets_layout.setContentsMargins(0, 0, 0, 0)
        
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter assets...")
        self.search_input.textChanged.connect(self.filter_assets)
        search_layout.addWidget(self.search_input)
        assets_layout.addLayout(search_layout)
        
        self.asset_list = QListWidget()
        self.asset_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.asset_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.asset_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.asset_list.customContextMenuRequested.connect(self.show_context_menu)
        assets_layout.addWidget(self.asset_list)
        
        button_layout = QHBoxLayout()
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.on_add_asset)
        button_layout.addWidget(add_button)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.on_remove_asset)
        button_layout.addWidget(remove_button)
        assets_layout.addLayout(button_layout)
        
        self.tabs.addTab(assets_widget, "Assets")
        
        # Spreads tab
        spreads_widget = QWidget()
        spreads_layout = QVBoxLayout(spreads_widget)
        spreads_layout.setContentsMargins(0, 0, 0, 0)
        
        self.spread_list = QListWidget()
        self.spread_list.itemDoubleClicked.connect(self.on_spread_double_clicked)
        self.spread_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.spread_list.customContextMenuRequested.connect(self.show_spread_context_menu)
        spreads_layout.addWidget(self.spread_list)
        
        spread_button_layout = QHBoxLayout()
        remove_spread_button = QPushButton("Remove")
        remove_spread_button.clicked.connect(self.on_remove_spread)
        spread_button_layout.addWidget(remove_spread_button)
        spreads_layout.addLayout(spread_button_layout)
        
        self.tabs.addTab(spreads_widget, "Spreads")
        
        layout.addWidget(self.tabs)
        
        self.copy_button = QPushButton("Copy Graph")
        self.copy_button.clicked.connect(self.on_copy_graph)
        layout.addWidget(self.copy_button)
        
        self.rename_button = QPushButton("Rename")
        self.rename_button.clicked.connect(self.on_rename_graph)
        layout.addWidget(self.rename_button)
    
    def add_asset(self, symbol: str):
        if symbol not in self.assets:
            self.assets.append(symbol)
            item = QListWidgetItem(symbol)
            self.asset_list.addItem(item)
    
    def get_assets(self) -> list:
        return self.assets
    
    def rename_asset(self, old_symbol: str, new_symbol: str):
        if old_symbol in self.assets:
            idx = self.assets.index(old_symbol)
            self.assets[idx] = new_symbol
            item = self.asset_list.item(idx)
            if item:
                item.setText(new_symbol)
    
    def filter_assets(self, pattern: str):
        pattern = pattern.lower()
        for i in range(self.asset_list.count()):
            item = self.asset_list.item(i)
            if pattern:
                item.setHidden(pattern not in item.text().lower())
            else:
                item.setHidden(False)
    
    def on_item_double_clicked(self, item: QListWidgetItem):
        self.asset_selected.emit(item.text())
    
    def on_selection_changed(self):
        selected = self.asset_list.selectedItems()
        if selected:
            self.asset_selected.emit(selected[0].text())
    
    def on_add_asset(self):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Add Asset", "Enter ticker symbol:")
        if ok and text:
            symbol = text.strip().upper()
            if symbol:
                self.add_asset(symbol)
                self.asset_selected.emit(symbol)
    
    def on_remove_asset(self):
        selected = self.asset_list.selectedItems()
        if selected:
            item = selected[0]
            symbol = item.text()
            self.assets.remove(symbol)
            self.asset_list.takeItem(self.asset_list.row(item))
    
    def show_context_menu(self, pos):
        item = self.asset_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(lambda: self.on_refresh(item.text()))
        menu.addAction(refresh_action)
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self.rename_graph.emit(item.text()))
        menu.addAction(rename_action)
        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(self.on_remove_asset)
        menu.addAction(remove_action)
        menu.exec(self.asset_list.mapToGlobal(pos))
    
    def on_refresh(self, symbol: str):
        self.asset_selected.emit(symbol)
    
    def on_copy_graph(self):
        selected = self.asset_list.selectedItems()
        if selected:
            self.copy_graph.emit(selected[0].text())
    
    def on_rename_graph(self):
        selected = self.asset_list.selectedItems()
        if selected:
            self.rename_graph.emit(selected[0].text())
    
    def add_spread(self, name: str):
        if name not in self.spreads:
            self.spreads.append(name)
            self.spread_list.addItem(QListWidgetItem(name))
    
    def remove_spread(self, name: str):
        if name in self.spreads:
            self.spreads.remove(name)
            for i in range(self.spread_list.count()):
                if self.spread_list.item(i).text() == name:
                    self.spread_list.takeItem(i)
                    break
    
    def on_spread_double_clicked(self, item: QListWidgetItem):
        self.spread_selected.emit(item.text())
    
    def on_remove_spread(self):
        selected = self.spread_list.selectedItems()
        if selected:
            item = selected[0]
            name = item.text()
            self.spreads.remove(name)
            self.spread_list.takeItem(self.spread_list.row(item))
            self.spread_removed.emit(name)
            return name
        return None
    
    def show_spread_context_menu(self, pos):
        item = self.spread_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        remove_action = QAction("Remove", self)
        remove_action.clicked.connect(self.on_remove_spread)
        menu.addAction(remove_action)
        menu.exec(self.spread_list.mapToGlobal(pos))