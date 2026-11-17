#!/usr/bin/env python3
"""
pystalker_cli.py - The unified PyStalker command-line tool

ONE program with every tool INSIDE it (the user's request: the code is
not dispersed - the old console_programs standalones are integrated
here and not restored). One command per tool:

  operations   The trading journal (the Trading -> Operations list):
               the operations with their gains (green/red like the
               application, plain for planned projects) and filters.
    --db --asset --open/--closed --planned --paper --no-color

  update       Update all assets' data (the File > Update All Stock Data
               twin): every asset from the source that serves it.
    --db --symbol --no-color

  scanner      The fused scanner: the channel scanner and the supertrend
               scanner in one command - the drawn channels (near a line,
               broken) and/or the supertrend indicator (touching the
               line, trend flips, opens outside the band range); bare or
               --all scans both at once and appends the both-scans-by-asset
               view (each asset's two conditions side by side, sorted by
               asset name, with the both/only-one counts and the events'
               breakdown: broken channels by line, flips by direction,
               each with its percentage; both tables titled with their
               day); --channels or --supertrend scans one alone. The
               section flags --near, --broken and --open-broken print
               ONLY that section of the listing (combinable; they take
               precedence over the scan flags and run the scans their
               sections need). --historical (needs --asset) scans the
               asset's WHOLE HISTORY: every occurrence of a broken
               channel, a supertrend flip or an open broken supertrend
               channel, one chronological list (one occurrence per
               episode), with --broken/--open-broken filtering the event
               types.
    --channels/--supertrend/--all --db --max-proximity --asset
    --date(both scans as of a past day) --lower-than(channels)
    --period/--multiplier(supertrend) --no-color
    --near/--broken/--open-broken(only that section of the listing)
    --historical(--asset: the asset's whole history of events)

  status       The per-asset snapshot, one row per asset sorted by its
               display name: the last close (green when it went up
               since the previous bar, red when it went down) with the
               DAY % column (the percent change along the day) and the
               WEEK % column next to it (the percent change along the
               last week), both colored the same way, the last update
               date (when the shown data was last refreshed), the
               nearest drawn channel (its kind + the percentage
               distances to the upper and lower lines) with the CH BREAK
               column (the line the close went beyond), and the
               supertrend bands (the percentage distances to the Up line
               - the support below the price - and the Down line - the
               resistance above) with the ST BREAK column (the band the
               close went beyond); '-' marks what does not apply.
               --date YYYY-MM-DD shows the status as of a past date (the
               last bar on or before it, with its own daily and weekly
               changes, channel and supertrend). --history with --asset
               shows the asset's whole daily history: one row per bar
               since the begin (the oldest day first), the same columns
               at each day - the row's own day in the LAST UPDATE
               column; --date ends the history at that day.
    --db --asset --date --history --period --multiplier --no-color

  list         The assets of an exchange - the second argument is the
               exchange: "list phemex" or "list pionex".
    --search --type --quote(phemex) --all

The machine-learning programs stay their own files in console_programs/
(volatility_prediction.py, volatility_accuracy.py,
supertrend_flip_study.py and the supertrend/ trade suite), and all the
scanning logic lives in the pystalker.core package shared with the
application.

Usage:
  python pystalker_cli.py                       (no command: the help screen)
  python pystalker_cli.py operations
  python pystalker_cli.py operations --asset BTC --planned
  python pystalker_cli.py update
  python pystalker_cli.py update --symbol AAPL
  python pystalker_cli.py scanner                    (channels + supertrend)
  python pystalker_cli.py scanner --channels
  python pystalker_cli.py scanner --supertrend --multiplier 3
  python pystalker_cli.py scanner --all --asset BTC-USD --max-proximity 5
  python pystalker_cli.py scanner --date 2026-11-04          (that day's scans)
  python pystalker_cli.py scanner --broken                   (only that section)
  python pystalker_cli.py scanner --near --open-broken       (two sections alone)
  python pystalker_cli.py scanner --historical --asset TSLA  (TSLA's event history)
  python pystalker_cli.py status
  python pystalker_cli.py status --asset BTC-USD
  python pystalker_cli.py status --date 2026-11-04
  python pystalker_cli.py status --asset BTC-USD --history  (the whole history)
  python pystalker_cli.py list phemex --search Tesla
  python pystalker_cli.py list pionex --type perp

  python pystalker_cli.py <command> --help     lists the flags of a command
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))          # the pystalker package imports
from pystalker.core.channel_scanner import (evaluate_channel, get_assets,
                                            get_source_symbol, load_channels,
                                            scan_channel_break_history,
                                            scan_channel_proximity)
from pystalker.core.database import Database
from pystalker.core.operations import (fmt_gain, fmt_price, get_display_name,
                                       list_operations)
from pystalker.core.providers import (DataManager, PhemexProvider,
                                      PHEMEX_CATEGORY_LABELS, PionexProvider)
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                        scan_supertrend, scan_supertrend_history,
                                        supertrend)

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'


def colored(text, color, enabled=True, bold=False):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    if not enabled or color is None:
        return text
    prefix = (BOLD if bold else '') + color
    return f"{prefix}{text}{RESET}"


def _date_arg(text):
    """The --date flag's value: a YYYY-MM-DD date (the scanner and the
    status share it)."""
    try:
        datetime.strptime(text, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"the date must be YYYY-MM-DD (got {text!r})")
    return text


# ====================================================================
# operations - the trading journal (the Trading -> Operations list)
# ====================================================================
# Prints the trading journal stored in the pystalker database - the same
# list as Trading -> Operations in the application, split into the same
# three groups as its tabs: OPEN OPERATIONS (running, not planned),
# PLANNED OPERATIONS (all the planned ones) and CLOSED OPERATIONS (done,
# not planned), each section with its title and count - a group flag
# lists one group alone. The columns: the entry date, the asset (its
# personalized name), the PAPER and PLANNED flags, Long/Short, entry
# price, the stop price (a light-red line is drawn on the asset's chart
# in the application when it is set), volume, leverage, the current
# price (the last close stored in the database), the NET GAIN % (the
# directional move without the leverage, the 1x gain) and the leveraged
# GAIN % (green/red like the application, plain for planned operations
# whose gains are not real yet), the exit, the exit price and the FINAL
# GAIN % (the leveraged gain at the exit price - identical to GAIN % for
# closed operations, the projection at the reference exit price while
# open). The listing logic (and the gain math, identical to the
# application's) lives in pystalker/core/operations.py; the database is
# only read.

OPERATIONS_COLUMNS = ['ENTRY', 'ASSET', 'PAPER', 'PLANNED', 'LONG/SHORT',
                      'ENTRY PRICE', 'STOP', 'VOLUME', 'LEVERAGE',
                      'CURRENT PRICE', 'NET GAIN %', 'GAIN %', 'EXIT',
                      'EXIT PRICE', 'FINAL GAIN %']

OPERATIONS_TITLES = {'open': 'OPEN OPERATIONS', 'planned': 'PLANNED OPERATIONS',
                     'closed': 'CLOSED OPERATIONS'}


def _gain_color(value):
    return GREEN if value >= 0 else RED


def build_operations_parser(parser):
    """The operations command's flags."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="keep only this asset's operations (substring of its stored name, "
                             "official symbol or personalized name)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--open', action='store_true',
                       help="only the open operations (running, not planned)")
    group.add_argument('--closed', action='store_true',
                       help="only the closed operations (done, not planned)")
    group.add_argument('--planned', action='store_true',
                       help="only the planned operations (projects, open or closed)")
    parser.add_argument('--paper', action='store_true', help="only paper trading operations")
    parser.add_argument('--no-color', action='store_true', help="plain text without ANSI colors")


def run_operations(args):

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    group = 'open' if args.open else ('closed' if args.closed
                                       else ('planned' if args.planned else None))
    conn = sqlite3.connect(args.db)
    try:
        result = list_operations(
            conn,
            asset=args.asset,
            group=group,
            paper=True if args.paper else None)
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
    if group is not None:
        scope.append(f"only {group}")
    if args.paper:
        scope.append("paper")
    scope_text = (f" matching {' + '.join(scope)}" if scope else "") + \
                 (f" - {len(rows)} of {result['total']} in the database" if scope else "")
    print(f"Operations{scope_text}\n")

    if not rows:
        print("No operations in the database yet" if not scope
              else "No operation matches the filters")
        return

    # by default the operations are listed in three sections (open, planned,
    # closed - the application's tabs); a group flag lists one alone
    if group is not None:
        sections = [(OPERATIONS_TITLES[group], rows)]
    else:
        sections = [(OPERATIONS_TITLES[g], [r for r in rows if r['group'] == g])
                     for g in ('open', 'planned', 'closed')]

    for title, section_rows in sections:
        if not section_rows:
            continue

        # column values as plain text first (padding), colors applied after so
        # the ANSI escapes never break the alignment
        plain_rows = []
        for r in section_rows:
            lev = r['lev']
            plain_rows.append((
                r['entry_date'] or '',
                r['asset'],
                'X' if r['paper'] else '-',
                'X' if r['planned'] else '-',
                r['side'],
                fmt_price(r['entry_price']) if r['entry_price'] is not None else '-',
                fmt_price(r['stop_price']) if r['stop_price'] is not None else '-',
                fmt_price(r['volume']) if r['volume'] is not None else '-',
                f"{lev:g}x" if lev else (r['leverage'] if r['leverage'] else '-'),
                fmt_price(r['current_price']) if r['current_price'] is not None else '-',
                fmt_gain(r['net_gain']),
                fmt_gain(r['gain']),
                r['exit_date'] or '',
                fmt_price(r['exit_price']) if r['exit_price'] is not None else '',
                fmt_gain(r['final_gain']),
            ))

        widths = [max(len(OPERATIONS_COLUMNS[i]),
                     max((len(row[i]) for row in plain_rows), default=0))
                  for i in range(len(OPERATIONS_COLUMNS))]
        aligns = ['<', '<', '>', '>', '<', '>', '>', '>', '>', '>', '>', '>', '<', '>', '>']

        print(f"{title} ({len(section_rows)})")
        header = '  '.join(f"{OPERATIONS_COLUMNS[i]:{aligns[i]}{widths[i]}}"
                           for i in range(len(OPERATIONS_COLUMNS)))
        print(header)
        for r, plain in zip(section_rows, plain_rows):
            # pad first, colorize after: the f-string widths would count the
            # invisible ANSI escape characters otherwise
            cells = [f"{plain[i]:{aligns[i]}{widths[i]}}"
                     for i in range(len(OPERATIONS_COLUMNS))]
            # Long/Short: colored like the application (green long, red short)
            side_color = GREEN if r['side'] == 'Long' else RED
            cells[4] = colored(cells[4], side_color, use_color, bold=True)
            # NET GAIN % / GAIN %: green/red like the application (the 1x move
            # and the leveraged one), plain for planned operations (still only
            # a project, no real gains yet)
            if r['net_gain'] is not None and not r['planned']:
                cells[10] = colored(cells[10], _gain_color(r['net_gain']),
                                    use_color, bold=True)
            if r['gain'] is not None and not r['planned']:
                cells[11] = colored(cells[11], _gain_color(r['gain']),
                                    use_color, bold=True)
            # FINAL GAIN %: colored for real closed operations (the leveraged
            # gain at the exit price, identical to GAIN % there); plain for the
            # potential gain of open ones and the projected gain of planned ones
            if r['final_gain'] is not None and not r['open'] and not r['planned']:
                cells[14] = colored(cells[14], _gain_color(r['final_gain']),
                                    use_color, bold=True)
            print('  '.join(cells))
        print()

    print(f"{len(rows)} operation(s): {result['n_open']} open, "
          f"{result['n_planned']} planned, {result['n_closed']} closed")


# ====================================================================
# update - update all assets' data (the File > Update All Stock Data twin)
# ====================================================================
# Fetches the daily candles of every asset in the database from the data
# source that serves it (each asset remembers whether it came from Yahoo
# Finance, Phemex or Pionex - exactly like the menu point) and merges
# them into the database (new bars are added, existing ones refreshed;
# nothing is deleted). Copies (assets that share another asset's bars
# through their source_symbol setting) are skipped: they always use
# their source asset's fresh bars. Like the application, this tool
# WRITES the database.

def _bars_snapshot(database, symbol):
    """(bar count, newest bar datetime) of the asset's daily bars table."""
    try:
        row = database.conn.execute(
            f'SELECT COUNT(*), MAX(timestamp) FROM "{symbol}_bars"').fetchone()
        count = row[0]
        newest = datetime.fromtimestamp(row[1]) if row[1] else None
        return count, newest
    except sqlite3.OperationalError:
        return 0, None


def build_update_parser(parser):
    """The update command's flags."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--symbol', default=None,
                        help="update a single asset instead of all (the exact database symbol)")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run_update(args):

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    use_color = not args.no_color
    database = Database(args.db)
    data_manager = DataManager()

    symbols = database.get_symbols()
    if args.symbol is not None:
        if args.symbol not in symbols:
            print(f"Symbol not found in the database: {args.symbol}")
            database.close()
            sys.exit(1)
        symbols = [args.symbol]

    if not symbols:
        print("No symbols in the database. Download some data first.")
        database.close()
        sys.exit(1)

    # copies share their source asset's bars: nothing to fetch for them
    copies = [s for s in symbols if database.is_copy(s)]
    symbols = [s for s in symbols if not database.is_copy(s)]

    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Updating {len(symbols)} symbol(s) from their data sources"
          + (f" ({len(copies)} copie(s) skipped: they use their source asset's bars)"
             if copies else "") + "\n")

    updated, failed = [], []
    for symbol in symbols:
        source = database.load_data_source(symbol)
        before_count, _ = _bars_snapshot(database, symbol)
        try:
            bar_data = data_manager.fetch_by_source(source, symbol)
            if bar_data is not None and bar_data.count() > 0:
                database.save_bars(bar_data)
                after_count, newest = _bars_snapshot(database, symbol)
                added = after_count - before_count
                updated.append(symbol)
                print(f"{symbol:<{20}}  {source.capitalize():<8}  "
                      f"{after_count:>7} bars  "
                      f"{newest.strftime('%Y-%m-%d') if newest else '-':<10}  "
                      f"+{added} new")
            else:
                # no exception, but nothing came back (the GUI also counts
                # these as updated; here the line shows it plainly)
                updated.append(symbol)
                print(f"{symbol:<{20}}  {source.capitalize():<8}  "
                      f"{'no data returned':>7}")
        except Exception as e:
            failed.append((symbol, e))
            print(colored(f"{symbol:<{20}}  {source.capitalize():<8}  ERROR: {e}",
                          RED, use_color))

    if failed:
        print(colored(f"\nUpdated {len(updated)}/{len(symbols)} symbol(s), "
                      f"{len(failed)} failed", RED, use_color))
    else:
        print(colored(f"\nUpdated {len(updated)}/{len(symbols)} symbol(s)",
                      GREEN, use_color))

    database.close()


# ====================================================================
# the channel scanner's report (the scanner --channels half)
# ====================================================================
# Scans all assets in the database, keeps the ones that have channel
# drawings (ascending/descending channels), and reports the assets whose
# last close is inside the channel and within max-proximity of the
# lower or the upper channel line (the CHANNEL column: Ascending green,
# Descending red; the NEAR LINE column: Upper green, Lower red), plus
# the broken channels as notifications ("price X is beyond the upper
# line (Y) by Z%"). --lower-than keeps only the assets at that price or
# lower. The scanning logic lives in pystalker.core.channel_scanner and
# is shared with the application's Trading menu.

def resolve_channel_names(conn, res):
    """The personalized display names of the listed assets (like
    Operations); resolved while the connection is still open."""
    names = {}
    for sym, _, _ in res['near'] + res['broken']:
        names[sym] = get_display_name(conn, sym) or sym
    return names


def print_channel_report(res, names, args):
    """The channel scanner's report."""
    near_results = res['near']
    broken_results = res['broken']
    skipped = res['skipped']
    scanned = res['scanned']

    use_color = not args.no_color
    price_filter = f" - price <= {args.lower_than:g}" if args.lower_than is not None else ""
    # the date of the data in the title (the --date day, or the scan's
    # day): among all the data, every section's title identifies itself
    date_str = (getattr(args, 'date', None)
                or res['generated'].strftime('%Y-%m-%d'))
    print(f"Report generated: {res['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Channel scanner {date_str} - assets with price within "
          f"{args.max_proximity:g}% of a channel line{price_filter}")
    print(f"Scanned {scanned} asset(s) with channel drawings\n")

    if near_results:
        name_w = max(len(names[r[0]]) for r in near_results)
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
            print(f"{names[symbol]:<{name_w}}  {channel} {near_line} "
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
            print(f"  {names[symbol]}: {kind_s} - price {price:.2f} is {line_s} "
                  f"({ev['line_value']:.2f}) by {beyond_s}")
        print(f"{len(broken_results)} broken channel(s)")

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


# ====================================================================
# the supertrend scanner's reports (the scanner --supertrend half)
# ====================================================================
# Computes the classic Supertrend indicator (ATR period 10, multiplier
# 1.8 - the parameters the user chose; --period/--multiplier change
# them per run) over each asset's daily bars and reports the last close
# against the ACTIVE trend line: TOUCHING (the close within
# max-proximity of the line and still on the safe side), SURPASSED (the
# close crossed the line on the last bar - the trend flipped, reported
# as "the Up trend flipped Down - the close X surpassed the lower line
# (Y) by Z%"), and the OPEN BROKEN SUPERTREND CHANNEL alert (the last
# bar OPENED outside the Supertrend channel - the chart's Upper/Lower
# lines: the ACTIVE ratcheted line plus the freshly recomputed basic
# line on the other side - "the open X broke the Upper/Lower line (Y)
# by Z% - a Up/Down candle, close W"). Copies use their source asset's
# bars; the scanning logic lives in pystalker.core.supertrend.

def resolve_supertrend_names(conn, res):
    """The personalized display names of the listed assets (like
    Operations); resolved while the connection is still open."""
    names = {}
    for sym, _, _ in res['touching'] + res['surpassed'] + res['open_broken']:
        names[sym] = get_display_name(conn, sym) or sym
    return names


def print_supertrend_report(res, names, args):
    """The supertrend scanner's report."""
    touching = res['touching']
    surpassed = res['surpassed']
    skipped = res['skipped']
    scanned = res['scanned']

    use_color = not args.no_color
    # the date of the data in the title (the --date day, or the scan's day)
    date_str = (getattr(args, 'date', None)
                or res['generated'].strftime('%Y-%m-%d'))
    print(f"Report generated: {res['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Supertrend {date_str} (period {args.period}, multiplier {args.multiplier:g}) - "
          f"assets with the close within {args.max_proximity:g}% of the supertrend "
          f"line or beyond it")
    print(f"Scanned {scanned} asset(s)\n")

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


def print_open_broken_alert(res, names, args, section_mode=False):
    """The OPEN BROKEN SUPERTREND CHANNEL alert: the last bar's open
    outside the Supertrend channel - beyond the Upper or the Lower line,
    whatever the candle's direction. A separate function so the scanner
    can print it at the very END of its listing (it does not fire often -
    the bottom of the output is easy to locate); nothing is printed when
    no asset fired - UNLESS section_mode (the scanner's --open-broken
    flag): a section-only run prints the section's title and a "No
    opens..." line when nothing fired, so it always shows the scan ran,
    and it does not open with a blank line (there is nothing above it)."""
    open_broken = res['open_broken']
    use_color = not args.no_color
    date_str = (getattr(args, 'date', None)
                or res['generated'].strftime('%Y-%m-%d'))
    title = (f"OPEN BROKEN SUPERTREND CHANNEL {date_str} (period {args.period}, "
             f"multiplier {args.multiplier:g}) - the open of the last bar "
             f"is beyond the Upper or the Lower line:")
    if not open_broken:
        if section_mode:
            print(title)
            print("No opens outside the supertrend channel")
        return
    print(("" if section_mode else "\n") + title)
    for symbol, ev, price in open_broken:
        beyond = f"{ev['beyond']:.2f}%" if ev['beyond'] != float('inf') else "?"
        # the candle's direction colored like the trend coding; the broken
        # line colored like the line coding (Upper green, Lower red)
        candle = colored(f"{ev['candle']} candle",
                         GREEN if ev['candle'] == 'Up' else RED, use_color)
        line_s = colored(f"broke the {ev['line']} line",
                         GREEN if ev['line'] == 'Upper' else RED, use_color)
        print(f"  {names[symbol]}: the open {ev['open']:.2f} {line_s} "
              f"({ev['line_value']:.2f}) by {beyond} - a {candle}, "
              f"close {price:.2f}")
    print(f"{len(open_broken)} open(s) outside the supertrend channel")


# ====================================================================
# scanner - the fused scanner: channels and/or supertrend
# ====================================================================

def build_scanner_parser(parser):
    """The scanner command's flags."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--channels', action='store_true',
                       help="scan the drawn channels only (the channel scanner's report)")
    group.add_argument('--supertrend', action='store_true',
                       help="scan the supertrend indicator only (the supertrend scanner's report)")
    group.add_argument('--all', action='store_true',
                       help="scan channels and supertrend at the same time (also the default)")
    # the section flags: print ONLY that section of the listing; they take
    # precedence over the scan flags above (the chosen sections run the
    # scans they need) and can be combined - the sections print in the
    # listing's order
    section_group = parser.add_argument_group(
        'section flags',
        "show only that section of the listing (combinable; they take "
        "precedence over --channels/--supertrend/--all). --historical "
        "(needs --asset) is its own mode: the asset's whole history of "
        "broken channel / supertrend flip / open broken events")
    section_group.add_argument('--near', action='store_true',
                               help="show only the NEAR A CHANNEL LINE / "
                                    "TOUCHING THE SUPERTREND LINE table "
                                    "(both scans run)")
    section_group.add_argument('--broken', action='store_true',
                               help="show only the BROKEN CHANNEL / SUPERTREND "
                                    "FLIP table (both scans run); with "
                                    "--historical: only the broken channel + "
                                    "flip occurrences")
    section_group.add_argument('--open-broken', action='store_true',
                               help="show only the OPEN BROKEN SUPERTREND "
                                    "CHANNEL section (the closing alert; the "
                                    "supertrend scan runs); with --historical: "
                                    "only the open broken occurrences")
    section_group.add_argument('--historical', action='store_true',
                               help="with --asset: the asset's WHOLE HISTORY of "
                                    "events - every occurrence of a broken "
                                    "channel, a supertrend flip or an open "
                                    "broken supertrend channel, one "
                                    "chronological list (one occurrence per "
                                    "episode: the first bar of each stretch "
                                    "outside a line); --broken/--open-broken "
                                    "filter the event types, --near is ignored")
    parser.add_argument('--max-proximity', type=float, default=10.0,
                        help="maximum proximity percentage to report (default: 10; both scans)")
    parser.add_argument('--asset', default=None,
                        help="scan a single asset instead of all (both scans)")
    parser.add_argument('--date', default=None, type=_date_arg, metavar='YYYY-MM-DD',
                        help="scan a PAST day: only the bars up to that date, so the "
                             "channels and the supertrend are evaluated at that moment "
                             "of the history (both scans)")
    parser.add_argument('--lower-than', type=float, default=None, metavar='PRICE',
                        help="(channels) keep only the assets whose last price is at this "
                             "price or lower (e.g. --lower-than 15)")
    parser.add_argument('--period', type=int, default=SUPERTREND_PERIOD,
                        help=f"(supertrend) the ATR period (default: {SUPERTREND_PERIOD})")
    parser.add_argument('--multiplier', type=float, default=SUPERTREND_MULTIPLIER,
                        help=f"(supertrend) the multiplier (default: {SUPERTREND_MULTIPLIER:g})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run_scanner(args):

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    # --date: the scan of a past day - only the bars strictly before the
    # end of that date (None = today, the whole history)
    cutoff = None
    if args.date is not None:
        cutoff = datetime.strptime(args.date, '%Y-%m-%d').timestamp() + 86400
        print(f"Scanner as of {args.date} - only the bars up to that date\n")

    # the --historical mode: one asset's whole history of events (the
    # user's request) - it needs --asset and takes over the run; the
    # --broken/--open-broken section flags filter its event types
    if args.historical:
        if not args.asset:
            print("The --historical scan needs --asset (one asset's whole "
                  "history of events)")
            sys.exit(1)
        print_historical(args, cutoff)
        return

    # the section flags (--near/--broken/--open-broken): print ONLY those
    # sections of the listing, in the listing's order; they take
    # precedence over the scan flags - the by-asset tables need BOTH
    # scans, the OPEN BROKEN alert only the supertrend one
    sections = [s for s, on in (('near', args.near),
                                ('broken', args.broken),
                                ('open_broken', args.open_broken)) if on]

    # --channels: only the channel scan; --supertrend: only the supertrend
    # scan; --all or bare: both (the user's choice for the default)
    if sections:
        run_channels = 'near' in sections or 'broken' in sections
        run_supertrend = True
    else:
        run_channels = not args.supertrend
        run_supertrend = not args.channels
    both = run_channels and run_supertrend

    conn = sqlite3.connect(args.db)
    res_channels = names_channels = None
    res_supertrend = names_supertrend = None
    if run_channels:
        res_channels = scan_channel_proximity(
            conn, max_proximity=args.max_proximity, symbol=args.asset,
            lower_than=args.lower_than, cutoff=cutoff)
        names_channels = resolve_channel_names(conn, res_channels)
    if run_supertrend:
        res_supertrend = scan_supertrend(
            conn, period=args.period, multiplier=args.multiplier,
            max_proximity=args.max_proximity, symbol=args.asset,
            cutoff=cutoff)
        names_supertrend = resolve_supertrend_names(conn, res_supertrend)
    conn.close()

    if sections:
        # the section mode: only the chosen sections, in the listing's
        # order (the by-asset tables first, the alert closing as always);
        # an empty section prints its "No ..." line inside its printer
        if 'near' in sections or 'broken' in sections:
            print_fused_view(res_channels, names_channels, res_supertrend,
                             names_supertrend, args, sections)
        if 'open_broken' in sections:
            if 'near' in sections or 'broken' in sections:
                print()          # the sections' separator, like the full listing
            print_open_broken_alert(res_supertrend, names_supertrend, args,
                                    section_mode=True)
        return

    if res_channels is not None:
        if both:
            print("Channel scanner:")
        print_channel_report(res_channels, names_channels, args)
    if res_supertrend is not None:
        if both:
            print("\nSupertrend:")
        print_supertrend_report(res_supertrend, names_supertrend, args)
    if both:
        print_fused_view(res_channels, names_channels, res_supertrend,
                         names_supertrend, args)
    if res_supertrend is not None:
        # the OPEN BROKEN SUPERTREND CHANNEL alert closes the listing: it
        # does not fire often, so the very end is where it is easiest to
        # locate (after the by-asset view in --all mode)
        print_open_broken_alert(res_supertrend, names_supertrend, args)


def print_historical(args, cutoff):
    """The --historical mode: ONE asset's whole history of events (the
    user's request) - every occurrence of a broken channel, a supertrend
    flip or an open broken supertrend channel, ONE chronological list
    (the user's choice), one occurrence per episode: the first bar of
    each stretch of bars outside a line. Each row is the event's date
    plus the established notification wording; the counts line closes
    the listing. --broken shows only the broken channel + supertrend
    flip occurrences, --open-broken only the open broken ones (the
    user's choices); --near is ignored (touching is a state, not an
    event); --date limits the history to that day, --period and
    --multiplier set the supertrend parameters."""
    conn = sqlite3.connect(args.db)
    # the personalized display name in the title (the established
    # convention: the listings show display names)
    name = get_display_name(conn, args.asset) or args.asset
    # the event types to show (the --broken/--open-broken filters)
    show_broken = not args.open_broken       # channel breaks + flips
    show_open = not args.broken
    skipped = []
    res_channels = None
    if show_broken:
        res_channels = scan_channel_break_history(conn, args.asset, cutoff)
        skipped += res_channels['skipped']
    res_st = scan_supertrend_history(conn, period=args.period,
                                     multiplier=args.multiplier,
                                     symbol=args.asset, cutoff=cutoff)
    skipped += res_st['skipped']
    conn.close()

    # the one chronological list of occurrences (the user's choice)
    rows = []                 # (timestamp, type, evaluation, close)
    if show_broken:
        for ts, ev, price in (res_channels['occurrences'] if res_channels
                              else []):
            rows.append((ts, 'channel', ev, price))
        for ts, ev, price in res_st['flips']:
            rows.append((ts, 'flip', ev, price))
    if show_open:
        for ts, ev, price in res_st['open_broken']:
            rows.append((ts, 'open', ev, price))
    rows.sort(key=lambda r: r[0])

    use_color = not args.no_color
    # the date of the data in the title (the --date day, or the scan's day)
    date_str = args.date or res_st['generated'].strftime('%Y-%m-%d')
    if show_broken and show_open:
        what = ("every occurrence of a broken channel, a supertrend flip "
                "or an open broken supertrend channel")
    elif show_broken:
        what = "every occurrence of a broken channel or a supertrend flip"
    else:
        what = "every occurrence of an open broken supertrend channel"
    print(f"Report generated: "
          f"{res_st['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Historical scanner {name} {date_str} (period {args.period}, "
          f"multiplier {args.multiplier:g}) - {what}:")

    def pct(value):
        return f"{value:.2f}%" if value != float('inf') else "?"

    if not rows:
        if show_broken and show_open:
            no_what = ("a broken channel, a supertrend flip or an open "
                       "broken supertrend channel")
        elif show_broken:
            no_what = "a broken channel or a supertrend flip"
        else:
            no_what = "an open broken supertrend channel"
        print(f"No occurrence of {no_what} in the history")
    else:
        for ts, kind, ev, price in rows:
            day = datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d')
            if kind == 'channel':
                # the channel report's established broken wording
                kind_s = colored(f"{ev['kind']} channel",
                                  GREEN if ev['kind'] == 'Ascending' else RED,
                                  use_color)
                line_s = colored(f"beyond the {ev['broken_line'].lower()} line",
                                 GREEN if ev['broken_line'] == 'Upper'
                                 else RED, use_color)
                print(f"{day}  {kind_s} - price {price:.2f} is {line_s} "
                      f"({ev['line_value']:.2f}) by {pct(ev['beyond'])}")
            elif kind == 'flip':
                # the supertrend report's established flip wording
                old_s = colored(f"{ev['old_trend']} trend",
                                GREEN if ev['old_trend'] == 'Up' else RED,
                                use_color)
                new_s = colored(f"{ev['trend']}",
                                GREEN if ev['trend'] == 'Up' else RED,
                                use_color)
                line_s = colored(f"surpassed the {ev['line'].lower()} line",
                                 GREEN if ev['line'] == 'Upper' else RED,
                                 use_color)
                print(f"{day}  the {old_s} flipped {new_s} - the close "
                      f"{price:.2f} {line_s} ({ev['line_value']:.2f}) "
                      f"by {pct(ev['beyond'])}")
            else:
                # the OPEN BROKEN alert's established wording
                candle_s = colored(f"{ev['candle']} candle",
                                   GREEN if ev['candle'] == 'Up' else RED,
                                   use_color)
                line_s = colored(f"broke the {ev['line']} line",
                                 GREEN if ev['line'] == 'Upper' else RED,
                                 use_color)
                print(f"{day}  the open {ev['open']:.2f} {line_s} "
                      f"({ev['line_value']:.2f}) by {pct(ev['beyond'])} - "
                      f"a {candle_s}, close {price:.2f}")
        # the counts line (the filtered event types only)
        counts = []
        if show_broken:
            counts.append(f"{sum(1 for r in rows if r[1] == 'channel')} "
                          f"broken channel(s)")
            counts.append(f"{sum(1 for r in rows if r[1] == 'flip')} "
                          f"supertrend flip(s)")
        if show_open:
            counts.append(f"{sum(1 for r in rows if r[1] == 'open')} "
                          f"open broken")
        print(f"\n{len(rows)} occurrence(s): " + ", ".join(counts))

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


def _best_per_asset(rows, key):
    """The best (nearest) row per asset - the by-asset view shows one row
    per asset even when an asset has several channel drawings (the
    detailed reports still list every drawing)."""
    best = {}
    for sym, ev, price in rows:
        if sym not in best or key(ev) < key(best[sym][0]):
            best[sym] = (ev, price)
    return best


def print_fused_view(res_channels, names_channels, res_supertrend,
                     names_supertrend, args, sections=None):
    """The both-scans-by-asset view appended after the two reports in --all
    mode (the user's request): one row per asset with its channel condition
    and its supertrend condition side by side, '-' when the asset has only
    one of them, sorted by the assets' display names (case-insensitive,
    the user's choice) - so it is easy to see which assets have both
    conditions and which only one. Two tables: near a channel line /
    touching the supertrend line, and broken channel / supertrend flip -
    each table's title carrying its day (the --date day or the scan's
    day), like every other section's title (the user's request); each is
    closed by the count of assets with both conditions, only the
    channel's and only the supertrend's. The broken/flip summary then
    breaks its events down (the user's request): the broken channels by
    the line they broke and the flips by their direction, each count with
    its share of that event type's total (a breakdown line only prints
    when that type has assets). The color coding is the reports'
    one (Ascending/Upper/Up in green, Descending/Lower/Down in red).

    sections is the scanner's section mode (the --near/--broken flags):
    the list of the only sections to print, in this view's order - None
    prints both tables (the established full listing). A section with no
    assets prints its "No ..." line, so a section-only run always shows
    that the scan ran; the leading blank line only separates the view
    from the reports above (a section-only run starts the output)."""
    use_color = not args.no_color

    names = dict(names_channels)
    names.update(names_supertrend)

    def asset_key(sym):
        return (names.get(sym, sym).casefold(), sym)

    chan_near = _best_per_asset(res_channels['near'],
                                lambda ev: ev['proximity'])
    st_near = {sym: (ev, price) for sym, ev, price in res_supertrend['touching']}
    chan_broken = _best_per_asset(res_channels['broken'],
                                  lambda ev: ev['beyond'])
    st_flip = {sym: (ev, price) for sym, ev, price in res_supertrend['surpassed']}

    show_near = sections is None or 'near' in sections
    show_broken = sections is None or 'broken' in sections

    date_str = (getattr(args, 'date', None)
                or res_supertrend['generated'].strftime('%Y-%m-%d'))
    print(("" if sections else "\n")
          + f"Both scans by asset {date_str} - each asset's channel condition and its "
          f"supertrend condition (period {args.period}, multiplier "
          f"{args.multiplier:g}) side by side (sorted by asset name):")

    def counts(syms, left, right):
        both = sum(1 for s in syms if s in left and s in right)
        only_left = sum(1 for s in syms if s in left and s not in right)
        return both, only_left, len(syms) - both - only_left

    def pct(value):
        return f"{value:.2f}%" if value != float('inf') else "?%"

    if show_near:
        # NEAR A CHANNEL LINE / TOUCHING THE SUPERTREND LINE
        syms = sorted(set(chan_near) | set(st_near), key=asset_key)
        if not syms:
            print("No assets near a channel line or touching the supertrend line")
        else:
            ch_rest = {s: f"{chan_near[s][0]['proximity']:.2f}% "
                          f"({chan_near[s][0]['line_value']:.2f})"
                       for s in syms if s in chan_near}
            st_rest = {s: f"{st_near[s][0]['proximity']:.2f}% "
                          f"({st_near[s][0]['line_value']:.2f})"
                       for s in syms if s in st_near}
            name_w = max(max(len(names[s]) for s in syms), len('ASSET'))
            # each cell starts with two fixed-width colored words (10 + 6 for
            # the channel cell, 4 + 6 for the supertrend one) plus the spaces
            ch_w = max(18 + max((len(r) for r in ch_rest.values()), default=0),
                       len('NEAR CHANNEL LINE'))
            st_w = max(12 + max((len(r) for r in st_rest.values()), default=0),
                       len('NEAR SUPERTREND LINE'))
            print(f"NEAR A CHANNEL LINE / TOUCHING THE SUPERTREND LINE {date_str}")
            print(f"{'ASSET':<{name_w}}  {'NEAR CHANNEL LINE':<{ch_w}}  "
                  f"{'NEAR SUPERTREND LINE':<{st_w}}  {'AGE':>5}  {'LAST CLOSE':>12}")
            for s in syms:
                price = (chan_near[s] if s in chan_near else st_near[s])[1]
                if s in chan_near:
                    ev, _ = chan_near[s]
                    kind = colored(f"{ev['kind']:<10}",
                                   GREEN if ev['kind'] == 'Ascending' else RED,
                                   use_color)
                    word = colored(f"{ev['near']:<6}",
                                   GREEN if ev['near'] == 'Upper' else RED,
                                   use_color)
                    ch_cell = f"{kind} {word} {ch_rest[s]:<{ch_w - 18}}"
                else:
                    ch_cell = '-'.ljust(ch_w)
                if s in st_near:
                    ev, _ = st_near[s]
                    trend = colored(f"{ev['trend']:<4}",
                                    GREEN if ev['trend'] == 'Up' else RED, use_color)
                    word = colored(f"{ev['line']:<6}",
                                   GREEN if ev['line'] == 'Upper' else RED,
                                   use_color)
                    st_cell = f"{trend} {word} {st_rest[s]:<{st_w - 12}}"
                    age = f"{ev['age']:>5}"
                else:
                    st_cell = '-'.ljust(st_w)
                    age = f"{'-':>5}"
                print(f"{names[s]:<{name_w}}  {ch_cell}  {st_cell}  {age}  "
                      f"{price:>12.2f}")
            n_both, n_ch, n_st = counts(syms, chan_near, st_near)
            print(f"\n{len(syms)} asset(s): {n_both} with both conditions, "
                  f"{n_ch} only near the channel, {n_st} only touching the supertrend")

    if show_near and show_broken:
        print()
    if show_broken:
        # BROKEN CHANNEL / SUPERTREND FLIP
        syms = sorted(set(chan_broken) | set(st_flip), key=asset_key)
        if not syms:
            print("No assets with a broken channel or a supertrend flip")
        else:
            ch_rest = {s: f"({chan_broken[s][0]['line_value']:.2f})"
                       for s in syms if s in chan_broken}
            st_rest = {s: f"({st_flip[s][0]['line_value']:.2f})"
                       for s in syms if s in st_flip}
            name_w = max(max(len(names[s]) for s in syms), len('ASSET'))
            # both cells: two fixed-width colored words, 'beyond '/' flipped ',
            # the beyond % and the line word = 32 chars before the value
            ch_w = max(32 + max((len(r) for r in ch_rest.values()), default=0),
                       len('CHANNEL BROKEN'))
            st_w = max(32 + max((len(r) for r in st_rest.values()), default=0),
                       len('SUPERTREND FLIP'))
            print(f"BROKEN CHANNEL / SUPERTREND FLIP {date_str}")
            print(f"{'ASSET':<{name_w}}  {'CHANNEL BROKEN':<{ch_w}}  "
                  f"{'SUPERTREND FLIP':<{st_w}}  {'LAST CLOSE':>12}")
            for s in syms:
                price = (chan_broken[s] if s in chan_broken else st_flip[s])[1]
                if s in chan_broken:
                    ev, _ = chan_broken[s]
                    kind = colored(f"{ev['kind']:<10}",
                                   GREEN if ev['kind'] == 'Ascending' else RED,
                                   use_color)
                    word = colored(f"{ev['broken_line']:<6}",
                                   GREEN if ev['broken_line'] == 'Upper' else RED,
                                   use_color)
                    ch_cell = (f"{kind} beyond {word} {pct(ev['beyond']):>6} "
                               f"{ch_rest[s]:<{ch_w - 32}}")
                else:
                    ch_cell = '-'.ljust(ch_w)
                if s in st_flip:
                    ev, _ = st_flip[s]
                    old = colored(f"{ev['old_trend']:<4}",
                                  GREEN if ev['old_trend'] == 'Up' else RED,
                                  use_color)
                    new = colored(f"{ev['trend']:<4}",
                                  GREEN if ev['trend'] == 'Up' else RED,
                                  use_color)
                    word = colored(f"{ev['line']:<6}",
                                   GREEN if ev['line'] == 'Upper' else RED,
                                   use_color)
                    st_cell = (f"{old} flipped {new} {pct(ev['beyond']):>6} "
                               f"{word} {st_rest[s]:<{st_w - 32}}")
                else:
                    st_cell = '-'.ljust(st_w)
                print(f"{names[s]:<{name_w}}  {ch_cell}  {st_cell}  "
                      f"{price:>12.2f}")
            n_both, n_ch, n_st = counts(syms, chan_broken, st_flip)
            print(f"\n{len(syms)} asset(s): {n_both} with both conditions, "
                  f"{n_ch} only the broken channel, {n_st} only the supertrend flip")
            # the events' breakdown (the user's request): the broken
            # channels by the line they broke and the flips by their
            # direction, each count with its share of that event type's
            # total - over the assets the table lists (an asset with
            # several broken drawings shows one, its closest break)
            if chan_broken:
                n_upper = sum(1 for s in chan_broken
                              if chan_broken[s][0]['broken_line'] == 'Upper')
                n_lower = len(chan_broken) - n_upper
                print(f"Broken channels: {len(chan_broken)} - "
                      f"{colored(f'{n_upper} Upper', GREEN, use_color)} "
                      f"({n_upper / len(chan_broken) * 100:.2f}%), "
                      f"{colored(f'{n_lower} Lower', RED, use_color)} "
                      f"({n_lower / len(chan_broken) * 100:.2f}%)")
            if st_flip:
                n_up = sum(1 for s in st_flip
                           if st_flip[s][0]['trend'] == 'Up')
                n_down = len(st_flip) - n_up
                print(f"Supertrend flips: {len(st_flip)} - "
                      f"{colored(f'{n_up} Up', GREEN, use_color)} "
                      f"({n_up / len(st_flip) * 100:.2f}%), "
                      f"{colored(f'{n_down} Down', RED, use_color)} "
                      f"({n_down / len(st_flip) * 100:.2f}%)")


# ====================================================================
# status - the per-asset snapshot (and its whole-history mode)
# ====================================================================
# One row per asset (sorted by its display name) with: the last close,
# colored by its daily move; the DAY % column (the percent change along
# the day) and the WEEK % column next to it (the percent change along
# the last week, vs the last close at least 7 days older); the LAST
# UPDATE date (when the shown data was last refreshed - the source
# asset's row for copies, '-' when never updated); the nearest drawn
# channel: its kind (Ascending green, Descending red) and the
# percentage distances to the upper and lower lines, with the CH BREAK
# column (the line the close went beyond: Upper green, Lower red, '-'
# while inside); and the supertrend bands: the percentage distances to
# the Up line - the support below the price - and the Down line - the
# resistance above it - with the ST BREAK column (the band the close
# went beyond, same coding). '-' marks what does not apply (no channel,
# or too few bars for the supertrend's warm-up); assets without any bars
# are listed in the Skipped note. --date shows the status AS OF a past
# date; --history (with --asset) shows the asset's WHOLE daily history,
# one row per bar since the begin (the oldest day first), each row with
# exactly the same columns as the status of that day - the row's own day
# in the LAST UPDATE column.

def _load_status_bars(conn, symbol):
    """(timestamps, highs, lows, closes) of the asset's daily bars in
    stored order, as numpy arrays - the status needs the timestamps (the
    week window, the --date cutoff) on top of the supertrend's arrays;
    empty arrays when the asset has no bars table."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT timestamp, high, low, close FROM "{symbol}_bars" '
                     f'ORDER BY timestamp')
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        return np.array([]), np.array([]), np.array([]), np.array([])
    data = np.array(rows, dtype=float)
    return data[:, 0], data[:, 1], data[:, 2], data[:, 3]


def _distance_pct(close, line_value):
    """The percentage distance of the close from a line value (relative to
    the line's value, the scanner convention); inf for a ~zero line."""
    if abs(line_value) < 1e-12:
        return float('inf')
    return abs(close - line_value) / abs(line_value) * 100.0


def _nearest_channel(conn, symbol, close, n_bars):
    """The asset's nearest channel evaluation (the closest of its upper
    and lower lines, the by-asset view's convention), None when the
    asset has no usable channel drawing."""
    best = None
    for channel in load_channels(conn, symbol):
        ev = evaluate_channel(channel, close, n_bars)
        if ev is None:
            continue
        distance = min(_distance_pct(close, ev['lower']),
                       _distance_pct(close, ev['upper']))
        if best is None or distance < best[0]:
            best = (distance, ev)
    return best[1] if best else None


def _print_status_table(rows, use_color):
    """The status listing's table: the twelve columns with the established
    colors (CLOSE and DAY % by the daily move, WEEK % by its own sign,
    Ascending/Upper/Up in green, Descending/Lower/Down in red, '-' plain)
    - shared by the per-asset listing and the --history mode, so both
    print exactly the same columns (the user's request)."""
    def cell(value):
        return f"{value:.2f}%" if value is not None and value != float('inf') else '-'

    headers = ['ASSET', 'CLOSE', 'DAY %', 'WEEK %', 'LAST UPDATE', 'CHANNEL',
               'TO UPPER', 'TO LOWER', 'CH BREAK', 'TO UP LINE',
               'TO DOWN LINE', 'ST BREAK']
    aligns = ['<', '>', '>', '>', '<', '<', '>', '>', '<', '>', '>', '<']
    plain = [(r['name'], fmt_price(r['close']), fmt_gain(r['change']),
              fmt_gain(r['week']), r['updated'],
              r['channel']['kind'] if r['channel'] else '-',
              cell(r['ch_upper']), cell(r['ch_lower']),
              r['ch_break'] or '-',
              cell(r['st_up']), cell(r['st_down']),
              r['st_break'] or '-')
             for r in rows]
    widths = [max(len(headers[i]), max((len(p[i]) for p in plain), default=0))
              for i in range(len(headers))]

    header = '  '.join(f"{headers[i]:{aligns[i]}{widths[i]}}"
                       for i in range(len(headers)))
    print(header)
    for r, p in zip(rows, plain):
        # pad first, colorize after: the f-string widths would count the
        # invisible ANSI escape characters otherwise
        cells = [f"{p[i]:{aligns[i]}{widths[i]}}" for i in range(len(headers))]
        # CLOSE and DAY %: green when the daily move went up, red when
        # down, plain when it did not move or there is no previous bar
        close_color = None
        if r['up'] is True:
            close_color = GREEN
        elif r['up'] is False:
            close_color = RED
        cells[1] = colored(cells[1], close_color, use_color)
        cells[2] = colored(cells[2], close_color, use_color)
        # WEEK %: colored by its own sign (green up, red down, plain flat)
        week_color = None
        if r['week'] is not None:
            if r['week'] > 0:
                week_color = GREEN
            elif r['week'] < 0:
                week_color = RED
        cells[3] = colored(cells[3], week_color, use_color)
        # LAST UPDATE stays plain (cells[4]); CHANNEL: the established
        # coding (Ascending green, Descending red)
        kind_color = None
        if r['channel']:
            kind_color = GREEN if r['channel']['kind'] == 'Ascending' else RED
        cells[5] = colored(cells[5], kind_color, use_color)
        # CH BREAK / ST BREAK: beyond the upper line green, beyond the
        # lower line red (the established coding); '-' stays plain
        ch_break_color = None
        if r['ch_break'] == 'Upper':
            ch_break_color = GREEN
        elif r['ch_break'] == 'Lower':
            ch_break_color = RED
        cells[8] = colored(cells[8], ch_break_color, use_color)
        # the supertrend distances: the Up line green, the Down line red
        cells[9] = colored(cells[9], GREEN if r['st_up'] is not None else None,
                           use_color)
        cells[10] = colored(cells[10], RED if r['st_down'] is not None else None,
                            use_color)
        st_break_color = None
        if r['st_break'] == 'Upper':
            st_break_color = GREEN
        elif r['st_break'] == 'Lower':
            st_break_color = RED
        cells[11] = colored(cells[11], st_break_color, use_color)
        print('  '.join(cells))


def print_history(args, conn, cutoff):
    """The --history mode: ONE asset's whole daily history - one row per
    bar since the begin, the OLDEST day first (the user's choice) - each
    row with exactly the same columns as the status of that day: the
    close colored by its daily move, DAY %, WEEK % (vs the last close at
    least 7 days older), the row's own day in the LAST UPDATE column, the
    nearest channel evaluated at that bar (the drawings are anchored at
    bar positions) with its line distances and CH BREAK, and the
    supertrend of that day with its line distances and ST BREAK ('-'
    while in the warm-up or without a channel). The supertrend runs ONCE
    over the whole history (the computation is causal - the bands at a
    bar only depend on the bars up to it), so each row shows what a
    --date scan of that day would show. --date ends the history at that
    day."""
    use_color = not args.no_color
    if args.asset not in get_assets(conn):
        print(f"Asset not found in the database: {args.asset}")
        return
    name = get_display_name(conn, args.asset) or args.asset
    bars_symbol = get_source_symbol(conn, args.asset) or args.asset
    timestamps, high, low, close = _load_status_bars(conn, bars_symbol)
    if cutoff is not None:
        keep = timestamps < cutoff
        timestamps, high, low, close = (timestamps[keep], high[keep],
                                        low[keep], close[keep])
    n_bars = len(close)
    if n_bars == 0:
        print(f"{args.asset}: no price data"
              + (f" up to {args.date}" if args.date else "")
              + (f" (source {bars_symbol})"
                 if bars_symbol != args.asset else ""))
        return

    # the supertrend over the whole history: one pass, every bar's bands
    # (the chart pair: the active ratcheted line + the basic recomputed
    # line on the other side; NaN while in the warm-up)
    direction, line, flip, lower_band, upper_band, basic_lower, basic_upper = \
        supertrend(high, low, close, args.period, args.multiplier)
    support = np.where(direction == 1, lower_band, basic_lower)
    resistance = np.where(direction == 1, basic_upper, upper_band)

    # the channels, loaded once (the nearest evaluated at each bar)
    channels = load_channels(conn, args.asset)

    def nearest_channel(price, t):
        best = None
        for channel in channels:
            ev = evaluate_channel(channel, price, t + 1)
            if ev is None:
                continue
            distance = min(_distance_pct(price, ev['lower']),
                           _distance_pct(price, ev['upper']))
            if best is None or distance < best[0]:
                best = (distance, ev)
        return best[1] if best else None

    rows = []
    for t in range(n_bars):
        c = float(close[t])
        ts = float(timestamps[t])
        prev = float(close[t - 1]) if t >= 1 else None
        # the daily percent change (the same move that colors the close)
        change = (c - prev) / prev * 100.0 if prev else None
        # the weekly percent change: vs the last close at least 7 days older
        week = None
        older = timestamps <= (ts - 7 * 86400)
        if older.any():
            week_close = float(close[older][-1])
            if week_close:
                week = (c - week_close) / week_close * 100.0
        # the daily move: True up, False down, None flat or unknown
        up = None
        if prev:
            if c > prev:
                up = True
            elif c < prev:
                up = False
        # the nearest drawn channel at this bar, with its two distances
        channel = nearest_channel(c, t)
        ch_upper = _distance_pct(c, channel['upper']) if channel else None
        ch_lower = _distance_pct(c, channel['lower']) if channel else None
        ch_break = None
        if channel and channel['status'] == 'broken':
            ch_break = channel['broken_line']
        # the supertrend of that day: the Up line (the support) and the
        # Down line (the resistance), with the range break
        st_up = st_down = st_break = None
        if not np.isnan(support[t]) and not np.isnan(resistance[t]):
            st_up = _distance_pct(c, float(support[t]))
            st_down = _distance_pct(c, float(resistance[t]))
            if c > resistance[t]:
                st_break = 'Upper'
            elif c < support[t]:
                st_break = 'Lower'
        rows.append({
            'symbol': args.asset,
            'name': name,
            'close': c,
            # the row's own day: each row of the history is the status of
            # ITS day (the LAST UPDATE column identifies the row)
            'updated': datetime.fromtimestamp(int(ts)).strftime('%Y-%m-%d'),
            'change': change, 'week': week, 'up': up,
            'channel': channel,
            'ch_upper': ch_upper, 'ch_lower': ch_lower, 'ch_break': ch_break,
            'st_up': st_up, 'st_down': st_down, 'st_break': st_break,
        })

    date_str = args.date if args.date is not None \
        else datetime.now().strftime('%Y-%m-%d')
    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Status history {name} {date_str} (period {args.period}, "
          f"multiplier {args.multiplier:g}) - one row per day since the "
          "begin, the status columns at each day:")
    print(f"{len(rows)} day(s) - from {rows[0]['updated']} "
          f"to {rows[-1]['updated']}\n")
    _print_status_table(rows, use_color)


def build_status_parser(parser):
    """The status command's flags."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="show a single asset instead of all")
    parser.add_argument('--date', default=None, type=_date_arg, metavar='YYYY-MM-DD',
                        help="show the status as of this past date (the last bar on "
                             "or before it, with its own daily and weekly changes, "
                             "channel and supertrend)")
    parser.add_argument('--history', action='store_true',
                        help="with --asset: the asset's WHOLE daily history - one "
                             "row per bar since the begin (the oldest day first), "
                             "each with the same columns as the status of that "
                             "day; --date ends the history at that day")
    parser.add_argument('--period', type=int, default=SUPERTREND_PERIOD,
                        help=f"the ATR period of the supertrend (default: {SUPERTREND_PERIOD})")
    parser.add_argument('--multiplier', type=float, default=SUPERTREND_MULTIPLIER,
                        help=f"the supertrend multiplier (default: {SUPERTREND_MULTIPLIER:g})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run_status(args):

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    use_color = not args.no_color
    conn = sqlite3.connect(args.db)

    # --date: the status as of a past date - only the bars strictly before
    # the end of that date (None = today, the whole history)
    cutoff = None
    if args.date is not None:
        cutoff = datetime.strptime(args.date, '%Y-%m-%d').timestamp() + 86400

    # the --history mode: one asset's whole daily history, one row per bar
    # - the same columns as the status at each day; it takes over the run
    if args.history:
        if args.asset is None:
            print("The --history status needs --asset (one asset's whole "
                  "daily history)")
            sys.exit(1)
        print_history(args, conn, cutoff)
        conn.close()
        return

    rows, skipped = [], []
    for symbol in get_assets(conn):
        if args.asset is not None and symbol != args.asset:
            continue
        bars_symbol = get_source_symbol(conn, symbol) or symbol
        timestamps, high, low, close = _load_status_bars(conn, bars_symbol)
        if cutoff is not None:
            keep = timestamps < cutoff
            timestamps, high, low, close = (timestamps[keep], high[keep],
                                             low[keep], close[keep])
        n_bars = len(close)
        if n_bars == 0:
            skipped.append(f"{symbol}: no price data"
                           + (f" up to {args.date}" if args.date else "")
                           + (f" (source {bars_symbol})" if bars_symbol != symbol else ""))
            continue
        last_close = float(close[-1])
        last_ts = float(timestamps[-1])
        prev_close = float(close[-2]) if n_bars >= 2 else None
        # the last update date: when the shown data was last refreshed -
        # the source asset's row for copies (their bars come from it)
        updated = '-'
        row = conn.execute('SELECT last_updated FROM symbols WHERE symbol = ?',
                           (bars_symbol,)).fetchone()
        if row and row[0]:
            updated = datetime.fromtimestamp(int(row[0])).strftime('%Y-%m-%d')
        # the daily percent change (the same move that colors the close)
        change = None
        if prev_close:
            change = (last_close - prev_close) / prev_close * 100.0
        # the weekly percent change: vs the last close at least 7 days
        # older than the as-of bar
        week_change = None
        older = timestamps <= (last_ts - 7 * 86400)
        if older.any():
            week_close = float(close[older][-1])
            if week_close:
                week_change = (last_close - week_close) / week_close * 100.0
        # the daily move: True up, False down, None flat or unknown
        daily_move = None
        if prev_close:
            if last_close > prev_close:
                daily_move = True
            elif last_close < prev_close:
                daily_move = False

        # the nearest drawn channel and its two line distances
        channel = _nearest_channel(conn, symbol, last_close, n_bars)
        ch_upper = _distance_pct(last_close, channel['upper']) if channel else None
        ch_lower = _distance_pct(last_close, channel['lower']) if channel else None
        # the channel break: the close is beyond the shown channel's
        # upper or lower line
        ch_break = None
        if channel and channel['status'] == 'broken':
            ch_break = channel['broken_line']

        # the supertrend bands: the Up line (the support below the price,
        # the lower band) and the Down line (the resistance above it)
        st_up = st_down = st_break = None
        if n_bars >= args.period + 2:
            direction, line, flip, lower_band, upper_band, basic_lower, \
                basic_upper = supertrend(high, low, close, args.period,
                                         args.multiplier)
            t = n_bars - 1
            if direction[t] != 0:
                # the supertrend channel as the chart draws it: the ACTIVE
                # ratcheted line + the freshly recomputed basic line on
                # the other side (the Up line = the support, the Down
                # line = the resistance)
                if direction[t] == 1:
                    support, resistance = (float(lower_band[t]),
                                           float(basic_upper[t]))
                else:
                    support, resistance = (float(basic_lower[t]),
                                           float(upper_band[t]))
                st_up = _distance_pct(last_close, support)
                st_down = _distance_pct(last_close, resistance)
                # the supertrend range break: the close is beyond one of
                # the channel lines
                if last_close > resistance:
                    st_break = 'Upper'
                elif last_close < support:
                    st_break = 'Lower'

        rows.append({
            'symbol': symbol,
            'name': get_display_name(conn, symbol) or symbol,
            'close': last_close,
            'updated': updated,
            'change': change,
            'week': week_change,
            'up': daily_move,
            'channel': channel,
            'ch_upper': ch_upper, 'ch_lower': ch_lower,
            'ch_break': ch_break,
            'st_up': st_up, 'st_down': st_down,
            'st_break': st_break,
        })
    conn.close()

    rows.sort(key=lambda r: (r['name'].casefold(), r['symbol']))

    # the date of the data in the title (the --date day, or today)
    date_str = args.date if args.date is not None \
        else datetime.now().strftime('%Y-%m-%d')
    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Status {date_str} (period {args.period}, multiplier {args.multiplier:g}) - "
          "the last close colored by its daily move (green up, red down),")
    print("the channel and the supertrend line distances")
    print(f"{len(rows)} asset(s)\n")

    if not rows:
        if args.asset is not None and not skipped:
            print(f"Asset not found in the database: {args.asset}")
        elif args.date is not None:
            print(f"No asset has price data up to {args.date}")
        else:
            print("No assets in the database")
    else:
        _print_status_table(rows, use_color)

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


# ====================================================================
# list - the exchange product listings (phemex, pionex)
# ====================================================================

PHEMEX_TYPE_CHOICES = ('perp', 'tradfi', 'tokenized', 'crypto', 'all')
PHEMEX_DEFAULT_TYPES = ('perp', 'tradfi', 'tokenized')
PHEMEX_CATEGORY_LABELS = PHEMEX_CATEGORY_LABELS
PHEMEX_CATEGORY_ORDER = {'perp': 0, 'tradfi': 1, 'tokenized': 2, 'crypto': 3}
PHEMEX_CATEGORY_TITLES = {'perp': 'crypto perp futures',
                          'tradfi': 'perp futures on tokenized assets '
                                    '(stocks, indices, commodities)',
                          'tokenized': 'tokenized assets (spot)',
                          'crypto': 'normal crypto spot pairs',
                          'all': 'all products'}


def build_phemex_parser(parser):
    """The list phemex command's flags."""
    parser.add_argument('--search', default=None,
                        help="keep only products matching this text (symbol, description or asset name)")
    parser.add_argument('--type', choices=PHEMEX_TYPE_CHOICES, default=None,
                        help="perp: only crypto perp futures | tradfi: only perps on tokenized "
                             "stocks/indices/commodities | tokenized: only spot tokenized assets | "
                             "crypto: only normal crypto spot pairs | all: everything "
                             "(default: perps + tokenized assets)")
    parser.add_argument('--quote', default=None,
                        help="keep only products quoted in this currency (e.g. USDT)")
    parser.add_argument('--all', action='store_true',
                        help="include delisted products (a STATUS column is added)")


def run_phemex(args):
    """The Phemex products fetched live from the public Phemex API, with
    the exact symbol you can type in the pystalker Download flow: by
    default the perp futures and the tokenized assets (the crypto perps,
    the TradFi perps on tokenized stocks/indices/commodities and the
    spot tokenized assets), --type crypto for the normal crypto spot
    pairs, --type all for everything. The product list and the asset
    categories come from the same PhemexProvider the application uses,
    so the symbols seen here are always the ones the application will
    download."""
    provider = PhemexProvider()
    try:
        products = provider.get_products()
    except Exception as e:
        print(f"Could not get the Phemex product list: {e}")
        sys.exit(1)

    if not products:
        print("Phemex returned an empty product list")
        sys.exit(1)

    if args.type:
        categories = set(PHEMEX_TYPE_CHOICES[:-1]) if args.type == 'all' \
            else {args.type}
    else:
        categories = set(PHEMEX_DEFAULT_TYPES)

    total = len(products)
    rows = []
    for p in products:
        symbol = p.get('symbol') or ''
        display = p.get('displaySymbol') or ''
        quote = p.get('quoteCurrency') or ''
        status = p.get('status') or ''
        category = provider.classify_product(p)
        name = provider.get_product_name(p)
        if not args.all and status != 'Listed':
            continue
        if category not in categories:
            continue
        if args.quote and quote.upper() != args.quote.upper():
            continue
        if args.search:
            text = args.search.strip().lower()
            if not any(text in s.lower() for s in (symbol, display, name)):
                continue
        rows.append((symbol, category, display, name, quote, status))

    rows.sort(key=lambda r: (PHEMEX_CATEGORY_ORDER[r[1]], r[0]))

    listed = sum(1 for p in products if p.get('status') == 'Listed')
    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    title = PHEMEX_CATEGORY_TITLES[args.type] if args.type \
        else "perp futures and tokenized assets"
    scope = f"matching \"{args.search}\" " if args.search else ""
    print(f"Phemex {title} {scope}- {len(rows)} shown "
          f"({listed} listed products, {total} including delisted)\n")

    if not rows:
        print("No product matches the filters")
        return

    sym_w = max(max(len(r[0]) for r in rows), len('SYMBOL'))
    cat_w = max(max(len(PHEMEX_CATEGORY_LABELS[r[1]]) for r in rows), len('CATEGORY'))
    desc_w = max(max(len(r[2]) for r in rows), len('DESCRIPTION'))
    name_w = max(max(len(r[3]) for r in rows), len('NAME'))
    quote_w = max(max(len(r[4]) for r in rows), len('QUOTE'))
    header = (f"{'SYMBOL':<{sym_w}}  {'CATEGORY':<{cat_w}}  {'DESCRIPTION':<{desc_w}}  "
              f"{'NAME':<{name_w}}  {'QUOTE':<{quote_w}}")
    if args.all:
        header += f"  {'STATUS':<9}"
    print(header)
    for symbol, category, display, name, quote, status in rows:
        line = (f"{symbol:<{sym_w}}  {PHEMEX_CATEGORY_LABELS[category]:<{cat_w}}  "
                f"{display:<{desc_w}}  {name:<{name_w}}  {quote:<{quote_w}}")
        if args.all:
            line += f"  {status:<9}"
        print(line)

    counts = {}
    for _, category, _, _, _, _ in rows:
        counts[PHEMEX_CATEGORY_LABELS[category]] = \
            counts.get(PHEMEX_CATEGORY_LABELS[category], 0) + 1
    breakdown = ", ".join(f"{n} {c.lower()}" for c, n in counts.items())
    print(f"\n{len(rows)} product(s): {breakdown}")


PIONEX_TYPE_CHOICES = ('all', 'spot', 'perp')


def _pionex_enabled(product: dict) -> bool:
    """Spot products carry an `enable` flag; perpetuals a trading status."""
    if 'enable' in product:
        return bool(product['enable'])
    return product.get('status') == 'TRADING'


def build_pionex_parser(parser):
    """The list pionex command's flags."""
    parser.add_argument('--search', default=None,
                        help="keep only products matching this text (symbol, base or quote)")
    parser.add_argument('--type', choices=PIONEX_TYPE_CHOICES, default='all',
                        help="spot: only spot pairs | perp: only perpetual futures | all (default)")
    parser.add_argument('--all', action='store_true',
                        help="include disabled products (a STATUS column is added)")


def run_pionex(args):
    """Every Pionex product (the spot pairs like BTC_USDT - including
    their tokenized assets like AAPLX_USDT - and the perpetual futures
    like BTC_USDT_PERP), fetched live from the public Pionex API, with
    the exact symbol you can type in the pystalker Download flow; the
    product list comes from the same PionexProvider the application
    uses."""
    try:
        products = PionexProvider().get_symbols()
    except Exception as e:
        print(f"Could not get the Pionex product list: {e}")
        sys.exit(1)

    if not products:
        print("Pionex returned an empty product list")
        sys.exit(1)

    rows = []
    for p in products:
        symbol = p.get('symbol') or ''
        ptype = p.get('type') or ''
        base = p.get('baseCurrency') or ''
        quote = p.get('quoteCurrency') or ''
        name = p.get('name') or ''
        # spot products carry an `enable` flag; perpetuals a trading status
        enabled = bool(p['enable']) if 'enable' in p else p.get('status') == 'TRADING'
        if not args.all and not enabled:
            continue
        if args.type == 'spot' and ptype != 'SPOT':
            continue
        if args.type == 'perp' and ptype != 'PERP':
            continue
        if args.search:
            text = args.search.strip().lower()
            if not any(text in value.lower() for value in (symbol, base, quote, name)):
                continue
        rows.append((symbol, ptype, base, quote, name,
                     'Enabled' if enabled else 'Disabled'))
    rows.sort(key=lambda r: (0 if r[1] == 'SPOT' else 1, r[0]))

    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    scope = f"matching \"{args.search}\" " if args.search else ""
    print(f"Pionex products {scope}- {len(rows)} shown "
          f"({sum(1 for p in products if _pionex_enabled(p))} enabled, "
          f"{len(products)} total)\n")

    if not rows:
        print("No product matches the filters")
        return

    sym_w = max(max(len(r[0]) for r in rows), len('SYMBOL'))
    type_w = 4
    base_w = max(max(len(r[2]) for r in rows), len('BASE'))
    quote_w = max(max(len(r[3]) for r in rows), len('QUOTE'))
    name_w = max(max(len(r[4]) for r in rows), len('NAME'))
    header = (f"{'SYMBOL':<{sym_w}}  {'TYPE':<{type_w}}  "
              f"{'BASE':<{base_w}}  {'QUOTE':<{quote_w}}  {'NAME':<{name_w}}")
    if args.all:
        header += f"  {'STATUS':<9}"
    print(header)
    for symbol, ptype, base, quote, name, status in rows:
        line = (f"{symbol:<{sym_w}}  {ptype:<{type_w}}  "
                f"{base:<{base_w}}  {quote:<{quote_w}}  {name:<{name_w}}")
        if args.all:
            line += f"  {status:<9}"
        print(line)

    spot_count = sum(1 for r in rows if r[1] == 'SPOT')
    perp_count = sum(1 for r in rows if r[1] == 'PERP')
    print(f"\n{len(rows)} product(s): {spot_count} spot, {perp_count} perpetual")


# ====================================================================
# the unified command line
# ====================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='pystalker_cli.py',
        description="The unified PyStalker command-line tool "
                    "(operations, update, scanner, status, list)")
    sub = parser.add_subparsers(dest='command', metavar='command')

    sub_parser = sub.add_parser('operations',
                                help="list the trading operations journal")
    build_operations_parser(sub_parser)
    sub_parser.set_defaults(func=run_operations)

    sub_parser = sub.add_parser('update',
                                help="update all assets' data from their "
                                     "data sources")
    build_update_parser(sub_parser)
    sub_parser.set_defaults(func=run_update)

    sub_parser = sub.add_parser('scanner',
                                help="scan the drawn channels and/or the "
                                     "supertrend indicator (default: both)")
    build_scanner_parser(sub_parser)
    sub_parser.set_defaults(func=run_scanner)

    sub_parser = sub.add_parser('status',
                                help="the last close with its daily and "
                                     "weekly changes, last update date, "
                                     "channel and supertrend distances of "
                                     "every asset")
    build_status_parser(sub_parser)
    sub_parser.set_defaults(func=run_status)

    # list: the second argument is the exchange
    list_parser = sub.add_parser(
        'list', help="list the assets of an exchange (phemex, pionex)")
    list_sub = list_parser.add_subparsers(dest='exchange', metavar='exchange',
                                          required=True)
    for exchange, builder, runner in (('phemex', build_phemex_parser,
                                        run_phemex),
                                       ('pionex', build_pionex_parser,
                                        run_pionex)):
        exchange_parser = list_sub.add_parser(
            exchange, help=f"the {exchange} products")
        builder(exchange_parser)
        exchange_parser.set_defaults(func=runner)

    args = parser.parse_args(argv)
    if args.command is None:
        # running the program without any command: show the help screen
        # with all the commands instead of the usage error
        parser.print_help()
        return
    args.func(args)


if __name__ == '__main__':
    main()
