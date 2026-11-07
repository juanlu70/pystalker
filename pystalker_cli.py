#!/usr/bin/env python3
"""
pystalker_cli.py - The unified PyStalker command-line tool

One self-contained program: every console tool the CLI executes is
integrated in this file as a command (operations, update, scanner,
status, list). The console_programs/ directory keeps only the tools the
CLI does not run - the volatility prediction/accuracy suite, the
bar-fixing tools and prob_target; the scanning logic itself lives in
pystalker/core/ and is shared with the application.

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
               line, trend flips); bare or --all scans both at once and
               appends the both-scans-by-asset view (each asset's two
               conditions side by side, sorted by asset name, with the
               both/only-one counts); --channels or --supertrend scans
               one alone.
    --channels/--supertrend/--all --db --max-proximity --asset
    --lower-than(channels) --period/--multiplier(supertrend) --no-color

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
               supertrend bands (the percentage distances to the Up
               line - the support below the price - and the Down line -
               the resistance above) with the ST BREAK column (the band
               the close went beyond); '-' marks what does not apply.
               --date YYYY-MM-DD shows the status as of a past date
               (the last bar on or before it, with its own daily and
               weekly changes, channel and supertrend).
    --db --asset --date --period --multiplier --no-color

  list         The assets of an exchange - the second argument is the
               exchange: "list phemex" or "list pionex".
    --search --type --quote(phemex) --all

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
  python pystalker_cli.py status
  python pystalker_cli.py status --asset BTC-USD
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
                                            scan_channel_proximity)
from pystalker.core.database import Database
from pystalker.core.operations import (fmt_gain, fmt_price, get_display_name,
                                       list_operations)
from pystalker.core.providers import (PHEMEX_CATEGORY_LABELS, DataManager,
                                      PhemexProvider, PionexProvider)
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                        scan_supertrend, supertrend)

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

# the shared ANSI helpers: colors are applied AFTER the padding (the
# invisible escape codes would break the column alignment otherwise)
GREEN = '\033[32m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'


def colored(text, color, enabled=True, bold=False):
    """text wrapped in ANSI codes; the padding must already be applied."""
    if not enabled or color is None:
        return text
    prefix = (BOLD if bold else '') + color
    return f"{prefix}{text}{RESET}"


# === operations: the trading journal =======================================
# The Trading -> Operations list from the terminal, split into the same
# three groups as the application's tabs (OPEN / PLANNED / CLOSED): the
# entry date, the asset (its personalized name), the PAPER and PLANNED
# flags, Long/Short, entry price, the stop price, volume, leverage, the
# current price, the gains (NET GAIN % without leverage, the leveraged
# GAIN % and the FINAL GAIN % at the exit price - green/red like the
# application, plain for planned operations). The listing logic (and the
# gain math) is the application's own (pystalker/core/operations.py);
# the database is only read.

OPERATIONS_COLUMNS = ['ENTRY', 'ASSET', 'PAPER', 'PLANNED', 'LONG/SHORT',
                      'ENTRY PRICE', 'STOP', 'VOLUME', 'LEVERAGE',
                      'CURRENT PRICE', 'NET GAIN %', 'GAIN %', 'EXIT',
                      'EXIT PRICE', 'FINAL GAIN %']

OPERATION_GROUP_TITLES = {'open': 'OPEN OPERATIONS', 'planned': 'PLANNED OPERATIONS',
                          'closed': 'CLOSED OPERATIONS'}


def gain_color(value):
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
        sections = [(OPERATION_GROUP_TITLES[group], rows)]
    else:
        sections = [(OPERATION_GROUP_TITLES[g], [r for r in rows if r['group'] == g])
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

        widths = [max(len(OPERATIONS_COLUMNS[i]), max((len(row[i]) for row in plain_rows), default=0))
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
                cells[10] = colored(cells[10], gain_color(r['net_gain']), use_color, bold=True)
            if r['gain'] is not None and not r['planned']:
                cells[11] = colored(cells[11], gain_color(r['gain']), use_color, bold=True)
            # FINAL GAIN %: colored for real closed operations (the leveraged
            # gain at the exit price, identical to GAIN % there); plain for the
            # potential gain of open ones and the projected gain of planned ones
            if r['final_gain'] is not None and not r['open'] and not r['planned']:
                cells[14] = colored(cells[14], gain_color(r['final_gain']), use_color, bold=True)
            print('  '.join(cells))
        print()

    print(f"{len(rows)} operation(s): {result['n_open']} open, "
          f"{result['n_planned']} planned, {result['n_closed']} closed")


# === update: refresh every asset's daily bars ==============================
# The console twin of the application's "Update All Stock Data": every
# asset fetches its daily candles from the data source that serves it
# (Yahoo Finance, Phemex or Pionex - exactly like the menu point) and the
# database is merged (new bars added, existing refreshed, nothing deleted).
# Copies (assets sharing their source asset's bars) are skipped; failures
# are shown in red and never stop the run. Like the application, this
# command WRITES the database.

def bars_snapshot(database, symbol):
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
    parser.add_argument('--no-color', action='store_true', help="plain text without ANSI colors")


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
    for i, symbol in enumerate(symbols):
        source = database.load_data_source(symbol)
        before_count, _ = bars_snapshot(database, symbol)
        try:
            bar_data = data_manager.fetch_by_source(source, symbol)
            if bar_data is not None and bar_data.count() > 0:
                database.save_bars(bar_data)
                after_count, newest = bars_snapshot(database, symbol)
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
        print(colored(f"\nUpdated {len(updated)}/{len(symbols)} symbol(s)", GREEN, use_color))

    database.close()


# === scanner: the drawn channels and the supertrend indicator ==============
# The fused scanner. --channels reports the assets whose price is near a
# drawn channel line (or beyond it: the broken channels); --supertrend
# reports the assets whose close touches the active supertrend line
# (period 10, multiplier 1.8) or crossed it on the last bar (the trend
# flipped); bare or --all scans both at once and appends the
# both-scans-by-asset view: one row per asset with its two conditions
# side by side ('-' when only one), sorted by the assets' display names,
# each table closed by the both/only-one counts. The scanning logic is
# pystalker/core/channel_scanner.py and pystalker/core/supertrend.py -
# shared with the application's dialogs.

def resolve_channel_names(conn, res):
    """The personalized display names of the channel scan's listed assets
    (like Operations); resolved while the connection is still open."""
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
    print(f"Report generated: {res['generated'].strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Channel scanner - assets with price within {args.max_proximity:g}% of a channel"
          f" line{price_filter}")
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


def resolve_supertrend_names(conn, res):
    """The personalized display names of the supertrend scan's listed
    assets (like Operations); resolved while the connection is open."""
    names = {}
    for sym, _, _ in res['touching'] + res['surpassed']:
        names[sym] = get_display_name(conn, sym) or sym
    return names


def print_supertrend_report(res, names, args):
    """The supertrend scanner's report."""
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
                     names_supertrend, args):
    """The both-scans-by-asset view appended after the two reports in --all
    mode: one row per asset with its channel condition and its supertrend
    condition side by side, '-' when the asset has only one of them,
    sorted by the assets' display names (case-insensitive) - so it is easy
    to see which assets have both conditions and which only one. Two
    tables: near a channel line / touching the supertrend line, and
    broken channel / supertrend flip; each is closed by the count of
    assets with both conditions, only the channel's and only the
    supertrend's. The color coding is the reports' one (Ascending/Upper/Up
    in green, Descending/Lower/Down in red)."""
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

    print("\nBoth scans by asset - each asset's channel condition and its "
          "supertrend condition side by side (sorted by asset name):")

    def counts(syms, left, right):
        both = sum(1 for s in syms if s in left and s in right)
        only_left = sum(1 for s in syms if s in left and s not in right)
        return both, only_left, len(syms) - both - only_left

    def pct(value):
        return f"{value:.2f}%" if value != float('inf') else "?%"

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
        print("NEAR A CHANNEL LINE / TOUCHING THE SUPERTREND LINE")
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

    print()
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
        print("BROKEN CHANNEL / SUPERTREND FLIP")
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
                              GREEN if ev['trend'] == 'Up' else RED, use_color)
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
    parser.add_argument('--max-proximity', type=float, default=10.0,
                        help="maximum proximity percentage to report (default: 10; both scans)")
    parser.add_argument('--asset', default=None,
                        help="scan a single asset instead of all (both scans)")
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

    # --channels: only the channel scan; --supertrend: only the supertrend
    # scan; --all or bare: both (the user's choice for the default)
    run_channels = not args.supertrend
    run_supertrend = not args.channels
    both = run_channels and run_supertrend

    conn = sqlite3.connect(args.db)
    res_channels = names_channels = None
    res_supertrend = names_supertrend = None
    if run_channels:
        res_channels = scan_channel_proximity(
            conn, max_proximity=args.max_proximity, symbol=args.asset,
            lower_than=args.lower_than)
        names_channels = resolve_channel_names(conn, res_channels)
    if run_supertrend:
        res_supertrend = scan_supertrend(
            conn, period=args.period, multiplier=args.multiplier,
            max_proximity=args.max_proximity, symbol=args.asset)
        names_supertrend = resolve_supertrend_names(conn, res_supertrend)
    conn.close()

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


# === status: the per-asset snapshot ========================================
# One row per asset (sorted by its display name): the last close colored
# by its daily move (green when it went up since the previous bar, red
# when it went down, plain when it did not move or there is no previous
# bar) with the DAY % column - the percent change along the day - and the
# WEEK % column next to it - the percent change along the last week (vs
# the last close at least 7 days older), both colored the same way; the
# last update date (when the shown data was last refreshed - the source
# asset's row for copies), the nearest drawn channel (its kind and the
# percentage distances to the upper and lower lines), the CHANNEL BREAK
# (the line the close went beyond: Upper or Lower, the established
# green/red coding), the supertrend bands (the percentage distances to
# the Up line - the support below the price - and the Down line - the
# resistance above it) and the SUPERTREND BREAK (the band the close went
# beyond). '-' marks what does not apply (never updated, no channel, or
# too few bars for the supertrend's warm-up); assets without any bars
# are listed in the Skipped note.
#
# --date YYYY-MM-DD shows the status AS OF a past date: only the bars up
# to that date, so the close, the daily and weekly changes, the channel
# lines (drawings are anchored at bar positions) and the supertrend bands
# are all evaluated at that moment of the history.

def _date_arg(text):
    """The --date flag's value: a YYYY-MM-DD date."""
    try:
        datetime.strptime(text, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"the date must be YYYY-MM-DD (got {text!r})")
    return text


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


def build_status_parser(parser):
    """The status command's flags."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="show a single asset instead of all")
    parser.add_argument('--date', default=None, type=_date_arg, metavar='YYYY-MM-DD',
                        help="show the status as of this past date (the last bar on "
                             "or before it, with its own daily and weekly changes, "
                             "channel and supertrend)")
    parser.add_argument('--period', type=int, default=SUPERTREND_PERIOD,
                        help=f"the ATR period of the supertrend (default: {SUPERTREND_PERIOD})")
    parser.add_argument('--multiplier', type=float, default=SUPERTREND_MULTIPLIER,
                        help=f"the supertrend multiplier (default: {SUPERTREND_MULTIPLIER:g})")
    parser.add_argument('--no-color', action='store_true', help="plain text without ANSI colors")


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
            direction, line, flip, lower_band, upper_band = supertrend(
                high, low, close, args.period, args.multiplier)
            t = n_bars - 1
            if direction[t] != 0:
                support, resistance = float(lower_band[t]), float(upper_band[t])
                st_up = _distance_pct(last_close, support)
                st_down = _distance_pct(last_close, resistance)
                # the supertrend range break: the close is beyond one of
                # the bands
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

    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("Status - the last close colored by its daily move (green up, red down),")
    print("the channel and the supertrend line distances")
    print(f"Parameters: period {args.period}, multiplier {args.multiplier:g} | "
          f"{len(rows)} asset(s)"
          + (f" | as of {args.date}" if args.date else "") + "\n")

    if not rows:
        if args.asset is not None and not skipped:
            print(f"Asset not found in the database: {args.asset}")
        elif args.date is not None:
            print(f"No asset has price data up to {args.date}")
        else:
            print("No assets in the database")
    else:
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

    if skipped:
        print("\nSkipped:")
        for s in skipped:
            print(f"  {s}")


# === list: the exchange product listings ====================================
# The assets of an exchange, fetched live from its public API with the
# same providers the application uses (pystalker/core/providers.py), so
# the symbols seen here are always the ones the application downloads.

PHEMEX_TYPE_CHOICES = ('perp', 'tradfi', 'tokenized', 'crypto', 'all')
PHEMEX_DEFAULT_TYPES = ('perp', 'tradfi', 'tokenized')

PHEMEX_CATEGORY_ORDER = {'perp': 0, 'tradfi': 1, 'tokenized': 2, 'crypto': 3}
PHEMEX_CATEGORY_TITLES = {'perp': 'crypto perp futures',
                          'tradfi': 'perp futures on tokenized assets (stocks, indices, commodities)',
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
        categories = set(PHEMEX_TYPE_CHOICES[:-1]) if args.type == 'all' else {args.type}
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
    title = PHEMEX_CATEGORY_TITLES[args.type] if args.type else "perp futures and tokenized assets"
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
        counts[PHEMEX_CATEGORY_LABELS[category]] = counts.get(PHEMEX_CATEGORY_LABELS[category], 0) + 1
    breakdown = ", ".join(f"{n} {c.lower()}" for c, n in counts.items())
    print(f"\n{len(rows)} product(s): {breakdown}")


PIONEX_TYPE_CHOICES = ('all', 'spot', 'perp')


def _is_enabled(product: dict) -> bool:
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
        rows.append((symbol, ptype, base, quote, name, 'Enabled' if enabled else 'Disabled'))
    rows.sort(key=lambda r: (0 if r[1] == 'SPOT' else 1, r[0]))

    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    scope = f"matching \"{args.search}\" " if args.search else ""
    print(f"Pionex products {scope}- {len(rows)} shown "
          f"({sum(1 for p in products if _is_enabled(p))} enabled, {len(products)} total)\n")

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


# === the command dispatch ===================================================

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='pystalker_cli.py',
        description="The unified PyStalker command-line tool "
                    "(operations, update, scanner, status, list)")
    sub = parser.add_subparsers(dest='command', metavar='command')

    operations = sub.add_parser('operations',
                                 help="list the trading operations journal")
    build_operations_parser(operations)
    operations.set_defaults(func=run_operations)

    update = sub.add_parser('update',
                            help="update all assets' data from their data sources")
    build_update_parser(update)
    update.set_defaults(func=run_update)

    scanner = sub.add_parser('scanner',
                             help="scan the drawn channels and/or the supertrend indicator "
                                  "(default: both)")
    build_scanner_parser(scanner)
    scanner.set_defaults(func=run_scanner)

    status = sub.add_parser(
        'status',
        help="the last close with its daily change, last update date, "
             "channel and supertrend distances of every asset")
    build_status_parser(status)
    status.set_defaults(func=run_status)

    # list: the second argument is the exchange
    list_parser = sub.add_parser('list',
                                 help="list the assets of an exchange (phemex, pionex)")
    list_sub = list_parser.add_subparsers(dest='exchange', metavar='exchange',
                                          required=True)
    phemex = list_sub.add_parser('phemex', help="the phemex products")
    build_phemex_parser(phemex)
    phemex.set_defaults(func=run_phemex)
    pionex = list_sub.add_parser('pionex', help="the pionex products")
    build_pionex_parser(pionex)
    pionex.set_defaults(func=run_pionex)

    args = parser.parse_args(argv)
    if args.command is None:
        # running the program without any command: show the help screen
        # with all the commands instead of the usage error
        parser.print_help()
        return
    args.func(args)


if __name__ == '__main__':
    main()