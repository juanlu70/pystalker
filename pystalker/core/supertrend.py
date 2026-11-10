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
  * OPEN BROKEN SUPERTREND CHANNEL: the open of the last bar is outside
    the Supertrend channel - beyond the Upper or the Lower line,
    whatever the candle's direction (up or down) - a separate event from
    the close-based ones: the open can break while the close does not,
    and the other way around.

The CHANNEL is the one the application's chart indicator draws: the
ACTIVE ratcheted line (the Lower support in an Up trend, the Upper
resistance in a Down trend) plus the freshly recomputed basic line on
the other side. The stale ratcheted band on the inactive side is NOT
part of the channel (it can sit far from the price); the close-based
TOUCHING and SURPASSED events only use the active line.
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


def load_bars(conn, symbol: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, int]:
    """(timestamps, opens, highs, lows, closes, n) of the asset's daily
    bars, in stored order."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT timestamp, open, high, low, close FROM "{symbol}_bars" '
                     f'ORDER BY timestamp')
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return (np.array([]), np.array([]), np.array([]),
                np.array([]), np.array([]), 0)
    if not rows:
        return (np.array([]), np.array([]), np.array([]),
                np.array([]), np.array([]), 0)
    data = np.array(rows, dtype=float)
    return data[:, 0], data[:, 1], data[:, 2], data[:, 3], data[:, 4], len(rows)


def supertrend(high, low, close, period=SUPERTREND_PERIOD,
               multiplier=SUPERTREND_MULTIPLIER):
    """The classic Supertrend series over the daily bars.

    Wilder's ATR (period), basic bands at hl2 +- multiplier * ATR, final
    bands that ratchet (the upper only falls, the lower only rises - each
    unless the previous close had crossed it), and the trend that rides the
    lower band (support, Up) or the upper band (resistance, Down), flipping
    exactly on the bar whose close crosses the current band - the classic
    Supertrend signal.

    Returns (direction, line, flip, lower_band, upper_band, basic_lower,
    basic_upper):
      direction    +1 (Up) / -1 (Down) per bar; 0 while the ATR warms up
      line         the ACTIVE band per bar (support in Up, resistance in Down)
      flip         True on the bar where the trend changed
      lower_band   the final lower band per bar (NaN in the warm-up)
      upper_band   the final upper band per bar (NaN in the warm-up)
      basic_lower  the freshly recomputed lower band (hl2 - m * ATR) per bar
      basic_upper  the freshly recomputed upper band (hl2 + m * ATR) per bar

    The Supertrend CHANNEL as the application's chart indicator draws it
    (the Upper and Lower lines on the chart) is the ACTIVE ratcheted line
    PLUS the basic recomputed line on the other side: in an Up trend the
    channel is [lower_band, basic_upper] (the support ratchets, the upper
    line follows the price), in a Down trend it is [basic_lower,
    upper_band]. The stale ratcheted band on the inactive side is NOT
    part of the channel.
    """
    n = len(close)
    direction = np.zeros(n, dtype=int)
    line = np.full(n, np.nan)
    flip = np.zeros(n, dtype=bool)
    lower_band = np.full(n, np.nan)
    upper_band = np.full(n, np.nan)
    basic_lower = np.full(n, np.nan)
    basic_upper = np.full(n, np.nan)
    if n < period + 2:
        return (direction, line, flip, lower_band, upper_band,
                basic_lower, basic_upper)

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
        basic_lower[t] = lb
        basic_upper[t] = ub
        line[t] = fl if d == 1 else fu
    return (direction, line, flip, lower_band, upper_band,
            basic_lower, basic_upper)


def evaluate_last_bar(direction, line, flip, lower_band, upper_band,
                      basic_lower, basic_upper, close,
                      max_proximity: float) -> Optional[Dict]:
    """Describe the last close against the active supertrend line.

    (The basic recomputed bands are accepted for the shared call
    signature; the close events only use the ACTIVE ratcheted band - a
    flip crosses the active line, not the channel.)

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


def evaluate_open_break(direction, line, flip, lower_band, upper_band,
                        basic_lower, basic_upper, opens, closes):
    """Describe the last bar's OPEN against the Supertrend channel AS THE
    APPLICATION'S CHART DRAWS IT: the OPEN BROKEN SUPERTREND CHANNEL event
    when the open is beyond the chart's Upper or Lower line, whatever the
    last candle's direction.

    The channel is the ACTIVE ratcheted line (the Lower support in an Up
    trend, the Upper resistance in a Down trend) plus the freshly
    recomputed basic line on the other side - exactly the Upper and Lower
    lines of the chart's supertrend indicator, NOT the stale ratcheted
    band (which can sit far from the price and would fire on opens the
    chart clearly shows inside the channel).

    Returns None (the open inside the channel, or still in the warm-up)
    or {'status': 'open_broken', 'line': 'Upper'/'Lower' (the broken
    line), 'line_value': its value, 'open': the open, 'beyond': the
    percentage beyond (relative to the line's value), 'candle':
    'Up'/'Down' (the last candle's direction: close vs open), 'age': the
    trend age in bars, 'close': the last close}."""
    t = len(opens) - 1
    if direction[t] == 0:
        return None                     # still in the warm-up
    # the chart's Upper and Lower lines at the last bar: the ACTIVE
    # ratcheted line + the freshly recomputed basic line on the other side
    if direction[t] == 1:
        channel_upper = basic_upper[t]   # follows the price above
        channel_lower = lower_band[t]    # the ratcheted support
    else:
        channel_upper = upper_band[t]    # the ratcheted resistance
        channel_lower = basic_lower[t]   # follows the price below
    if opens[t] > channel_upper:
        broken, value = 'Upper', channel_upper
    elif opens[t] < channel_lower:
        broken, value = 'Lower', channel_lower
    else:
        return None                     # the open is inside the range
    denom = abs(value)
    beyond = float(abs(opens[t] - value) / denom * 100.0) if denom > 1e-12 \
        else float('inf')
    # the trend age: bars since the last flip (like evaluate_last_bar)
    flips = np.nonzero(flip[:t])[0]
    if flips.size:
        age = int(t - flips[-1])
    else:
        age = int(t - np.argmax(direction != 0))
    return {'status': 'open_broken', 'line': broken,
            'line_value': float(value), 'open': float(opens[t]),
            'beyond': beyond,
            'candle': 'Up' if closes[t] >= opens[t] else 'Down',
            'age': age, 'close': float(closes[t])}


def scan_supertrend(conn, period: int = SUPERTREND_PERIOD,
                    multiplier: float = SUPERTREND_MULTIPLIER,
                    max_proximity: float = 10.0,
                    symbol: Optional[str] = None,
                    cutoff: Optional[float] = None) -> Dict:
    """Scan all assets for supertrend touches and breaks.

    cutoff scans a PAST DAY: only the bars strictly before this Unix
    timestamp, so the bands and all the events (touching, surpassed, the
    open break) are evaluated at that moment of the history;
    None = the whole history.

    Returns a dict:
      generated    report datetime (local time)
      scanned      number of assets with enough bars
      touching     [(symbol, evaluation, close)] sorted by proximity
      surpassed    [(symbol, evaluation, close)] sorted by symbol
      open_broken  [(symbol, evaluation, close)] - the OPEN BROKEN
                   SUPERTREND CHANNEL event: the last bar's open outside
                   the band range - sorted by symbol
      skipped      list of explanatory strings for unusable assets
    """
    results = {'generated': datetime.now().astimezone(),
                'scanned': 0, 'touching': [], 'surpassed': [],
                'open_broken': [], 'skipped': []}
    assets = get_assets(conn)
    if symbol:
        assets = [s for s in assets if s == symbol]

    for sym in assets:
        bars_symbol = get_source_symbol(conn, sym) or sym
        timestamps, opens, high, low, close, n_bars = load_bars(conn, bars_symbol)
        if cutoff is not None:
            keep = timestamps < cutoff
            opens, high, low, close = (opens[keep], high[keep],
                                       low[keep], close[keep])
            n_bars = len(close)
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
        if ev is not None:
            if ev['status'] == 'touching':
                results['touching'].append((sym, ev, ev['close']))
            else:
                results['surpassed'].append((sym, ev, ev['close']))
        # the open of the last bar vs the band range, whatever the candle's
        # direction (a separate event: the open can break while the close
        # does not, and the other way around)
        open_ev = evaluate_open_break(*series, opens, close)
        if open_ev is not None:
            results['open_broken'].append((sym, open_ev, open_ev['close']))

    results['touching'].sort(key=lambda r: r[1]['proximity'])
    results['surpassed'].sort(key=lambda r: (r[0], r[1]['line']))
    results['open_broken'].sort(key=lambda r: (r[0], r[1]['line']))
    return results


def scan_supertrend_history(conn, period: int = SUPERTREND_PERIOD,
                            multiplier: float = SUPERTREND_MULTIPLIER,
                            symbol: Optional[str] = None,
                            cutoff: Optional[float] = None) -> Dict:
    """Every HISTORICAL occurrence of the supertrend events of ONE asset
    (the scanner's --historical flag), one per episode:

      flips        the close crossed the line - a one-bar event (the trend
                   changed); the evaluation mirrors evaluate_last_bar's
                   surpassed dict (old_trend, trend, line, line_value,
                   beyond, close)
      open_broken  the open outside the Supertrend channel AS THE CHART
                   DRAWS IT (the active ratcheted line plus the basic
                   recomputed line on the other side) - the FIRST bar of
                   each stretch of opens beyond a line, since consecutive
                   opens can stay outside; the evaluation mirrors
                   evaluate_open_break's dict (line, line_value, open,
                   beyond, candle, age, close)

    Copies use their source asset's bars (like scan_supertrend); cutoff
    scans up to a past day (None = the whole history).

    Returns a dict:
      generated    report datetime (local time)
      flips        [(timestamp, evaluation, close)] chronological
      open_broken  [(timestamp, evaluation, close)] chronological
      skipped      explanatory strings (no price data, too few bars)
    """
    results = {'generated': datetime.now().astimezone(),
               'flips': [], 'open_broken': [], 'skipped': []}
    bars_symbol = get_source_symbol(conn, symbol) or symbol
    timestamps, opens, high, low, close, n_bars = load_bars(conn, bars_symbol)
    if cutoff is not None:
        keep = timestamps < cutoff
        timestamps, opens = timestamps[keep], opens[keep]
        high, low, close = high[keep], low[keep], close[keep]
        n_bars = len(close)
    if n_bars == 0:
        results['skipped'].append(f"{symbol}: no price data"
                                  + (f" (source {bars_symbol})"
                                     if bars_symbol != symbol else ""))
        return results
    if n_bars < period + 2:
        results['skipped'].append(f"{symbol}: {n_bars} bars "
                                  f"(< {period + 2} for period {period})")
        return results
    direction, line, flip, lower_band, upper_band, basic_lower, basic_upper = \
        supertrend(high, low, close, period, multiplier)
    prev_side = None            # the previous bar's open-break side (episodes)
    last_change = None          # the last flip (or the seeded first bar)
    for t in range(n_bars):
        if direction[t] == 0:
            continue            # still in the warm-up
        if last_change is None:
            last_change = t     # the seeded first bar (evaluate's fallback)
        # the trend age at this bar: bars since the last flip BEFORE this
        # bar - the established evaluate_last_bar/evaluate_open_break
        # convention (a flip bar itself counts from the previous flip)
        age = int(t - last_change)
        if flip[t]:
            old_dir = direction[t - 1]
            crossed = lower_band[t] if old_dir == 1 else upper_band[t]
            kind = 'Lower' if old_dir == 1 else 'Upper'
            denom = abs(crossed)
            beyond = float(abs(close[t] - crossed) / denom * 100.0) \
                if denom > 1e-12 else float('inf')
            results['flips'].append((timestamps[t],
                {'status': 'surpassed',
                 'trend': 'Up' if direction[t] > 0 else 'Down',
                 'old_trend': 'Up' if old_dir > 0 else 'Down',
                 'line': kind, 'line_value': float(crossed),
                 'beyond': beyond, 'age': 0, 'close': float(close[t])},
                float(close[t])))
            last_change = t
        # the open vs the chart's channel (the active ratcheted line plus
        # the basic recomputed line on the other side)
        if direction[t] == 1:
            channel_upper, channel_lower = basic_upper[t], lower_band[t]
        else:
            channel_upper, channel_lower = upper_band[t], basic_lower[t]
        if opens[t] > channel_upper:
            side, value = 'Upper', channel_upper
        elif opens[t] < channel_lower:
            side, value = 'Lower', channel_lower
        else:
            side = None
        # one occurrence per EPISODE: the first bar of each stretch of
        # opens beyond a line (the same side as the previous bar continues
        # the episode; the other side starts a new one)
        if side is not None and side != prev_side:
            denom = abs(value)
            beyond = float(abs(opens[t] - value) / denom * 100.0) \
                if denom > 1e-12 else float('inf')
            results['open_broken'].append((timestamps[t],
                {'status': 'open_broken', 'line': side,
                 'line_value': float(value), 'open': float(opens[t]),
                 'beyond': beyond,
                 'candle': 'Up' if close[t] >= opens[t] else 'Down',
                 'age': age, 'close': float(close[t])},
                float(close[t])))
        prev_side = side
    return results