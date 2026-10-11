#!/usr/bin/env python3
"""
channel_scanner.py - Find assets whose price is near a drawn channel line

Scans all assets (spreads are not stored as assets) in the pystalker
database, keeps the ones that have channel drawings (ascending/descending
channels), and reports:

  NEAR A LINE: assets whose last close is inside the channel and within
  --max-proximity (default 10%) of the lower or the upper channel line:
  the ticker, whether the channel is ascending or descending, which line
  the price is near (lower/upper), and the proximity percentage
  (distance of the price from the line, relative to the line's value).

  BROKEN: as a notification, assets whose last close has gone beyond a
  channel line (the channel is broken at the current price).

Assets without channel drawings are discarded. Price data comes from the
daily bars of the asset (copies use their source asset's bars).

Usage:
  python channel_scanner.py
  python channel_scanner.py --max-proximity 5
  python channel_scanner.py --symbol BTC-USD
  python channel_scanner.py --db /path/to/pystalker.db
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')
CHANNEL_TYPES = ('asc_channel', 'desc_channel')


def get_assets(conn):
    """All assets in the database (spreads are excluded from `symbols`)."""
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols ORDER BY symbol")
    return [r[0] for r in cur.fetchall()]


def get_source_symbol(conn, symbol):
    """Copies share the price data of their source asset."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT value FROM "{symbol}_settings" WHERE key = ?', ('source_symbol',))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def load_channels(conn, symbol):
    """Channel drawings of an asset.

    Returns a list of (type, b1x, b1y, b2x, b2y, height).
    """
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


def load_last_price(conn, symbol):
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


def evaluate_channel(channel, price, n_bars):
    """Describe the price vs one channel at the last bar.

    Returns a dict with status 'inside' (with near line + proximity) or
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
        return {'status': 'inside', 'kind': kind, 'near': near,
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


def main():
    parser = argparse.ArgumentParser(
        description="Find assets whose price is near a drawn channel line (<= max proximity)")
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--max-proximity', type=float, default=10.0,
                        help="maximum proximity percentage to report (default: 10)")
    parser.add_argument('--symbol', default=None, help="scan a single asset instead of all")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    assets = get_assets(conn)
    if args.symbol:
        assets = [s for s in assets if s == args.symbol]
        if not assets:
            print(f"Asset not found: {args.symbol}")
            sys.exit(1)

    near_results = []
    broken_results = []
    skipped = []
    scanned = 0

    for symbol in assets:
        channels = load_channels(conn, symbol)
        if not channels:
            continue  # discard assets without a drawn channel
        scanned += 1
        bars_symbol = get_source_symbol(conn, symbol) or symbol
        price, n_bars = load_last_price(conn, bars_symbol)
        if price is None or n_bars == 0:
            skipped.append(f"{symbol}: no price data"
                           + (f" (source {bars_symbol})" if bars_symbol != symbol else ""))
            continue
        for channel in channels:
            ev = evaluate_channel(channel, price, n_bars)
            if ev is None:
                continue
            if ev['status'] == 'inside':
                if ev['proximity'] <= args.max_proximity:
                    near_results.append((symbol, ev, price))
            else:
                broken_results.append((symbol, ev, price))
    conn.close()

    near_results.sort(key=lambda r: r[1]['proximity'])
    broken_results.sort(key=lambda r: (r[0], r[1]['broken_line']))

    now = datetime.now().astimezone()
    print(f"Report generated: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Channel scanner - assets with price within {args.max_proximity:g}% of a channel line")
    print(f"Scanned {scanned} asset(s) with channel drawings\n")

    if near_results:
        name_w = max(len(r[0]) for r in near_results)
        name_w = max(name_w, len('ASSET'))
        print(f"{'ASSET':<{name_w}}  {'CHANNEL':<11} {'NEAR LINE':<10} {'PROXIMITY':>9}  "
              f"{'LAST CLOSE':>12}  {'LINE VALUE':>12}")
        for symbol, ev, price in near_results:
            print(f"{symbol:<{name_w}}  {ev['kind']:<11} {ev['near']:<10} "
                  f"{ev['proximity']:>8.2f}%  {price:>12.2f}  {ev['line_value']:>12.2f}")
        print(f"\n{len(near_results)} asset(s) near a channel line")
    else:
        print(f"No assets inside a channel within {args.max_proximity:g}% of a line")

    if broken_results:
        print(f"\nBroken channels (price beyond a line):")
        for symbol, ev, price in broken_results:
            beyond = ev['beyond']
            beyond_s = f"{beyond:.2f}%" if beyond != float('inf') else "?"
            print(f"  {symbol}: {ev['kind']} channel - price {price:.2f} is beyond the "
                  f"{ev['broken_line'].lower()} line ({ev['line_value']:.2f}) by {beyond_s}")
        print(f"{len(broken_results)} broken channel(s)")

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


if __name__ == '__main__':
    main()