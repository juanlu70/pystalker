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
  The CHANNEL column shows Ascending in green and Descending in red
  letters; the NEAR LINE column shows Upper in green and Lower in red.

  BROKEN: as a notification, assets whose last close has gone beyond a
  channel line (the channel is broken at the current price). The channel
  kind is colored like the CHANNEL column (Ascending in green,
  Descending in red) and the broken line phrase is colored like the
  NEAR LINE column ("beyond the upper line" in green, "beyond the
  lower line" in red).

  --lower-than <price> keeps only the assets whose last close is at that
  price or lower, in the whole report (near and broken sections).

Assets without channel drawings are discarded. Price data comes from the
daily bars of the asset (copies use their source asset's bars).

The scanning logic lives in pystalker/core/channel_scanner.py and is shared
with the Trading menu inside the application.

Usage:
  python pystalker_cli.py scanner                       (the unified program)
  python pystalker_cli.py scanner --max-proximity 5 --symbol BTC-USD
  python pystalker_cli.py scanner --lower-than 15
  python console_programs/channel_scanner.py --db /path/to/pystalker.db   (standalone)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.channel_scanner import scan_channel_proximity

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'


def colored(text, color, enabled=True):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    return f"{color}{text}{RESET}" if enabled else text


def build_parser(parser):
    """This tool's flags, shared by the standalone program and pystalker_cli.py."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--max-proximity', type=float, default=10.0,
                        help="maximum proximity percentage to report (default: 10)")
    parser.add_argument('--symbol', default=None, help="scan a single asset instead of all")
    parser.add_argument('--lower-than', type=float, default=None, metavar='PRICE',
                        help="keep only the assets whose last price is at this price or lower "
                             "(e.g. --lower-than 15)")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run(args):

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

    # --lower-than: keep only the cheap assets, in the whole report
    if args.lower_than is not None:
        near_results = [r for r in near_results if r[2] <= args.lower_than]
        broken_results = [r for r in broken_results if r[2] <= args.lower_than]

    use_color = not args.no_color
    price_filter = f" - price <= {args.lower_than:g}" if args.lower_than is not None else ""
    print(f"Report generated: {res['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Channel scanner - assets with price within {args.max_proximity:g}% of a channel"
          f" line{price_filter}")
    print(f"Scanned {scanned} asset(s) with channel drawings\n")

    if near_results:
        name_w = max(len(r[0]) for r in near_results)
        name_w = max(name_w, len('ASSET'))
        print(f"{'ASSET':<{name_w}}  {'CHANNEL':<11} {'NEAR LINE':<10} {'PROXIMITY':>9}  "
              f"{'LAST CLOSE':>12}  {'LINE VALUE':>12}")
        for symbol, ev, price in near_results:
            # pad first, colorize after: the f-string widths would count the
            # invisible ANSI escape characters otherwise
            channel = colored(f"{ev['kind']:<11}",
                             GREEN if ev['kind'] == 'Ascending' else RED, use_color)
            near_line = colored(f"{ev['near']:<10}",
                                GREEN if ev['near'] == 'Upper' else RED, use_color)
            print(f"{symbol:<{name_w}}  {channel} {near_line} "
                  f"{ev['proximity']:>8.2f}%  {price:>12.2f}  {ev['line_value']:>12.2f}")
        print(f"\n{len(near_results)} asset(s) near a channel line")
    else:
        print(f"No assets inside a channel within {args.max_proximity:g}% of a line"
              f"{price_filter}")

    if broken_results:
        print(f"\nBroken channels (price beyond a line):")
        for symbol, ev, price in broken_results:
            beyond = ev['beyond']
            beyond_s = f"{beyond:.2f}%" if beyond != float('inf') else "?"
            # Ascending channel in green, Descending channel in red;
            # "beyond the upper line" in green, "beyond the lower line" in red
            kind_s = colored(f"{ev['kind']} channel",
                             GREEN if ev['kind'] == 'Ascending' else RED, use_color)
            line_s = colored(f"beyond the {ev['broken_line'].lower()} line",
                              GREEN if ev['broken_line'] == 'Upper' else RED, use_color)
            print(f"  {symbol}: {kind_s} - price {price:.2f} is {line_s} "
                  f"({ev['line_value']:.2f}) by {beyond_s}")
        print(f"{len(broken_results)} broken channel(s)")

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Find assets whose price is near a drawn channel line (<= max proximity)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()