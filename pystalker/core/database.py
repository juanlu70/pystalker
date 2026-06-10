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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS spreads (
                name TEXT PRIMARY KEY,
                symbol1 TEXT NOT NULL,
                symbol2 TEXT NOT NULL,
                start_date TEXT NOT NULL
            )
        ''')
        
        self.conn.commit()
        
        self._migrate_old_schema()
        self._deduplicate_indicators()
        self._rename_ml_predict()
    
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
    
    def _deduplicate_indicators(self):
        import json
        cursor = self.conn.cursor()
        cursor.execute("SELECT symbol FROM symbols")
        symbols = [row[0] for row in cursor.fetchall()]
        for symbol in symbols:
            settings_table = f'"{symbol}_settings"'
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (f'{symbol}_settings',))
            if not cursor.fetchone():
                continue
            cursor.execute(f"SELECT value FROM {settings_table} WHERE key = ?", ('indicators',))
            row = cursor.fetchone()
            if not row:
                continue
            try:
                indicators = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(indicators, list):
                continue
            seen = set()
            unique = []
            for ind in indicators:
                name = ind.get('name', '')
                if name not in seen:
                    seen.add(name)
                    unique.append(ind)
            if len(unique) < len(indicators):
                cursor.execute(f'''
                    INSERT OR REPLACE INTO {settings_table} (key, value)
                    VALUES (?, ?)
                ''', ('indicators', json.dumps(unique)))
        self.conn.commit()
    
    def _rename_ml_predict(self):
        import json
        cursor = self.conn.cursor()
        all_tables = []
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for row in cursor.fetchall():
            all_tables.append(row[0])
        
        for table in all_tables:
            if not table.endswith('_settings'):
                continue
            cursor.execute(f'SELECT value FROM "{table}" WHERE key = ?', ('indicators',))
            row = cursor.fetchone()
            if not row:
                continue
            try:
                indicators = json.loads(row[0])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(indicators, list):
                continue
            
            changed = False
            for ind in indicators:
                if ind.get('indicator_name') == 'ML Predict' or ind.get('name') == 'ML Predict':
                    if 'indicator_name' in ind:
                        ind['indicator_name'] = 'ML Predict (Random Forest)'
                    if ind.get('name') == 'ML Predict':
                        ind['name'] = 'ML Predict (Random Forest)'
                    changed = True
            
            if changed:
                cursor.execute(f'''
                    INSERT OR REPLACE INTO "{table}" (key, value)
                    VALUES (?, ?)
                ''', ('indicators', json.dumps(indicators)))
        self.conn.commit()

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
                volume REAL,
                series2 REAL
            )
        ''')
        
        try:
            cursor.execute(f'ALTER TABLE {bars_table} ADD COLUMN series2 REAL')
        except sqlite3.OperationalError:
            pass
        
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {settings_table} (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        drawings_table = f'"{symbol}_drawings"'
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {drawings_table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                color TEXT NOT NULL,
                snap TEXT,
                params TEXT,
                points TEXT NOT NULL
            )
        ''')
        
        self.conn.commit()
    
    def save_bars(self, bar_data: BarData, interval: str = '1d'):
        symbol = bar_data.symbol
        if bar_data.source_symbol:
            self._ensure_symbol_tables(symbol)
            settings_table = f'"{symbol}_settings"'
            cursor = self.conn.cursor()
            cursor.execute(f'INSERT OR REPLACE INTO {settings_table} (key, value) VALUES (?, ?)',
                          ('source_symbol', bar_data.source_symbol))
            cursor.execute('''
                INSERT OR REPLACE INTO symbols (symbol, last_updated, interval)
                VALUES (?, ?, ?)
            ''', (symbol, int(datetime.now().timestamp()), interval))
            self.conn.commit()
            return
        self._ensure_symbol_tables(symbol)
        
        cursor = self.conn.cursor()
        
        bars_table = f'"{symbol}_bars"'
        cursor.execute(f'DELETE FROM {bars_table}')
        
        df = bar_data.to_dataframe()
        has_series2 = 'Series2' in df.columns
        series2_values = df['Series2'].values if has_series2 else None
        
        for i, bar in enumerate(bar_data.bars):
            if has_series2 and series2_values is not None and i < len(series2_values):
                cursor.execute(f'''
                    INSERT OR REPLACE INTO {bars_table}
                    (timestamp, open, high, low, close, volume, series2)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    int(bar.date.timestamp()),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    float(series2_values[i]) if series2_values[i] is not None and not (isinstance(series2_values[i], float) and pd.isna(series2_values[i])) else None
                ))
            else:
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
        
        if not bar_data.is_spread:
            cursor.execute('''
                INSERT OR REPLACE INTO symbols (symbol, last_updated, interval)
                VALUES (?, ?, ?)
            ''', (symbol, int(datetime.now().timestamp()), interval))
        
        self.conn.commit()
    
    def load_bars(self, symbol: str, interval: str = '1d') -> Optional[BarData]:
        self._ensure_symbol_tables(symbol)
        
        cursor = self.conn.cursor()
        
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f"SELECT value FROM {settings_table} WHERE key = ?", ('source_symbol',))
        row_src = cursor.fetchone()
        source_symbol = ''
        if row_src and row_src[0]:
            source_symbol = row_src[0]
            bar_data = BarData(symbol)
            bar_data.source_symbol = source_symbol
            cursor.execute(f'INSERT OR REPLACE INTO {settings_table} (key, value) VALUES (?, ?)',
                          ('source_symbol', source_symbol))
            self.conn.commit()
            return bar_data
        
        bars_table = f'"{symbol}_bars"'
        cursor.execute(f'PRAGMA table_info({bars_table})')
        columns = [row[1] for row in cursor.fetchall()]
        has_series2 = 'series2' in columns
        
        if has_series2:
            cursor.execute(f'''
                SELECT timestamp, open, high, low, close, volume, series2
                FROM {bars_table}
                ORDER BY timestamp ASC
            ''')
        else:
            cursor.execute(f'''
                SELECT timestamp, open, high, low, close, volume
                FROM {bars_table}
                ORDER BY timestamp ASC
            ''')
        
        rows = cursor.fetchall()
        
        if not rows:
            return None
        
        bar_data = BarData(symbol)
        bar_data.source_symbol = source_symbol
        series2_values = []
        
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
            if has_series2 and len(row) > 6 and row[6] is not None:
                series2_values.append(float(row[6]))
        
        if has_series2 and series2_values:
            df = bar_data.to_dataframe()
            n = min(len(series2_values), len(df))
            s2_arr = [float('nan')] * len(df)
            for i in range(n):
                s2_arr[i] = series2_values[i]
            df['Series2'] = s2_arr
            bar_data._df = df
            bar_data.is_spread = True
        
        if bar_data.is_spread:
            settings_table = f'"{symbol}_settings"'
            cursor.execute(f"SELECT value FROM {settings_table} WHERE key = ?", ('spread_lines',))
            row_s = cursor.fetchone()
            if row_s:
                import json
                info = json.loads(row_s[0])
                bar_data.spread_symbol1 = info.get('symbol1', '')
                bar_data.spread_symbol2 = info.get('symbol2', '')
                bar_data.spread_color1 = info.get('color1', '#00BFFF')
                bar_data.spread_color2 = info.get('color2', '#FF6B6B')
        
        return bar_data
    
    def get_symbols(self) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT symbol FROM symbols ORDER BY symbol')
        return [row[0] for row in cursor.fetchall()]
    
    def is_copy(self, symbol: str) -> bool:
        cursor = self.conn.cursor()
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f"SELECT value FROM {settings_table} WHERE key = ?", ('source_symbol',))
        row = cursor.fetchone()
        return row is not None and bool(row[0])
    
    def delete_symbol(self, symbol: str):
        cursor = self.conn.cursor()
        
        bars_table = f'"{symbol}_bars"'
        settings_table = f'"{symbol}_settings"'
        drawings_table = f'''"{symbol}_drawings"'''
        
        cursor.execute(f'DROP TABLE IF EXISTS {bars_table}')
        cursor.execute(f'DROP TABLE IF EXISTS {settings_table}')
        cursor.execute(f'DROP TABLE IF EXISTS {drawings_table}')
        cursor.execute('DELETE FROM symbols WHERE symbol = ?', (symbol,))
        
        self.conn.commit()
    
    def rename_symbol(self, old_symbol: str, new_symbol: str):
        cursor = self.conn.cursor()
        
        old_bars = f'{old_symbol}_bars'
        old_settings = f'{old_symbol}_settings'
        old_drawings = f'{old_symbol}_drawings'
        new_bars = f'{new_symbol}_bars'
        new_settings = f'{new_symbol}_settings'
        new_drawings = f'{new_symbol}_drawings'
        
        cursor.execute(f'ALTER TABLE "{old_bars}" RENAME TO "{new_bars}"')
        cursor.execute(f'ALTER TABLE "{old_settings}" RENAME TO "{new_settings}"')
        cursor.execute(f'ALTER TABLE "{old_drawings}" RENAME TO "{new_drawings}"')
        cursor.execute('UPDATE symbols SET symbol = ? WHERE symbol = ?', (new_symbol, old_symbol))
        
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
    
    def save_chart_style(self, symbol: str, style: str):
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f'''
            INSERT OR REPLACE INTO {settings_table} (key, value)
            VALUES (?, ?)
        ''', ('chart_style', style))
        self.conn.commit()

    def load_chart_style(self, symbol: str) -> str:
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f'SELECT value FROM {settings_table} WHERE key = ?', ('chart_style',))
        row = cursor.fetchone()
        return row[0] if row else 'candlestick'

    def save_setting(self, key: str, value: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
        ''', (key, value))
        self.conn.commit()
    
    def load_setting(self, key: str) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def save_settings(self, settings: dict):
        cursor = self.conn.cursor()
        for key, value in settings.items():
            cursor.execute('''
                INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)
            ''', (key, value))
        self.conn.commit()
    
    def load_settings(self, keys: list = None) -> dict:
        cursor = self.conn.cursor()
        if keys:
            placeholders = ','.join(['?'] * len(keys))
            cursor.execute(f'SELECT key, value FROM settings WHERE key IN ({placeholders})', keys)
        else:
            cursor.execute('SELECT key, value FROM settings')
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def save_drawings(self, symbol: str, drawings: list):
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        drawings_table = f'"{symbol}_drawings"'
        cursor.execute(f'DELETE FROM {drawings_table}')
        
        for drawing in drawings:
            import json
            params = dict(drawing.get('params', {}))
            params['width'] = drawing.get('width', 1)
            cursor.execute(f'''
                INSERT INTO {drawings_table} (type, color, snap, params, points)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                drawing.get('type', 'trendline'),
                drawing.get('color', '#FFD700'),
                drawing.get('snap', ''),
                json.dumps(params),
                json.dumps(drawing.get('points', []))
            ))
        
        self.conn.commit()
    
    def load_drawings(self, symbol: str) -> list:
        self._ensure_symbol_tables(symbol)
        cursor = self.conn.cursor()
        
        drawings_table = f'"{symbol}_drawings"'
        cursor.execute(f'SELECT type, color, snap, params, points FROM {drawings_table}')
        
        drawings = []
        for row in cursor.fetchall():
            import json
            params = json.loads(row[3]) if row[3] else {}
            width = params.pop('width', 1)
            drawings.append({
                'type': row[0],
                'color': row[1],
                'snap': row[2] if row[2] else '',
                'params': params,
                'points': json.loads(row[4]) if row[4] else [],
                'width': width
            })
        
        return drawings
    
    def save_spread(self, name: str, symbol1: str, symbol2: str, start_date: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO spreads (name, symbol1, symbol2, start_date)
            VALUES (?, ?, ?, ?)
        ''', (name, symbol1, symbol2, start_date))
        self.conn.commit()
    
    def load_spread(self, name: str) -> Optional[dict]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT name, symbol1, symbol2, start_date FROM spreads WHERE name = ?', (name,))
        row = cursor.fetchone()
        if row:
            return {'name': row[0], 'symbol1': row[1], 'symbol2': row[2], 'start_date': row[3]}
        return None
    
    def load_spreads(self) -> list:
        cursor = self.conn.cursor()
        cursor.execute('SELECT name, symbol1, symbol2, start_date FROM spreads ORDER BY name')
        return [{'name': row[0], 'symbol1': row[1], 'symbol2': row[2], 'start_date': row[3]} for row in cursor.fetchall()]
    
    def delete_spread(self, name: str):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM spreads WHERE name = ?', (name,))
        self.conn.commit()
    
    def save_spread_lines(self, symbol: str, symbol1: str, symbol2: str, color1: str, color2: str):
        self._ensure_symbol_tables(symbol)
        import json
        cursor = self.conn.cursor()
        settings_table = f'"{symbol}_settings"'
        cursor.execute(f'''
            INSERT OR REPLACE INTO {settings_table} (key, value)
            VALUES (?, ?)
        ''', ('spread_lines', json.dumps({
            'symbol1': symbol1,
            'symbol2': symbol2,
            'color1': color1,
            'color2': color2
        })))
        self.conn.commit()
    
    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None