"""
PyStalker - Asset Navigator Panel
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
    QListWidget, QListWidgetItem, QPushButton, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QAction

class AssetNavigator(QWidget):
    asset_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.assets = []
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        search_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter assets...")
        self.search_input.textChanged.connect(self.filter_assets)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        self.asset_list = QListWidget()
        self.asset_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.asset_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.asset_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.asset_list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.asset_list)
        
        button_layout = QHBoxLayout()
        
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.on_add_asset)
        button_layout.addWidget(add_button)
        
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self.on_remove_asset)
        button_layout.addWidget(remove_button)
        
        layout.addLayout(button_layout)
    
    def add_asset(self, symbol: str):
        if symbol not in self.assets:
            self.assets.append(symbol)
            item = QListWidgetItem(symbol)
            self.asset_list.addItem(item)
    
    def get_assets(self) -> list:
        return self.assets
    
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
        
        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(self.on_remove_asset)
        menu.addAction(remove_action)
        
        menu.exec(self.asset_list.mapToGlobal(pos))
    
    def on_refresh(self, symbol: str):
        self.asset_selected.emit(symbol)