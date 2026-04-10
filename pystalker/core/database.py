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
        
        self.conn.commit()
        
        self._migrate_old_schema()
    
    def _migrate_old_schema(self):
        cursor = self.conn.cursor()
        
        # Check if old 'bars' table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bars'")
        if cursor.fetchone():
            cursor.execute("SELECT DISTINCT symbol FROM bars")
            old_symbols = [row[0] for row in cursor.fetchall()]
            
            for symbol in old_symbols:
                self._ensure_symbol_tables(symbol)
                
                bars_table = f'"{symbol}_bars"'
                settings_table = f'"{symbol}_settings"'
                
                # Migrate bars
                cursor.execute(f'''
                    INSERT OR REPLACE INTO {bars_table} (timestamp, open, high, low, close, volume)
                    SELECT timestamp, open, high, low, close, volume
                    FROM bars WHERE symbol = ?
                ''', (symbol,))
                
                # Check for old indicators
                cursor.execute('''
                    SELECT name FROM sqlite_master WHERE type='table' AND name='chart_indicators'
                ''')
                if cursor.fetchone():
                    import json
                    cursor.execute('''
                        SELECT indicator_name, indicator_type, params, color, view_state
                        FROM chart_indicators WHERE symbol = ?
                    ''', (symbol,))
                    indicators = []
                    for row in cursor.fetchall():
                        indicators.append({
                            'name': row[0],
                            'indicator_name': row[0],
                            'type': row[1],
                            'params': json.loads(row[2]) if row[2] else {},
                            'color': row[3] if row[3] else '#00BFFF',
                            'view_state': json.loads(row[4]) if row[4] else {}
                        })
                    if indicators:
                        cursor.execute(f'''
                            INSERT OR REPLACE INTO {settings_table} (key, value) VALUES (?, ?)
                        ''', ('indicators', json.dumps(indicators)))
                
                # Check for old view state
                cursor.execute('''
                    SELECT name FROM sqlite_master WHERE type='table' AND name='chart_view_state'
                ''')
                if cursor.fetchone():
                    cursor.execute('''
                        SELECT x_range_min, x_range_max, y_range_min, y_range_max
                        FROM chart_view_state WHERE symbol = ?
                    ''', (symbol,))
                    row = cursor.fetchone()
                    if row:
                        import json
                        view_state = {
                            'x_min': row[0],
                            'x_max': row[1],
                            'y_min': row[2],
                            'y_max': row[3]
                        }
                        cursor.execute(f'''
                            INSERT OR REPLACE INTO {settings_table} (key, value) VALUES (?, ?)
                        ''', ('view_state', json.dumps(view_state)))
                
                # Check for old colors
                cursor.execute('''
                    SELECT name FROM sqlite_master WHERE type='table' AND name='chart_colors'
                ''')
                if cursor.fetchone():
                    cursor.execute('''
                        SELECT bull_color, bear_color FROM chart_colors WHERE symbol = ?
                    ''', (symbol,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute(f'''
                            INSERT OR REPLACE INTO {settings_table} (key, value) VALUES (?, ?)
                        ''', ('bull_color', row[0]))
                        cursor.execute(f'''
                            INSERT OR REPLACE INTO {settings_table} (key, value) VALUES (?, ?)
                        ''', ('bear_color', row[1]))
            
            # Drop old tables
            cursor.execute('DROP TABLE IF EXISTS bars')
            cursor.execute('DROP TABLE IF EXISTS chart_indicators')
            cursor.execute('DROP TABLE IF EXISTS chart_view_state')
            cursor.execute('DROP TABLE IF EXISTS chart_colors')
            
            self.conn.commit()
            print(f"Migrated {len(old_symbols)} symbols to new schema")
    
    def _ensure_symbol_tables(self, symbol: str):
        cursor = self.conn.cursor()
        
        bars_table = f'"{symbol}_bars"'
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {bars_table} (
                timestamp INTEGER PRIMARY KEY,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL
            )
        ''')
        
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {settings_table} (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        self.conn.commit()
    
    def save_bars(self, bar_data: BarData, interval: str = '1d'):
        symbol = bar_data.symbol
        self._ensure_symbol_tables(symbol)
        
        cursor = self.conn.cursor()
        
        bars_table = f'"{symbol}_bars"'
        cursor.execute(f'DELETE FROM {bars_table}')
        
        for bar in bar_data.bars:
            cursor.execute(f'''
                INSERT OR REPLACE INTO {bars_table}
                (timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                int(bar.date.timestamp()),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume
            ))
        
        cursor.execute('''
            INSERT OR REPLACE INTO symbols (symbol, last_updated, interval)
            VALUES (?, ?, ?)
        ''', (symbol, int(datetime.now().timestamp()), interval))
        
        self.conn.commit()
    
    def load_bars(self, symbol: str, interval: str = '1d') -> Optional[BarData]:
        self._ensure_symbol_tables(symbol)
        
        cursor = self.conn.cursor()
        
        bars_table = f'"{symbol}_bars"'
        cursor.execute(f'''
            SELECT timestamp, open, high, low, close, volume
            FROM {bars_table}
            ORDER BY timestamp ASC
        ''')
        
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
        
        bars_table = f'"{symbol}_bars"'
        settings_table = f'"{symbol}_settings"'
        
        cursor.execute(f'DROP TABLE IF EXISTS {bars_table}')
        cursor.execute(f'DROP TABLE IF EXISTS {settings_table}')
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
    
    def save_chart_colors(self, symbol: str, bull_color: str, bear_color: str):
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        import json
        
        cursor.execute(f'''
            INSERT OR REPLACE INTO {settings_table} (key, value)
            VALUES (?, ?)
        ''', ('bull_color', bull_color))
        
        cursor.execute(f'''
            INSERT OR REPLACE INTO {settings_table} (key, value)
            VALUES (?, ?)
        ''', ('bear_color', bear_color))
        
        self.conn.commit()
    
    def load_chart_colors(self, symbol: str) -> dict:
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        
        result = {}
        
        cursor.execute(f'SELECT value FROM {settings_table} WHERE key = ?', ('bull_color',))
        row = cursor.fetchone()
        if row:
            result['bull_color'] = row[0]
        
        cursor.execute(f'SELECT value FROM {settings_table} WHERE key = ?', ('bear_color',))
        row = cursor.fetchone()
        if row:
            result['bear_color'] = row[0]
        
        return result
    
    def save_chart_indicators(self, symbol: str, indicators: list):
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        import json
        
        indicators_json = json.dumps(indicators)
        cursor.execute(f'''
            INSERT OR REPLACE INTO {settings_table} (key, value)
            VALUES (?, ?)
        ''', ('indicators', indicators_json))
        
        self.conn.commit()
    
    def load_chart_indicators(self, symbol: str) -> list:
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        
        cursor.execute(f'SELECT value FROM {settings_table} WHERE key = ?', ('indicators',))
        row = cursor.fetchone()
        
        if row:
            import json
            return json.loads(row[0])
        
        return []
    
    def save_chart_view_state(self, symbol: str, view_state: dict):
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        import json
        
        view_state_json = json.dumps(view_state)
        cursor.execute(f'''
            INSERT OR REPLACE INTO {settings_table} (key, value)
            VALUES (?, ?)
        ''', ('view_state', view_state_json))
        
        self.conn.commit()
    
    def load_chart_view_state(self, symbol: str) -> dict:
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        
        cursor.execute(f'SELECT value FROM {settings_table} WHERE key = ?', ('view_state',))
        row = cursor.fetchone()
        
        if row:
            import json
            return json.loads(row[0])
        
        return {}
    
    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None