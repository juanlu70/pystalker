#!/usr/bin/env python3
"""
correlation.py - How every asset correlates with the market indexes

Standalone (the user's request: no links to any other program - plain
sqlite3 and numpy on the database file, no pystalker imports): for
EVERY asset in the pystalker database except the indexes themselves,
the Pearson correlation of its history against each of the seven
market indexes (the user's list - these are the indexes, never a
compared asset):

    ES=F        the Emini S&P 500 futures (Yahoo Finance)
    NQ=F        the Nasdaq 100 futures (Yahoo Finance)
    SPY         the S&P 500 ETF (Yahoo Finance)
    QQQ         the Nasdaq 100 ETF (Yahoo Finance)
    NAS100USDT  the Nasdaq 100 perpetual (Phemex)
    QQQUSDT     the Nasdaq 100 perpetual (Phemex)
    SPYXUSDT    the S&P 500 perpetual (Phemex)

Two tables, the two bases the user chose:

    DAILY % RETURNS   the correlation of the daily moves: how each
                      day's percent change of the asset matches the
                      index's same-day percent change - the way
                      correlation is usually meant (do they move
                      together TODAY)
    CLOSE PRICE LEVELS   the correlation of the raw closes: whether
                      the two series travel together in the long run
                      (mostly two things going up over the years)

One row per asset, one column per index PLUS the final AVERAGE column
(the mean of the row's available correlations - the cells showing '-'
do not count; a row without a single correlation shows '-' there too),
the columns headed by the indexes' personalized display names (their
symbols when they have none), the rows showing their display names
like every pystalker listing. The rows are sorted by the AVERAGE
column (the user's request), the HIGHEST value first: the assets
that move like the indexes on top, the inverse movers at the bottom
of the correlated ones, and the assets without an average (no
correlation anywhere - not enough shared bars, or a flat series)
last, sorted by name. --sort-by INDEX switches the sort to one index's
column instead (the original behavior).

The correlation of a pair is computed over the bars BOTH series
share (the dates present in the two histories - an asset and an
index usually start at very different times), and a pair needs at
least --min-shared shared bars (default 60, the user's choice) to
report one: the cell shows '-' below that, because a correlation
over a handful of shared days is noise. --days N limits each pair
to its last N shared bars instead of the whole shared history. A
flat series (a stable coin, a halted asset) has no correlation
either: its cells show '-' too.

The database is only READ (the connection opens it read-only).

Usage:
  python console_programs/correlation.py
  python console_programs/correlation.py --sort-by NQ=F
  python console_programs/correlation.py --days 90
  python console_programs/correlation.py --asset AAPL
  python console_programs/correlation.py --min-shared 30 --days 250
  python console_programs/correlation.py --no-color
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

# the seven market indexes (the user's list): every asset correlates
# against each of them, and they are never a compared asset themselves.
# The tables' column order is this list's order.
INDEX_SYMBOLS = ['ES=F', 'NAS100USDT', 'NQ=F', 'QQQ', 'QQQUSDT', 'SPY',
                 'SPYXUSDT']
MIN_SHARED_DEFAULT = 60

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'


def colored(text, color, enabled=True):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    if not enabled or color is None:
        return text
    return f"{color}{text}{RESET}"


def get_display_name(conn, symbol):
    """The personalized display name of a symbol, None when it has none
    (read straight from the database's settings table - this program is
    standalone: no pystalker imports)."""
    try:
        row = conn.execute(
            f'SELECT value FROM "{symbol}_settings" WHERE key = ?',
            ('display_name',)).fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def load_series(conn, symbol):
    """The asset's daily closes as a {timestamp: close} map, {} when the
    asset has no bars table or no rows."""
    try:
        rows = conn.execute(
            f'SELECT timestamp, close FROM "{symbol}_bars" '
            f'WHERE close IS NOT NULL ORDER BY timestamp').fetchall()
    except sqlite3.OperationalError:
        return {}
    return {int(float(t)): float(c) for t, c in rows}


def daily_returns(close_map):
    """{timestamp: the day's percent return} of a close series: each
    bar's return against the previous bar OF THE SAME SERIES (a series
    with a hole reports the return that spans it); the first bar has
    no return, and a zero previous close has none either."""
    returns = {}
    prev = None
    for ts in sorted(close_map):
        c = close_map[ts]
        if prev:
            returns[ts] = (c - prev) / prev * 100.0
        prev = c
    return returns


def correlation(a_map, i_map, last_n, min_shared):
    """The Pearson correlation of two {timestamp: value} maps over the
    timestamps BOTH have (the shared bars), the last N of them when
    last_n is set; None when the pair has fewer than min_shared shared
    bars, when a series is flat (no variance - the correlation is
    undefined) or when they share nothing."""
    common = sorted(set(a_map) & set(i_map))
    if last_n is not None:
        common = common[-last_n:]
    if len(common) < min_shared:
        return None
    a = np.array([a_map[t] for t in common])
    i = np.array([i_map[t] for t in common])
    # a flat series (a stable coin, a halted asset) has no correlation
    if np.std(a) == 0.0 or np.std(i) == 0.0:
        return None
    r = float(np.corrcoef(a, i)[0, 1])
    return r if np.isfinite(r) else None


def print_table(rows, index_data, basis, args, use_color):
    """One of the two sections' tables: one row per asset, one column
    per index plus the final AVERAGE column (the mean of the row's
    available correlations - the user's request), the rows sorted by
    the AVERAGE (the default) or by the correlation with one index
    (--sort-by), the HIGHEST value first, the rows without that value
    last (by name). basis is 'returns' or 'levels'; the color coding:
    green positive, red negative, '-' plain."""
    driver = args.sort_by          # None: the AVERAGE column sorts
    has_driver = (driver is not None
                  and any(i['symbol'] == driver for i in index_data))

    # the final AVERAGE column: the mean of the row's AVAILABLE
    # correlations in this basis (the user's choice: the cells showing
    # '-' do not count; a row without a single correlation has no
    # average either - its AVERAGE cell shows '-')
    averages = {}
    for r in rows:
        vals = [v for v in r[basis].values() if v is not None]
        averages[r['symbol']] = sum(vals) / len(vals) if vals else None

    if has_driver:
        rows_sorted = sorted(rows, key=lambda r: (
            r[basis][driver] is None,
            -(r[basis][driver] or 0.0),
            r['name'].casefold(), r['symbol']))
    elif driver is not None:
        # the chosen index has no data at all: the name order takes over
        rows_sorted = sorted(rows, key=lambda r: (r['name'].casefold(),
                                                  r['symbol']))
    else:
        rows_sorted = sorted(rows, key=lambda r: (
            averages[r['symbol']] is None,
            -(averages[r['symbol']] or 0.0),
            r['name'].casefold(), r['symbol']))

    headers = [i['name'] for i in index_data] + ['AVERAGE']
    name_w = max([len('ASSET')] + [len(r['name']) for r in rows_sorted])
    # '+0.87' / '-1.00': the widest value is 5 characters
    col_ws = [max(len(h), 5) for h in headers]

    print(f"{'ASSET':<{name_w}}"
          + ''.join(f"  {h:>{w}}" for h, w in zip(headers, col_ws)))
    for r in rows_sorted:
        # pad first, colorize after: the f-string widths would count the
        # invisible ANSI escape characters otherwise
        line = f"{r['name']:<{name_w}}"
        for idx, w in zip(index_data, col_ws[:-1]):
            v = r[basis][idx['symbol']]
            cell = '-' if v is None else f"{v:+.2f}"
            color = None if v is None else (GREEN if v >= 0 else RED)
            line += '  ' + colored(f"{cell:>{w}}", color, use_color)
        # the final AVERAGE column
        v = averages[r['symbol']]
        cell = '-' if v is None else f"{v:+.2f}"
        color = None if v is None else (GREEN if v >= 0 else RED)
        line += '  ' + colored(f"{cell:>{col_ws[-1]}}", color, use_color)
        print(line)

    if has_driver:
        n_val = sum(1 for r in rows_sorted if r[basis][driver] is not None)
        driver_name = next(i['name'] for i in index_data
                           if i['symbol'] == driver)
        print(f"\n{len(rows_sorted)} asset(s): {n_val} correlated with "
              f"{driver_name} (the sort basis), "
              f"{len(rows_sorted) - n_val} with '-' (fewer than "
              f"{args.min_shared} shared bars or a flat series)")
    elif driver is None:
        n_val = sum(1 for r in rows_sorted
                    if averages[r['symbol']] is not None)
        print(f"\n{len(rows_sorted)} asset(s): {n_val} with the average "
              f"(the sort basis), {len(rows_sorted) - n_val} with '-' "
              f"(fewer than {args.min_shared} shared bars or a flat series)")
    else:
        print(f"\n{len(rows_sorted)} asset(s)")


def run(args):

    if args.days is not None and args.days < 2:
        sys.exit("the --days window needs at least 2 shared bars")
    if args.min_shared < 2:
        sys.exit("the --min-shared minimum needs at least 2 bars")

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    # read-only by construction: the tool never writes the database
    conn = sqlite3.connect(
        f"file:{quote(str(Path(args.db).resolve()))}?mode=ro", uri=True)
    try:
        try:
            symbols = [r[0] for r in conn.execute(
                'SELECT symbol FROM symbols ORDER BY symbol').fetchall()]
        except sqlite3.OperationalError:
            print("The database has no assets yet - download some data first.")
            sys.exit(1)

        # the index columns: an index without price data is omitted
        # (noted at the end); an asset that is not in the symbols table
        # but has a bars table still counts (its data is there)
        index_data, omitted = [], []
        for sym in INDEX_SYMBOLS:
            closes = load_series(conn, sym)
            if not closes:
                omitted.append(sym)
                continue
            index_data.append({'symbol': sym,
                               'name': get_display_name(conn, sym) or sym,
                               'closes': closes,
                               'returns': daily_returns(closes)})
        if not index_data:
            print("None of the market indexes ("
                  + ", ".join(INDEX_SYMBOLS)
                  + ") has price data in the database.")
            sys.exit(1)

        # every asset except the indexes themselves (they are the columns)
        assets = [s for s in symbols if s not in INDEX_SYMBOLS]
        if args.asset:
            text = args.asset.strip().lower()
            assets = [s for s in assets
                      if text in s.lower()
                      or text in (get_display_name(conn, s) or '').lower()]

        # each asset against every index, on both bases; the newest bar
        # among everything loaded is the data date of the titles
        rows, skipped, newest = [], [], 0
        for sym in assets:
            closes = load_series(conn, sym)
            if not closes:
                skipped.append(f"{sym}: no price data")
                continue
            returns = daily_returns(closes)
            newest = max(newest, max(closes))     # the keys are timestamps
            levels, rets = {}, {}
            for idx in index_data:
                levels[idx['symbol']] = correlation(
                    closes, idx['closes'], args.days, args.min_shared)
                rets[idx['symbol']] = correlation(
                    returns, idx['returns'], args.days, args.min_shared)
            rows.append({'symbol': sym,
                         'name': get_display_name(conn, sym) or sym,
                         'levels': levels, 'returns': rets})
        for idx in index_data:
            newest = max(newest, max(idx['closes']))

        if args.asset and not rows and not skipped:
            print(f"No asset matches \"{args.asset}\" "
                  "(the market indexes themselves are never compared)")
            sys.exit(0)
        if not rows:
            print("No assets with price data in the database")
            if omitted:
                print(f"The index columns omitted (no price data): "
                      + ", ".join(omitted))
            if skipped:
                print("Skipped:")
                for s in skipped:
                    print(f"  {s}")
            sys.exit(0)

        day = (datetime.fromtimestamp(newest).strftime('%Y-%m-%d')
               if newest else datetime.now().strftime('%Y-%m-%d'))
        use_color = not args.no_color
        driver = args.sort_by
        has_driver = any(i['symbol'] == driver for i in index_data)
        driver_name = (next((i['name'] for i in index_data
                             if i['symbol'] == driver), None))

        print(f"Report generated: "
              f"{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        scope = ""
        if args.asset:
            scope += f" - asset \"{args.asset}\""
        if args.days is not None:
            scope += f" - the last {args.days} shared bars of each pair"
        if args.min_shared != MIN_SHARED_DEFAULT:
            scope += (f" - at least {args.min_shared} shared bars")
        print(f"Asset correlations {day} - every asset against the market "
              f"index columns{scope}:")
        if args.sort_by is None:
            print("sorted by the AVERAGE of the index correlations, the "
                  "highest first; correlated over the bars both share, at "
                  f"least {args.min_shared} of them ('-' when the pair does "
                  "not have them)")
        elif has_driver:
            print(f"sorted by the {driver_name} correlation, the highest "
                  f"first; correlated over the bars both share, at least "
                  f"{args.min_shared} of them ('-' when the pair does not "
                  f"have them)")
        else:
            print(f"{driver} has no price data in the database - the rows "
                  f"sorted by asset name")
            print(f"correlated over the bars both share, at least "
                  f"{args.min_shared} of them ('-' when the pair does not "
                  f"have them)")

        print()
        print(f"DAILY % RETURNS {day} - how each day's percent change "
              f"matches the index's same-day percent change:")
        print_table(rows, index_data, 'returns', args, use_color)

        print()
        print(f"CLOSE PRICE LEVELS {day} - the long-run travel together "
              f"of the raw closes:")
        print_table(rows, index_data, 'levels', args, use_color)

        if omitted or skipped:
            print("\nSkipped:")
            if omitted:
                print(f"  the index columns omitted (no price data): "
                      + ", ".join(omitted))
            for s in skipped:
                print(f"  {s}")
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="the correlation of every asset with the market "
                    "indexes (" + ", ".join(INDEX_SYMBOLS) + ") over the "
                    "bars both share - the daily percent returns and the "
                    "close price levels")
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--sort-by', choices=INDEX_SYMBOLS, default=None,
                        metavar='INDEX',
                        help="sort by one index's correlation instead of the "
                             "AVERAGE column (default: sorted by the "
                             "AVERAGE, the last column; one of: "
                             + ", ".join(INDEX_SYMBOLS) + ")")
    parser.add_argument('--days', type=int, default=None, metavar='N',
                        help="limit each pair to its last N shared bars "
                             "(default: the whole shared history)")
    parser.add_argument('--min-shared', type=int, default=MIN_SHARED_DEFAULT,
                        metavar='N',
                        help="the minimum shared bars a pair needs to report "
                             f"a correlation (default: {MIN_SHARED_DEFAULT}; "
                             "below that the cell shows '-')")
    parser.add_argument('--asset', default=None,
                        help="keep only this asset (a substring of its stored "
                             "symbol or personalized name)")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")
    args = parser.parse_args(argv)
    run(args)


if __name__ == '__main__':
    main()
