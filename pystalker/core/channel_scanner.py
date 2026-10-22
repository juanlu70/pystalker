"""
PyStalker - Channel proximity scanner core

Scans all assets (spreads are not stored as assets) in the database, keeps the
ones that have channel drawings, and evaluates the last close against every
channel's lines:

  * NEAR: the close is inside the channel and within max_proximity % of the
    lower or upper line (proximity = distance relative to the line's value).
  * BROKEN: the close is beyond a channel line (the channel is invalidated at
    the current price).
  * Assets without channel drawings are discarded; copies use their source
    asset's bars.

Shared by the standalone channel_scanner.py CLI tool and the Trading menu
inside the application.
"""
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple

DB_DEFAULT_CANDIDATE = None  # kept for documentation; connections are passed in

CHANNEL_TYPES = ('asc_channel', 'desc_channel')


def get_assets(conn) -> List[str]:
    """All assets in the database (spreads are excluded from `symbols`)."""
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols ORDER BY symbol")
    return [r[0] for r in cur.fetchall()]


def get_source_symbol(conn, symbol: str) -> Optional[str]:
    """Copies share the price data of their source asset."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT value FROM "{symbol}_settings" WHERE key = ?', ('source_symbol',))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def load_channels(conn, symbol: str):
    """Channel drawings of an asset: [(type, b1x, b1y, b2x, b2y, height)]."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT type, points FROM "{symbol}_drawings"')
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return []  # no drawings table
    channels = []
    for dtype, points_json in rows:
        if dtype not in CHANNEL_TYPES:
            continue
        try:
            points = json.loads(points_json) if isinstance(points_json, str) else points_json
        except (TypeError, ValueError):
            continue
        if not isinstance(points, list) or len(points) < 3:
            continue
        try:
            b1x, b1y = points[0]
            b2x, b2y = points[1]
            height = points[2][1]
        except (TypeError, ValueError, IndexError):
            continue
        try:
            b1x, b1y, b2x, b2y, height = float(b1x), float(b1y), float(b2x), float(b2y), float(height)
        except (TypeError, ValueError):
            continue
        if b2x == b1x:
            continue  # degenerate channel
        channels.append((dtype, b1x, b1y, b2x, b2y, height))
    return channels


def load_last_price(conn, symbol: str):
    """(last_close, n_bars) of the asset's daily bars."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{symbol}_bars"')
        n = cur.fetchone()[0]
        if n == 0:
            return None, 0
        cur.execute(f'SELECT close FROM "{symbol}_bars" ORDER BY timestamp DESC LIMIT 1')
        row = cur.fetchone()
        return (float(row[0]) if row else None), n
    except sqlite3.OperationalError:
        return None, 0


def evaluate_channel(channel, price: float, n_bars: int) -> Optional[Dict]:
    """Describe the price vs one channel at the last bar.

    Returns a dict with status 'near' (with near line + proximity) or
    'broken' (with which line was broken and how far beyond).
    """
    dtype, b1x, b1y, b2x, b2y, height = channel
    p = n_bars - 1
    slope = (b2y - b1y) / (b2x - b1x)
    base = b1y + slope * (p - b1x)
    if height >= 0:
        lower, upper = base, base + height
    else:
        upper, lower = base, base + height
    kind = 'Ascending' if dtype == 'asc_channel' else 'Descending'

    def pct(line_value):
        if abs(line_value) < 1e-12:
            return None
        return abs(price - line_value) / abs(line_value) * 100.0

    if lower <= price <= upper:
        candidates = []
        d_lower = pct(lower)
        d_upper = pct(upper)
        if d_lower is not None:
            candidates.append((d_lower, 'Lower', lower))
        if d_upper is not None:
            candidates.append((d_upper, 'Upper', upper))
        if not candidates:
            return None
        proximity, near, line_value = min(candidates, key=lambda c: c[0])
        return {'status': 'near', 'kind': kind, 'near': near,
                'proximity': proximity, 'line_value': line_value,
                'lower': lower, 'upper': upper}
    # price beyond a line: broken channel
    if price > upper:
        broken, line_value = 'Upper', upper
    else:
        broken, line_value = 'Lower', lower
    beyond = pct(line_value)
    return {'status': 'broken', 'kind': kind, 'broken_line': broken,
            'beyond': beyond if beyond is not None else float('inf'),
            'line_value': line_value, 'lower': lower, 'upper': upper}


def scan_channel_proximity(conn, max_proximity: float = 10.0,
                           symbol: Optional[str] = None,
                           lower_than: Optional[float] = None) -> Dict:
    """Scan all assets for channels near the price.

    lower_than keeps only the assets whose last close is at that price or
    lower (None = all prices), in both the near and the broken sections -
    the --lower-than flag of the console scanner and the 'Lower than'
    input of the application's dialog.

    Returns a dict:
      generated   report datetime (local time)
      scanned     number of assets with channel drawings
      near        [(symbol, evaluation, price)] sorted by proximity
      broken      [(symbol, evaluation, price)] sorted by symbol
      skipped     list of explanatory strings for unusable assets
    """
    results = {'generated': datetime.now().astimezone(),
               'scanned': 0, 'near': [], 'broken': [], 'skipped': []}

    assets = get_assets(conn)
    if symbol:
        assets = [s for s in assets if s == symbol]

    for sym in assets:
        channels = load_channels(conn, sym)
        if not channels:
            continue  # discard assets without a drawn channel
        results['scanned'] += 1
        bars_symbol = get_source_symbol(conn, sym) or sym
        price, n_bars = load_last_price(conn, bars_symbol)
        if price is None or n_bars == 0:
            results['skipped'].append(f"{sym}: no price data"
                                       + (f" (source {bars_symbol})" if bars_symbol != sym else ""))
            continue
        for channel in channels:
            ev = evaluate_channel(channel, price, n_bars)
            if ev is None:
                continue
            if ev['status'] == 'near':
                if ev['proximity'] <= max_proximity:
                    results['near'].append((sym, ev, price))
            else:
                results['broken'].append((sym, ev, price))

    # --lower-than: keep only the cheap assets, in both sections
    if lower_than is not None:
        results['near'] = [r for r in results['near'] if r[2] <= lower_than]
        results['broken'] = [r for r in results['broken'] if r[2] <= lower_than]

    results['near'].sort(key=lambda r: r[1]['proximity'])
    results['broken'].sort(key=lambda r: (r[0], r[1]['broken_line']))
    return results