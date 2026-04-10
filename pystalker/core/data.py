"""
PyStalker - Core data structures
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
import pandas as pd

@dataclass
class Bar:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float = 0.0

class BarData:
    MINUTE_1 = '1m'
    MINUTE_5 = '5m'
    MINUTE_10 = '10m'
    MINUTE_15 = '15m'
    MINUTE_30 = '30m'
    MINUTE_60 = '60m'
    DAILY = '1d'
    WEEKLY = '1wk'
    MONTHLY = '1mo'
    
    BAR_LENGTHS = [
        MINUTE_1, MINUTE_5, MINUTE_10, MINUTE_15, 
        MINUTE_30, MINUTE_60, DAILY, WEEKLY, MONTHLY
    ]
    
    def __init__(self, symbol: str = ''):
        self.symbol = symbol
        self.bars: List[Bar] = []
        self._df: Optional[pd.DataFrame] = None
        
    def count(self) -> int:
        return len(self.bars)
    
    def get_high(self) -> float:
        if not self.bars:
            return 0.0
        return max(b.high for b in self.bars)
    
    def get_low(self) -> float:
        if not self.bars:
            return 0.0
        return min(b.low for b in self.bars)
    
    def to_dataframe(self) -> pd.DataFrame:
        if self._df is not None:
            return self._df
        
        data = []
        for bar in self.bars:
            data.append({
                'Date': bar.date,
                'Open': bar.open,
                'High': bar.high,
                'Low': bar.low,
                'Close': bar.close,
                'Volume': bar.volume
            })
        
        self._df = pd.DataFrame(data)
        if not self._df.empty:
            self._df.set_index('Date', inplace=True)
        return self._df
    
    def clear(self):
        self.bars = []
        self._df = None

class ChartAssets:
    def __init__(self):
        self.assets: dict = {}
    
    def add_asset(self, symbol: str, data: BarData):
        self.assets[symbol] = data
    
    def remove_asset(self, symbol: str):
        if symbol in self.assets:
            del self.assets[symbol]
    
    def get_asset(self, symbol: str) -> Optional[BarData]:
        return self.assets.get(symbol)
    
    def get_symbols(self) -> list:
        return list(self.assets.keys())