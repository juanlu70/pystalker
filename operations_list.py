#!/usr/bin/env python3
"""
operations_list.py - List the trading operations (the Operations journal)

Prints the trading journal stored in the pystalker database - the same list
as Trading -> Operations in the application: the entry date, the asset (its
personalized name), the PAPER and PLANNED flags, Long/Short, entry price,
volume, leverage, the current price (the last close stored in the
database), the leveraged GAIN % (green/red like the application, plain for
planned operations whose gains are not real yet), the exit, the exit price
and the FINAL PNL (money when the invested volume is known, the leveraged
percent otherwise - colored for real closed operations, plain for the
potential PNL of open ones and the projected PNL of planned ones).

The listing logic (and the gain/PNL math, identical to the application's)
lives in pystalker/core/operations.py. The database is only read.

Usage:
  python operations_list.py
  python operations_list.py --asset BTC
  python operations_list.py --open
  python operations_list.py --closed
  python operations_list.py --planned
  python operations_list.py --paper
  python operations_list.py --no-color
  python operations_list.py --db /path/to/pystalker.db
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pystalker.core.operations import fmt_gain, fmt_pnl, fmt_price, list_operations

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'

COLUMNS = ['ENTRY', 'ASSET', 'PAPER', 'PLANNED', 'LONG/SHORT', 'ENTRY PRICE', 'VOLUME',
           'LEVERAGE', 'CURRENT PRICE', 'GAIN %', 'EXIT', 'EXIT PRICE', 'FINAL PNL']


def gain_color(value):
    return GREEN if value >= 0 else RED


def colored(text, color, enabled=True, bold=False):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    if not enabled or color is None:
        return text
    prefix = (BOLD if bold else '') + color
    return f"{prefix}{text}{RESET}"


def main():
    parser = argparse.ArgumentParser(
        description="List the trading operations (the Operations journal) from the terminal")
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="keep only this asset's operations (substring of its stored name, "
                             "official symbol or personalized name)")
    status = parser.add_mutually_exclusive_group()
    status.add_argument('--open', action='store_true', help="only open operations")
    status.add_argument('--closed', action='store_true', help="only closed operations")
    parser.add_argument('--planned', action='store_true',
                        help="only planned operations (projects that may or may not start)")
    parser.add_argument('--paper', action='store_true', help="only paper trading operations")
    parser.add_argument('--no-color', action='store_true', help="plain text without ANSI colors")
    args = parser.parse_args()

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    try:
        result = list_operations(
            conn,
            asset=args.asset,
            status='open' if args.open else ('closed' if args.closed else None),
            paper=True if args.paper else None,
            planned=True if args.planned else None)
    except sqlite3.OperationalError:
        print("The database has no operations yet - create them in the application "
              "(Trading -> Operations).")
        conn.close()
        sys.exit(1)
    conn.close()

    rows = result['rows']
    use_color = not args.no_color

    print(f"Report generated: {result['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    scope = []
    if args.asset:
        scope.append(f"asset \"{args.asset}\"")
    if args.open:
        scope.append("open")
    if args.closed:
        scope.append("closed")
    if args.planned:
        scope.append("planned")
    if args.paper:
        scope.append("paper")
    scope_text = (f" matching {' + '.join(scope)}" if scope else "") + \
                 (f" - {len(rows)} of {result['total']} in the database" if scope else "")
    print(f"Operations{scope_text}\n")

    if not rows:
        print("No operations in the database yet" if not scope
              else "No operation matches the filters")
        return

    # column values as plain text first (padding), colors applied after so
    # the ANSI escapes never break the alignment
    plain_rows = []
    for r in rows:
        lev = r['lev']
        plain_rows.append((
            r['entry_date'] or '',
            r['asset'],
            'X' if r['paper'] else '-',
            'X' if r['planned'] else '-',
            r['side'],
            fmt_price(r['entry_price']) if r['entry_price'] is not None else '-',
            fmt_price(r['volume']) if r['volume'] is not None else '-',
            f"{lev:g}x" if lev else (r['leverage'] if r['leverage'] else '-'),
            fmt_price(r['current_price']) if r['current_price'] is not None else '-',
            fmt_gain(r['gain']),
            r['exit_date'] or '',
            fmt_price(r['exit_price']) if r['exit_price'] is not None else '',
            fmt_pnl(r['pnl'], r['pnl_money']),
        ))

    widths = [max(len(COLUMNS[i]), max((len(row[i]) for row in plain_rows), default=0))
              for i in range(len(COLUMNS))]
    aligns = ['<', '<', '>', '>', '<', '>', '>', '>', '>', '>', '<', '>', '>']

    header = '  '.join(f"{COLUMNS[i]:{aligns[i]}{widths[i]}}" for i in range(len(COLUMNS)))
    print(header)
    for r, plain in zip(rows, plain_rows):
        # pad first, colorize after: the f-string widths would count the
        # invisible ANSI escape characters otherwise
        cells = [f"{plain[i]:{aligns[i]}{widths[i]}}" for i in range(len(COLUMNS))]
        # Long/Short: colored like the application (green long, red short)
        side_color = GREEN if r['side'] == 'Long' else RED
        cells[4] = colored(cells[4], side_color, use_color, bold=True)
        # GAIN %: green/red like the application, plain for planned
        # operations (still only a project, no real gains yet)
        if r['gain'] is not None and not r['planned']:
            cells[9] = colored(cells[9], gain_color(r['gain']), use_color, bold=True)
        # FINAL PNL: colored for real closed operations; plain for the
        # potential PNL of open ones and the projected PNL of planned ones
        if r['pnl'] is not None and not r['open'] and not r['planned']:
            cells[12] = colored(cells[12], gain_color(r['pnl']), use_color, bold=True)
        print('  '.join(cells))

    print(f"\n{len(rows)} operation(s): {result['n_open']} open, "
          f"{result['n_closed']} closed, {result['n_planned']} planned")


if __name__ == '__main__':
    main()