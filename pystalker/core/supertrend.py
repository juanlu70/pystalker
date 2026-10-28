"""
PyStalker - Supertrend core

The Supertrend indicator (defaults: ATR period 10, multiplier 1.8 - the
parameters the user chose) over the daily bars of an asset, and the scan
that reports the last close against the ACTIVE trend line:

  * TOUCHING: the close is within max_proximity % of the line (distance
    relative to the line's value, like the channel scanner) and still on
    the safe side of it - above the support (Up trend, the LOWER line)
    or below the resistance (Down trend, the UPPER line).
  * SURPASSED: the close crossed the line on the last bar. In the classic
    Supertrend the trend flips exactly at that bar, so the notification
    reports the flip ("the Up trend flipped Down - the close surpassed
    the lower line").

The inactive band is stale by construction and is not evaluated: the
active trend line is the one that matters for touches and breaks.
Copies use their source asset's bars (like the channel scanner).

Shared by the standalone supertrend.py CLI tool (and by the application
in the future, like the channel scanner).
"""
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

# the parameters the user chose as defaults
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 1.8


def get_assets(conn) -> List[str]:
    """All assets in the database (spreads are excluded from `symbols`)."""
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols ORDER BY symbol")
    return [r[0] for r in cur.fetchall()]


def get_source_symbol(conn, symbol: str) -> Optional[str]:
    """Copies share the price data of their source asset."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT value FROM "{symbol}_settings" WHERE key = ?',
                    ('source_symbol',))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def load_bars(conn, symbol: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """(highs, lows, closes, n) of the asset's daily bars, in stored order."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT high, low, close FROM "{symbol}_bars" '
                     f'ORDER BY timestamp')
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return np.array([]), np.array([]), np.array([]), 0
    if not rows:
        return np.array([]), np.array([]), np.array([]), 0
    data = np.array(rows, dtype=float)
    return data[:, 0], data[:, 1], data[:, 2], len(rows)


def supertrend(high, low, close, period=SUPERTREND_PERIOD,
               multiplier=SUPERTREND_MULTIPLIER):
    """The classic Supertrend series over the daily bars.

    Wilder's ATR (period), basic bands at hl2 +- multiplier * ATR, final
    bands that ratchet (the upper only falls, the lower only rises - each
    unless the previous close had crossed it), and the trend that rides the
    lower band (support, Up) or the upper band (resistance, Down), flipping
    exactly on the bar whose close crosses the current band - the classic
    Supertrend signal.

    Returns (direction, line, flip, lower_band, upper_band):
      direction   +1 (Up) / -1 (Down) per bar; 0 while the ATR warms up
      line        the ACTIVE band per bar (support in Up, resistance in Down)
      flip        True on the bar where the trend changed
      lower_band  the final lower band per bar (NaN in the warm-up)
      upper_band  the final upper band per bar (NaN in the warm-up)
    """
    n = len(close)
    direction = np.zeros(n, dtype=int)
    line = np.full(n, np.nan)
    flip = np.zeros(n, dtype=bool)
    lower_band = np.full(n, np.nan)
    upper_band = np.full(n, np.nan)
    if n < period + 2:
        return direction, line, flip, lower_band, upper_band

    # the true range and Wilder's ATR, seeded with the mean of the first
    # `period` true ranges
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close),
                            np.abs(low - prev_close)])
    atr = np.full(n, np.nan)
    atr[period - 1] = tr[:period].mean()
    for t in range(period, n):
        atr[t] = (atr[t - 1] * (period - 1) + tr[t]) / period

    hl2 = (high + low) / 2.0
    fu = fl = np.nan
    d = 0
    for t in range(period - 1, n):
        ub = hl2[t] + multiplier * atr[t]
        lb = hl2[t] - multiplier * atr[t]
        if d == 0:
            # the first bar with a valid ATR seeds the bands and the trend
            fu, fl = ub, lb
            d = 1 if close[t] > hl2[t] else -1
        else:
            # the final bands ratchet: the upper only falls, the lower only
            # rises - each unless the previous close had crossed it
            if ub < fu or close[t - 1] > fu:
                fu = ub
            if lb > fl or close[t - 1] < fl:
                fl = lb
            # the trend flips exactly on the bar whose close crosses the
            # current band
            if d == 1 and close[t] < fl:
                d, flip[t] = -1, True
            elif d == -1 and close[t] > fu:
                d, flip[t] = 1, True
        direction[t] = d
        lower_band[t] = fl
        upper_band[t] = fu
        line[t] = fl if d == 1 else fu
    return direction, line, flip, lower_band, upper_band


def evaluate_last_bar(direction, line, flip, lower_band, upper_band, close,
                      max_proximity: float) -> Optional[Dict]:
    """Describe the last close against the active supertrend line.

    Returns None (nothing to report), {'status': 'touching', ...} or
    {'status': 'surpassed', ...} with trend ('Up'/'Down'), the line kind
    ('Lower'/'Upper'), its value, the proximity or beyond percentage
    (relative to the line's value), and the trend age in bars."""
    t = len(close) - 1
    if direction[t] == 0:
        return None                     # still in the warm-up
    if flip[t]:
        # the close crossed the line on the last bar: the trend just flipped
        old_dir = direction[t - 1]
        new_dir = direction[t]
        crossed = lower_band[t] if old_dir == 1 else upper_band[t]
        kind = 'Lower' if old_dir == 1 else 'Upper'
        denom = abs(crossed)
        beyond = float(abs(close[t] - crossed) / denom * 100.0) if denom > 1e-12 \
            else float('inf')
        return {'status': 'surpassed', 'trend': 'Up' if new_dir > 0 else 'Down',
                'old_trend': 'Up' if old_dir > 0 else 'Down', 'line': kind,
                'line_value': float(crossed), 'beyond': beyond, 'age': 0,
                'close': float(close[t])}
    # the trend age: bars since the last flip (or since the seeded first bar)
    flips = np.nonzero(flip[:t])[0]
    if flips.size:
        age = int(t - flips[-1])
    else:
        age = int(t - np.argmax(direction != 0))
    kind = 'Lower' if direction[t] == 1 else 'Upper'
    value = line[t]
    denom = abs(value)
    proximity = float(abs(close[t] - value) / denom * 100.0) if denom > 1e-12 \
        else float('inf')
    if proximity > max_proximity:
        return None
    return {'status': 'touching', 'trend': 'Up' if direction[t] == 1 else 'Down',
            'line': kind, 'line_value': float(value), 'proximity': proximity,
            'age': age, 'close': float(close[t])}


def scan_supertrend(conn, period: int = SUPERTREND_PERIOD,
                    multiplier: float = SUPERTREND_MULTIPLIER,
                    max_proximity: float = 10.0,
                    symbol: Optional[str] = None) -> Dict:
    """Scan all assets for supertrend touches and breaks.

    Returns a dict:
      generated   report datetime (local time)
      scanned     number of assets with enough bars
      touching    [(symbol, evaluation, close)] sorted by proximity
      surpassed   [(symbol, evaluation, close)] sorted by symbol
      skipped     list of explanatory strings for unusable assets
    """
    results = {'generated': datetime.now().astimezone(),
               'scanned': 0, 'touching': [], 'surpassed': [], 'skipped': []}
    assets = get_assets(conn)
    if symbol:
        assets = [s for s in assets if s == symbol]

    for sym in assets:
        bars_symbol = get_source_symbol(conn, sym) or sym
        high, low, close, n_bars = load_bars(conn, bars_symbol)
        if n_bars == 0:
            results['skipped'].append(f"{sym}: no price data"
                                      + (f" (source {bars_symbol})"
                                         if bars_symbol != sym else ""))
            continue
        if n_bars < period + 2:
            results['skipped'].append(f"{sym}: {n_bars} bars "
                                      f"(< {period + 2} for period {period})")
            continue
        results['scanned'] += 1
        series = supertrend(high, low, close, period, multiplier)
        ev = evaluate_last_bar(*series, close, max_proximity)
        if ev is None:
            continue
        if ev['status'] == 'touching':
            results['touching'].append((sym, ev, ev['close']))
        else:
            results['surpassed'].append((sym, ev, ev['close']))

    results['touching'].sort(key=lambda r: r[1]['proximity'])
    results['surpassed'].sort(key=lambda r: (r[0], r[1]['line']))
    return results