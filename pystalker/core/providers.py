"""
PyStalker - Data providers for downloading/importing market data
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional
import pandas as pd

from .data import Bar, BarData

# friendly display names for the Phemex asset categories (classify_product)
PHEMEX_CATEGORY_LABELS = {'perp': 'Perp', 'tradfi': 'TradFi',
                          'tokenized': 'Tokenized', 'crypto': 'Crypto'}


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
        
        # yfinance returns timezone-aware timestamps (exchange timezone), while
        # the app and its database work with tz-naive datetimes everywhere.
        # Normalize to naive local time so freshly downloaded data matches
        # data reloaded from the database and every date comparison works.
        if getattr(df.index, 'tz', None) is not None:
            try:
                df.index = df.index.tz_localize(None)
            except Exception:
                df.index = df.index.tz_convert(None)
        
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
        
        # CSV files may carry timezone-aware timestamps; normalize to tz-naive
        # like every other data source in the app
        if getattr(df.index, 'tz', None) is not None:
            try:
                df.index = df.index.tz_localize(None)
            except Exception:
                df.index = df.index.tz_convert(None)
        
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


class PhemexProvider(DataProvider):
    """Phemex exchange public market data.

    Uses the public (no API key) kline endpoint, which serves the perpetual
    contracts (legacy coin-margined BTCUSD... and the USDT/USDC-margined
    BTCUSDT, TSLAUSDT, NAS100USDT...), the spot pairs (sBTCUSDT...) and the
    tokenized assets (sTSLAONUSDT, sAAPLONUSDT...):

        GET /exchange/public/md/v2/kline/last?symbol=<symbol>&resolution=<resolution>&limit=<limit>

    Kline rows are [timestamp_seconds, interval, last_close, open, high, low,
    close, volume, turnover, symbol], newest first. The V2 hedged perps
    return human-readable unscaled prices; the legacy perps and spot pairs
    return integers scaled by the symbol's priceScale (from
    GET /public/products, fetched once and cached), and spot volumes are
    scaled by 10^8.

    The endpoint returns the most recent candles only (max limit 1000), so
    about 2.7 years of daily data are available per request.
    """
    BASE_URL = 'https://api.phemex.com'

    RESOLUTION_MAP = {
        BarData.MINUTE_1: 60,
        BarData.MINUTE_5: 300,
        BarData.MINUTE_15: 900,
        BarData.MINUTE_30: 1800,
        BarData.MINUTE_60: 3600,
        BarData.DAILY: 86400,
        BarData.WEEKLY: 604800,
        BarData.MONTHLY: 2592000,
    }

    def __init__(self):
        super().__init__()
        self._products = None
        self._currencies = None

    def _http_get(self, path: str) -> dict:
        url = self.BASE_URL + path
        req = urllib.request.Request(url, headers={'User-Agent': 'pystalker'})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            # try to surface Phemex's own error message from the response body
            try:
                body = e.read().decode('utf-8')
                detail = json.loads(body).get('msg') or body
            except Exception:
                detail = e.reason
            raise ValueError(f"Phemex request failed ({e.code}): {detail}") from e

    def _load_products_data(self, force: bool = False):
        if self._products is None or force:
            data = self._http_get('/public/products')
            products_data = data.get('data') or {}
            # the response splits the product registry in sections: `products`
            # holds the spot pairs and the legacy coin-margined perpetuals,
            # `perpProductsV2` holds the USDT/USDC-margined perpetual
            # contracts (BTCUSDT, TSLAUSDT, NAS100USDT...) - merge both
            self._products = (products_data.get('products') or []) + \
                (products_data.get('perpProductsV2') or [])
            currencies = products_data.get('currencies') or []
            self._currencies = {c.get('currency'): c for c in currencies if c.get('currency')}

    def get_products(self, force: bool = False) -> list:
        """All Phemex products (cached), as returned by GET /public/products."""
        self._load_products_data(force)
        return self._products

    def get_currencies(self, force: bool = False) -> dict:
        """All Phemex currencies (cached), as {currency symbol: record}."""
        self._load_products_data(force)
        return self._currencies

    def is_tokenized_asset(self, product: dict) -> bool:
        """True for spot pairs of tokenized real-world assets.

        These are Phemex's tokenized stocks/ETFs/commodities: the Ondo series
        (TSLAON, SPYON, QQQON, IAUON... whose currency name ends with
        "Ondo Tokenized") and the xStocks series (TSLAX, SPCXX... whose
        currency name contains "xStock").
        """
        if product.get('type') != 'Spot':
            return False
        currency = self.get_currencies().get(product.get('baseCurrency') or '')
        name = (currency.get('name') or '').lower() if currency else ''
        return 'tokenized' in name or 'xstock' in name

    def classify_product(self, product: dict) -> str:
        """The asset category: 'perp', 'tradfi', 'tokenized' or 'crypto'.

        perp: perpetual futures on crypto (legacy coin-margined contracts and
        the USDT/USDC-margined V2 perps). tradfi: V2 perp futures on
        traditional assets - tokenized stocks, indices, commodities and the
        pre-IPO/pre-market names. tokenized: spot pairs of tokenized
        real-world assets. crypto: the normal spot pairs.
        """
        ptype = product.get('type')
        if ptype == 'PerpetualV2':
            if product.get('perpProductSubType') in ('TradFi', 'PreMarket'):
                return 'tradfi'
            return 'perp'
        if ptype == 'Perpetual':
            return 'perp'
        if self.is_tokenized_asset(product):
            return 'tokenized'
        return 'crypto'

    def get_product_name(self, product: dict) -> str:
        """Human-readable name of the traded asset (its currency name)."""
        base = product.get('baseCurrency') or product.get('settleCurrency') or ''
        currency = self.get_currencies().get(base)
        return (currency.get('name') or '') if currency else ''

    def get_product(self, symbol: str) -> Optional[dict]:
        for p in self.get_products():
            if p.get('symbol') == symbol:
                return p
        return None

    def fetch(self, symbol: str, start_date: Optional[datetime] = None,
              end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        resolution = self.RESOLUTION_MAP.get(interval)
        if resolution is None:
            raise ValueError(f"Phemex does not support the {interval} interval "
                             f"(supported: 1m, 5m, 15m, 30m, 1h, 1d, 1wk, 1mo)")

        resp = self._http_get(
            f'/exchange/public/md/v2/kline/last?symbol={symbol}&resolution={resolution}&limit=1000')
        if resp.get('code') != 0:
            raise ValueError(f"Phemex error for {symbol}: {resp.get('msg')}")
        rows = (resp.get('data') or {}).get('rows') or []
        if not rows:
            raise ValueError(f"Phemex has no candles for {symbol} "
                             f"(the asset may be too new or have no trading activity yet)")

        product = self.get_product(symbol)
        ptype = (product or {}).get('type')
        # the V2 hedged perps (BTCUSDT...) return human-readable unscaled
        # prices; the legacy perps and the spot pairs return integers scaled
        # by the symbol's priceScale, and spot volumes are scaled by 10^8
        if ptype == 'PerpetualV2':
            price_scale = 1.0
            volume_scale = 1.0
        elif ptype == 'Spot':
            # every spot pair uses price scale 10^8
            price_scale = 10 ** int((product or {}).get('priceScale') or 8)
            volume_scale = 1e8
        else:  # legacy coin-margined perpetuals
            price_scale = 10 ** int((product or {}).get('priceScale') or 4)
            volume_scale = 1.0

        bar_data = BarData(symbol)
        for row in reversed(rows):  # newest first -> chronological
            ts, _interval, _last_close, o, h, l, c, vol, _turnover = row[:9]
            # kline timestamps are UTC; keep the candle's calendar date as the
            # app's canonical naive local midnight
            utc_dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            if start_date and utc_dt < start_date:
                continue
            if end_date and utc_dt > end_date:
                continue
            bar_data.bars.append(Bar(
                date=datetime(utc_dt.year, utc_dt.month, utc_dt.day),
                open=float(o) / price_scale,
                high=float(h) / price_scale,
                low=float(l) / price_scale,
                close=float(c) / price_scale,
                volume=float(vol) / volume_scale
            ))
        return bar_data


class PionexProvider(DataProvider):
    """Pionex exchange public market data.

    Uses the public (no API key) REST API - the same endpoint serves the spot
    pairs (BTC_USDT, AAPLX_USDT - including their xStocks tokenized assets)
    and the perpetual futures (BTC_USDT_PERP, TSLAX_USDT_PERP...):

        GET /api/v1/market/klines?symbol=<symbol>&interval=<interval>&limit=<limit>[&endTime=<ms>]

    Klines are {time: ms, open/close/high/low/volume: unscaled strings},
    newest first. Errors come back with HTTP 200 as
    {result: false, code, message}. The endpoint serves at most 500 klines
    per request, so fetch() pages back with endTime up to MAX_BARS (the
    documented limit is 10,000 records). The product lists come from
    GET /api/v1/common/symbols (spot) and ?type=PERP (perpetuals).

    Interval mapping: 1M/5M/15M/30M/60M/4H/8H/12H/1D (spot and perpetuals
    alike; weekly/monthly klines are rejected by the live API despite the
    docs). The daily interval starts at UTC 00:00.
    """
    BASE_URL = 'https://api.pionex.com'
    MAX_BARS = 10000

    INTERVAL_MAP = {
        BarData.MINUTE_1: '1M',
        BarData.MINUTE_5: '5M',
        BarData.MINUTE_15: '15M',
        BarData.MINUTE_30: '30M',
        BarData.MINUTE_60: '60M',
        BarData.DAILY: '1D',
    }

    def __init__(self):
        super().__init__()
        self._symbols = None

    def _http_get(self, path: str) -> dict:
        url = self.BASE_URL + path
        req = urllib.request.Request(url, headers={'User-Agent': 'pystalker'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        if payload.get('result') is False:
            raise ValueError(f"Pionex error ({payload.get('code')}): {payload.get('message')}")
        return payload

    def get_symbols(self, force: bool = False) -> list:
        """All Pionex products (cached): the spot pairs and the perpetual
        futures, each record with its type (SPOT/PERP) and enable flag."""
        if self._symbols is None or force:
            spot = (self._http_get('/api/v1/common/symbols').get('data') or {}).get('symbols') or []
            perp = (self._http_get('/api/v1/common/symbols?type=PERP').get('data') or {}).get('symbols') or []
            self._symbols = spot + perp
        return self._symbols

    def get_product(self, symbol: str) -> Optional[dict]:
        for product in self.get_symbols():
            if product.get('symbol') == symbol:
                return product
        return None

    def fetch(self, symbol: str, start_date: Optional[datetime] = None,
              end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        interval_code = self.INTERVAL_MAP.get(interval)
        if interval_code is None:
            raise ValueError(f"Pionex does not support the {interval} interval "
                             f"(supported: 1m, 5m, 15m, 30m, 1h, 1d)")

        rows = []
        seen_times = set()
        end_time = None
        while len(rows) < self.MAX_BARS:
            path = (f'/api/v1/market/klines?symbol={symbol}&interval={interval_code}'
                    f'&limit=500')
            if end_time is not None:
                path += f'&endTime={end_time}'
            klines = (self._http_get(path).get('data') or {}).get('klines') or []
            for kline in klines:
                t = kline.get('time')
                if t in seen_times:
                    continue
                seen_times.add(t)
                rows.append(kline)
            if len(klines) < 500:
                break
            end_time = klines[-1].get('time')
            time.sleep(0.12)   # stay within the 10 req/s public limit

        if not rows:
            raise ValueError(f"Pionex has no candles for {symbol} "
                             f"(the asset may be too new or have no trading activity yet)")

        bar_data = BarData(symbol)
        for kline in reversed(rows):  # newest first -> chronological
            # kline times are UTC milliseconds; keep the candle's calendar
            # date as the app's canonical naive local midnight
            utc_dt = datetime.fromtimestamp(kline['time'] / 1000, tz=timezone.utc)
            utc_dt = utc_dt.replace(tzinfo=None)
            if start_date and utc_dt < start_date:
                continue
            if end_date and utc_dt > end_date:
                continue
            bar_data.bars.append(Bar(
                date=datetime(utc_dt.year, utc_dt.month, utc_dt.day),
                open=float(kline['open']),
                high=float(kline['high']),
                low=float(kline['low']),
                close=float(kline['close']),
                volume=float(kline['volume'])
            ))
        return bar_data


class DataManager:
    """Manages multiple data providers and cached data"""
    
    def __init__(self):
        self.yahoo_provider = YahooFinanceProvider()
        self.csv_provider = CSVProvider()
        self.phemex_provider = PhemexProvider()
        self.pionex_provider = PionexProvider()
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
    
    def fetch_phemex(self, symbol: str, start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        cache_key = f"phemex:{symbol}:{interval}:{start_date}:{end_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        data = self.phemex_provider.fetch(symbol, start_date, end_date, interval)
        self.cache[cache_key] = data
        return data
    
    def fetch_pionex(self, symbol: str, start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None, interval: str = '1d') -> BarData:
        cache_key = f"pionex:{symbol}:{interval}:{start_date}:{end_date}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = self.pionex_provider.fetch(symbol, start_date, end_date, interval)
        self.cache[cache_key] = data
        return data

    def fetch_by_source(self, source: str, symbol: str, interval: str = '1d') -> BarData:
        """Fetch a symbol from the provider that serves it ('phemex', 'pionex';
        anything else means Yahoo Finance, the implicit default)."""
        if source == 'phemex':
            return self.fetch_phemex(symbol, interval=interval)
        if source == 'pionex':
            return self.fetch_pionex(symbol, interval=interval)
        return self.fetch_yahoo(symbol, interval=interval)

    def fetch_symbol(self, symbol: str, start_date: Optional[datetime] = None,
                     end_date: Optional[datetime] = None, interval: str = '1d'):
        """Fetch a symbol trying Yahoo Finance first, then Phemex, then Pionex.

        Exchange-only symbols (Pionex's BTC_USDT/BTC_USDT_PERP, Phemex's
        BTCUSDT/sTSLAONUSDT, tokenized stocks) fail on the other providers and
        are served by their exchange automatically. Returns (bar_data, source)
        with source 'yahoo', 'phemex' or 'pionex'.
        """
        errors = []
        for source, fetcher in (('yahoo', self.fetch_yahoo),
                                ('phemex', self.fetch_phemex),
                                ('pionex', self.fetch_pionex)):
            try:
                data = fetcher(symbol, start_date, end_date, interval)
                if data is not None and data.count() > 0:
                    return data, source
                errors.append(f"{source.capitalize()}: returned no data for {symbol}")
            except Exception as e:
                errors.append(f"{source.capitalize()}: {e}")
        raise ValueError(' | '.join(errors))
    
    def clear_cache(self):
        self.cache.clear()

