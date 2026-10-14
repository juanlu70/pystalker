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

The scanning logic lives in pystalker/core/channel_scanner.py and is shared
with the Trading menu inside the application.

Usage:
  python channel_scanner.py
  python channel_scanner.py --max-proximity 5
  python channel_scanner.py --symbol BTC-USD
  python channel_scanner.py --db /path/to/pystalker.db
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pystalker.core.channel_scanner import scan_channel_proximity

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')


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
    res = scan_channel_proximity(conn, max_proximity=args.max_proximity, symbol=args.symbol)
    conn.close()

    near_results = res['near']
    broken_results = res['broken']
    skipped = res['skipped']
    scanned = res['scanned']

    print(f"Report generated: {res['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
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