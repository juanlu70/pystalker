"""
PyStalker - SQLite Database for storing chart data
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional, List
from pathlib import Path
import pandas as pd

from .data import Bar, BarData

class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            data_dir = Path.home() / '.pystalker'
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / 'pystalker.db')
        
        self.db_path = db_path
        self.conn = None
        self._init_db()
    
    def _init_db(self):
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                interval TEXT DEFAULT '1d',
                UNIQUE(symbol, timestamp, interval)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS symbols (
                symbol TEXT PRIMARY KEY,
                last_updated INTEGER,
                interval TEXT DEFAULT '1d'
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chart_indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                indicator_name TEXT NOT NULL,
                indicator_type TEXT NOT NULL,
                params TEXT,
                color TEXT,
                view_state TEXT,
                UNIQUE(symbol, indicator_name)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chart_view_state (
                symbol TEXT PRIMARY KEY,
                x_range_min REAL,
                x_range_max REAL,
                y_range_min REAL,
                y_range_max REAL
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_bars_symbol ON bars(symbol)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_bars_timestamp ON bars(timestamp)
        ''')
        
        self.conn.commit()
    
    def save_bars(self, bar_data: BarData, interval: str = '1d'):
        cursor = self.conn.cursor()
        
        cursor.execute('DELETE FROM bars WHERE symbol = ? AND interval = ?', 
                      (bar_data.symbol, interval))
        
        for bar in bar_data.bars:
            cursor.execute('''
                INSERT OR REPLACE INTO bars 
                (symbol, timestamp, open, high, low, close, volume, interval)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bar_data.symbol,
                int(bar.date.timestamp()),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
                interval
            ))
        
        cursor.execute('''
            INSERT OR REPLACE INTO symbols (symbol, last_updated, interval)
            VALUES (?, ?, ?)
        ''', (bar_data.symbol, int(datetime.now().timestamp()), interval))
        
        self.conn.commit()
    
    def load_bars(self, symbol: str, interval: str = '1d') -> Optional[BarData]:
        cursor = self.conn.cursor()
        
        cursor.execute('''
            SELECT timestamp, open, high, low, close, volume
            FROM bars
            WHERE symbol = ? AND interval = ?
            ORDER BY timestamp ASC
        ''', (symbol, interval))
        
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        bar_data = BarData(symbol)
        
        for row in rows:
            bar = Bar(
                date=datetime.fromtimestamp(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]) if row[5] else 0.0
            )
            bar_data.bars.append(bar)
        
        return bar_data
    
    def get_symbols(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT symbol FROM symbols ORDER BY symbol')
        return [row[0] for row in cursor.fetchall()]
    
    def delete_symbol(self, symbol: str):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM bars WHERE symbol = ?', (symbol,))
        cursor.execute('DELETE FROM symbols WHERE symbol = ?', (symbol,))
        self.conn.commit()
    
    def save_session(self, open_tabs: List[str], current_tab: str = None):
        cursor = self.conn.cursor()
        
        cursor.execute('DELETE FROM session WHERE key = ?', ('open_tabs',))
        if open_tabs:
            cursor.execute('INSERT INTO session (key, value) VALUES (?, ?)',
                          ('open_tabs', ','.join(open_tabs)))
        
        cursor.execute('DELETE FROM session WHERE key = ?', ('current_tab',))
        if current_tab:
            cursor.execute('INSERT INTO session (key, value) VALUES (?, ?)',
                          ('current_tab', current_tab))
        
        self.conn.commit()
    
    def load_session(self) -> tuple:
        cursor = self.conn.cursor()
        
        cursor.execute('SELECT value FROM session WHERE key = ?', ('open_tabs',))
        row = cursor.fetchone()
        open_tabs = row[0].split(',') if row and row[0] else []
        
        cursor.execute('SELECT value FROM session WHERE key = ?', ('current_tab',))
        row = cursor.fetchone()
        current_tab = row[0] if row else None
        
        return open_tabs, current_tab
    
    def save_chart_indicators(self, symbol: str, indicators: list):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM chart_indicators WHERE symbol = ?', (symbol,))
        
        for ind in indicators:
            import json
            cursor.execute('''
                INSERT INTO chart_indicators (symbol, indicator_name, indicator_type, params, color, view_state)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (symbol, ind['name'], ind['type'], json.dumps(ind.get('params', {})), 
                  ind.get('color', '#00BFFF'), json.dumps(ind.get('view_state', {}))))
        
        self.conn.commit()
    
    def load_chart_indicators(self, symbol: str) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT indicator_name, indicator_type, params, color, view_state
            FROM chart_indicators WHERE symbol = ?
        ''', (symbol,))
        
        import json
        indicators = []
        for row in cursor.fetchall():
            indicators.append({
                'name': row[0],
                'type': row[1],
                'params': json.loads(row[2]) if row[2] else {},
                'color': row[3] if row[3] else '#00BFFF',
                'view_state': json.loads(row[4]) if row[4] else {}
            })
        return indicators
    
    def save_chart_view_state(self, symbol: str, view_state: dict):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO chart_view_state (symbol, x_range_min, x_range_max, y_range_min, y_range_max)
            VALUES (?, ?, ?, ?, ?)
        ''', (symbol, view_state.get('x_min'), view_state.get('x_max'),
              view_state.get('y_min'), view_state.get('y_max')))
        self.conn.commit()
    
    def load_chart_view_state(self, symbol: str) -> dict:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT x_range_min, x_range_max, y_range_min, y_range_max
            FROM chart_view_state WHERE symbol = ?
        ''', (symbol,))
        
        row = cursor.fetchone()
        if row:
            return {
                'x_min': row[0],
                'x_max': row[1],
                'y_min': row[2],
                'y_max': row[3]
            }
        return {}
    
    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None