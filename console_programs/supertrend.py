#!/usr/bin/env python3
"""
supertrend.py - Find assets whose close is touching a supertrend line

Scans all assets (spreads are not stored as assets) in the pystalker
database, computes the Supertrend indicator (defaults: ATR period 10,
multiplier 1.8 - the parameters chosen for the project; --period and
--multiplier change them per run) over each one's daily bars, and reports
the last close against the ACTIVE trend line:

  TOUCHING: assets whose last close is within --max-proximity (default
  10%, like the channel scanner) of the line and still on the safe side
  of it - above the support (Up trend, the LOWER line, green) or below
  the resistance (Down trend, the UPPER line, red). The columns: the
  ticker (its personalized display name when the asset has one, like the
  Operations list), the trend (Up in green, Down in red), the line
  (Lower in red, Upper in green, like the channel scanner), the trend
  age in bars, the proximity percentage (distance relative to the
  line's value), the last close and the line value.

  SURPASSED: as a notification, assets whose last close crossed the
  line on the last bar - in the classic Supertrend the trend flips
  exactly then, so the notification reports the flip: "the Up trend
  flipped Down - the close X surpassed the lower line (Y) by Z%"
  ("surpassed the upper line" in green, "surpassed the lower line" in
  red, like the channel scanner's broken-line phrases).

Assets without enough bars for the indicator's warm-up are skipped with
the reason. Copies use their source asset's bars.

The scanning logic lives in pystalker/core/supertrend.py (shared with
the application, like the channel scanner's).

Usage:
  python pystalker_cli.py supertrend                       (the unified program)
  python pystalker_cli.py supertrend --max-proximity 5 --symbol BTC-USD
  python pystalker_cli.py supertrend --period 10 --multiplier 3
  python console_programs/supertrend.py --db /path/to/pystalker.db   (standalone)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                        scan_supertrend)
from pystalker.core.operations import get_display_name

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
    parser.add_argument('--period', type=int, default=SUPERTREND_PERIOD,
                        help=f"the ATR period of the supertrend (default: {SUPERTREND_PERIOD})")
    parser.add_argument('--multiplier', type=float, default=SUPERTREND_MULTIPLIER,
                        help=f"the supertrend multiplier (default: {SUPERTREND_MULTIPLIER:g})")
    parser.add_argument('--max-proximity', type=float, default=10.0,
                        help="maximum proximity percentage to report as touching (default: 10)")
    parser.add_argument('--symbol', default=None, help="scan a single asset instead of all")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run(args):

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    res = scan_supertrend(conn, period=args.period, multiplier=args.multiplier,
                          max_proximity=args.max_proximity, symbol=args.symbol)
    names = resolve_names(conn, res)
    conn.close()
    print_supertrend_report(res, names, args)


def resolve_names(conn, res):
    """The personalized display names of the listed assets (like Operations);
    resolved while the connection is still open."""
    names = {}
    for sym, _, _ in res['touching'] + res['surpassed']:
        names[sym] = get_display_name(conn, sym) or sym
    return names


def print_supertrend_report(res, names, args):
    """The supertrend scanner's report - shared by this standalone program
    and the fused scanner (console_programs/scanner.py, the
    pystalker_cli.py 'scanner' command)."""
    touching = res['touching']
    surpassed = res['surpassed']
    skipped = res['skipped']
    scanned = res['scanned']

    use_color = not args.no_color
    print(f"Report generated: {res['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Supertrend - assets with the close within {args.max_proximity:g}% "
          f"of the supertrend line or beyond it")
    print(f"Parameters: period {args.period}, multiplier {args.multiplier:g} | "
          f"Scanned {scanned} asset(s)\n")

    if touching:
        name_w = max(max(len(names[r[0]]) for r in touching), len('ASSET'))
        print(f"{'ASSET':<{name_w}}  {'TREND':<6} {'LINE':<6} {'AGE':>5}  "
              f"{'PROXIMITY':>9}  {'LAST CLOSE':>12}  {'LINE VALUE':>12}")
        for symbol, ev, price in touching:
            # pad first, colorize after: the f-string widths would count the
            # invisible ANSI escape characters otherwise
            trend = colored(f"{ev['trend']:<6}",
                            GREEN if ev['trend'] == 'Up' else RED, use_color)
            line = colored(f"{ev['line']:<6}",
                           GREEN if ev['line'] == 'Upper' else RED, use_color)
            print(f"{names[symbol]:<{name_w}}  {trend} {line} "
                  f"{ev['age']:>5}  {ev['proximity']:>8.2f}%  "
                  f"{price:>12.2f}  {ev['line_value']:>12.2f}")
        print(f"\n{len(touching)} asset(s) touching the supertrend line")
    else:
        print(f"No assets within {args.max_proximity:g}% of the supertrend line")

    if surpassed:
        print(f"\nSurpassed (the close crossed the line on the last bar):")
        for symbol, ev, price in surpassed:
            beyond = f"{ev['beyond']:.2f}%" if ev['beyond'] != float('inf') else "?"
            old_trend = colored(f"{ev['old_trend']} trend",
                                GREEN if ev['old_trend'] == 'Up' else RED,
                                use_color)
            new_trend = colored(f"{ev['trend']}",
                                GREEN if ev['trend'] == 'Up' else RED, use_color)
            line_s = colored(f"surpassed the {ev['line'].lower()} line",
                             GREEN if ev['line'] == 'Upper' else RED, use_color)
            print(f"  {names[symbol]}: the {old_trend} flipped "
                  f"{new_trend} - the close {price:.2f} {line_s} "
                  f"({ev['line_value']:.2f}) by {beyond}")
        print(f"{len(surpassed)} surpassed line(s)")

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Find assets whose close is touching a supertrend line "
                    "(<= max proximity) or crossed it (the trend flipped)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()