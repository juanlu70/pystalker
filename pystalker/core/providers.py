"""
PyStalker - Data providers for downloading/importing market data
"""
import os
from datetime import datetime
from typing import Optional
import pandas as pd

from .data import Bar, BarData

class DataProvider:
    """Base class for data providers"""
    def __init__(self):
        pass
    
    def fetch(self, symbol: str, start_date: Optional[datetime] = None, 
              end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        raise NotImplementedError

class YahooFinanceProvider(DataProvider):
    """Yahoo Finance data provider using yfinance"""
    
    INTERVAL_MAP = {
        BarData.MINUTE_1: '1m',
        BarData.MINUTE_5: '5m',
        BarData.MINUTE_15: '15m',
        BarData.MINUTE_30: '30m',
        BarData.MINUTE_60: '60m',
        BarData.DAILY: '1d',
        BarData.WEEKLY: '1wk',
        BarData.MONTHLY: '1mo',
    }
    
    def __init__(self):
        super().__init__()
        try:
            import yfinance as yf
            self.yf = yf
        except ImportError:
            raise ImportError("yfinance is required. Install with: pip install yfinance")
    
    def fetch(self, symbol: str, start_date: Optional[datetime] = None,
              end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        yf_interval = self.INTERVAL_MAP.get(interval, '1d')
        
        ticker = self.yf.Ticker(symbol)
        
        if start_date and end_date:
            df = ticker.history(start=start_date, end=end_date, interval=yf_interval)
        elif start_date:
            df = ticker.history(start=start_date, interval=yf_interval)
        else:
            df = ticker.history(period='max', interval=yf_interval)
        
        bar_data = BarData(symbol)
        
        for index, row in df.iterrows():
            bar = Bar(
                date=index.to_pydatetime(),
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=float(row['Volume'])
            )
            bar_data.bars.append(bar)
        
        return bar_data

class CSVProvider(DataProvider):
    """CSV file data provider"""
    
    DEFAULT_COLUMNS = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    
    def __init__(self):
        super().__init__()
    
    def fetch(self, filepath: str, symbol: str = None, 
              date_format: str = None, delimiter: str = ',',
              columns: list = None) -> BarData:
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"CSV file not found: {filepath}")
        
        if symbol is None:
            symbol = os.path.splitext(os.path.basename(filepath))[0]
        
        if columns is None:
            columns = self.DEFAULT_COLUMNS
        
        df = pd.read_csv(filepath, delimiter=delimiter, low_memory=False)
        
        for i, col in enumerate(columns):
            if i >= len(df.columns):
                break
            if col:
                df.rename(columns={df.columns[i]: col}, inplace=True)
        
        if 'Date' not in df.columns:
            df.reset_index(inplace=True)
            if 'index' in df.columns:
                df.rename(columns={'index': 'Date'}, inplace=True)
        
        df['Date'] = pd.to_datetime(df['Date'], format=date_format, errors='coerce')
        df = df.dropna(subset=['Date'])
        df.set_index('Date', inplace=True)
        df.sort_index(inplace=True)
        
        bar_data = BarData(symbol)
        
        for index, row in df.iterrows():
            try:
                bar = Bar(
                    date=index.to_pydatetime(),
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=float(row['Volume']) if 'Volume' in row else 0.0
                )
                bar_data.bars.append(bar)
            except (ValueError, KeyError):
                continue
        
        return bar_data

class DataManager:
    """Manages multiple data providers and cached data"""
    
    def __init__(self):
        self.yahoo_provider = YahooFinanceProvider()
        self.csv_provider = CSVProvider()
        self.cache = {}
    
    def fetch_yahoo(self, symbol: str, start_date: Optional[datetime] = None,
                    end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        cache_key = f"yahoo:{symbol}:{interval}:{start_date}:{end_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        data = self.yahoo_provider.fetch(symbol, start_date, end_date, interval)
        self.cache[cache_key] = data
        return data
    
    def fetch_csv(self, filepath: str, symbol: str = None,
                  date_format: str = None, delimiter: str = ',',
                  columns: list = None) -> BarData:
        cache_key = f"csv:{filepath}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        data = self.csv_provider.fetch(filepath, symbol, date_format, delimiter, columns)
        self.cache[cache_key] = data
        return data
    
    def clear_cache(self):
        self.cache.clear()