#!/usr/bin/env python3
"""
volatility_stop.py - The best stop loss level for any asset

Standalone (plain sqlite3 and numpy on the database file, no pystalker
imports): the stop loss program of the weekly strategy
(docs/all_2026_best_performing.md) - the companion of
next_week_recommendation.py. For any asset you could buy or sell with
that strategy, it sets the stop from THE VOLATILITY PREDICTOR's honest
call for the next trading day (the same fuel the strategy selects on):

  sigma_day = the predicted daily percent volatility of the asset
              (the journal volatility_predictions' latest row on a
              live run - run volatility_prediction.py first - or the
              honest as-of walk volatility_accuracy_days with --date),
              falling back to the REALIZED volatility (the standard
              deviation of the last 20 daily returns) when nothing is
              stored, flagged as the fallback.

THE CALIBRATED BEST STOP: K = 2.0x sigma_day. Measured on the 48 weekly
winners of 2026 (the analysis behind docs/all_2026_best_performing.md):
the winners' maximum adverse excursion within their winning week was a
median of only 0.47x sigma_day (12 of 48 never went against the entry
at all), and a stop at

     1.0x sigma_day would have stopped  8/26 winners (69% survive)
     1.5x sigma_day                    7/26        (73% survive)
     2.0x sigma_day                    4/26        (85% survive)
     3.0x sigma_day                    3/26        (88% survive)

2x is the sweet spot: it lets the winners run (85%) while staying a
meaningful distance from the entry - and it equals 0.9x sigma_week
(the weekly standard deviation of a 5-day hold, sigma_day x sqrt(5)),
about one weekly sigma, the classic size for a week-long position.
--stop-times overrides the multiple.

The program prints the whole ladder (1.0x / 1.5x / 2.0x / 3.0x /
1x sigma_week / 2x sigma_week) with the prices for the chosen side,
THE RECOMMENDED level, and THE POSITION that makes the stop survivable
(the risk per unit -> the position size at --risk percent of the
account: the leveraged vehicles need tiny positions because their
sigma is huge).

The database is only READ (mode=ro).

Usage:
  python console_programs/volatility_stop.py --asset AAPL
  python console_programs/volatility_stop.py --asset SKDD --direction short
  python console_programs/volatility_stop.py --asset SPY --entry 612.50 --stop-times 3
  python console_programs/volatility_stop.py --asset MRNA --date 2026-11-20
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

# the measured best stop (the docstring's calibration): 2x the
# predicted daily volatility
STOP_TIMES_DEFAULT = 2.0
SQRT5 = 5 ** 0.5

GREEN = '\033[32m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'


def colored(text, color, enabled=True, bold=False):
    """text wrapped in ANSI codes; the padding must already be applied."""
    if not enabled or color is None:
        return text
    prefix = BOLD if bold else ''
    return f"{prefix}{color}{text}{RESET}"


def get_display_name(conn, symbol):
    """The personalized display name, None when there is none (read
    straight from the settings table - this program is standalone)."""
    try:
        row = conn.execute(
            f'SELECT value FROM "{symbol}_settings" WHERE key = ?',
            ('display_name',)).fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def load_closes(conn, symbol):
    """(timestamps, closes) of the asset's daily bars."""
    try:
        rows = conn.execute(
            f'SELECT timestamp, close FROM "{symbol}_bars" '
            f'WHERE close IS NOT NULL ORDER BY timestamp').fetchall()
    except sqlite3.OperationalError:
        return None, None
    if not rows:
        return None, None
    return (np.array([int(r[0]) for r in rows]),
            np.array([float(r[1]) for r in rows]))


def resolve_asset(conn, text, symbols):
    """The official symbols matching the typed text (a substring of the
    stored symbol or the display name - the operations convention; an
    EXACT symbol match wins over the substrings, so SKDD is SKDD and
    not also SKDDUSDT)."""
    t = text.strip().lower()
    exact = [s for s in symbols if s.lower() == t]
    if exact:
        return exact
    return [s for s in symbols
            if t in s.lower() or t in (get_display_name(conn, s) or '').lower()]


def predicted_vol(conn, symbol, raw_ts, anchor_ts):
    """(sigma, source, date, stale) - the honest predicted daily
    volatility: the as-of walk for the next trading day after the
    anchor (raw_ts: the UNFILTERED bars - with --date the future bars
    live beyond the cutoff), then the journal's latest row, then None."""
    nxt = raw_ts[raw_ts > anchor_ts]
    first_day = (datetime.fromtimestamp(int(nxt[0])).strftime('%Y-%m-%d')
                 if len(nxt) else None)
    if first_day:
        row = conn.execute(
            'SELECT pred_vol, prob FROM volatility_accuracy_days '
            'WHERE symbol = ? AND predicted_for = ?', (symbol, first_day)).fetchone()
        if row and row[0] is not None:
            return abs(row[0]), f"the as-of walk (prob_high {row[1]:.2f})", first_day, False
    rows = conn.execute(
        'SELECT predicted_vol, prob_high, predicted_date, made_at '
        'FROM volatility_predictions WHERE symbol = ? '
        'ORDER BY made_at DESC LIMIT 1', (symbol,)).fetchall()
    if rows and rows[0][0] is not None:
        stale = (first_day is not None and rows[0][2] != first_day)
        return (abs(rows[0][0]),
                f"the journal (prob_high {rows[0][1]:.2f})",
                rows[0][2], stale)
    return None, None, None, False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="the best stop loss level for any asset, from the "
                    "volatility predictor's honest call - calibrated on "
                    "the 2026 weekly winners (2x the predicted daily "
                    "volatility)")
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', required=True, metavar='NAME',
                        help="the asset (the official symbol or a substring "
                             "of it or its display name)")
    parser.add_argument('--direction', choices=('long', 'short'),
                        default='long',
                        help="the side you would trade (default: long)")
    parser.add_argument('--entry', type=float, default=None, metavar='PRICE',
                        help="your entry price (default: the last close)")
    parser.add_argument('--stop-times', type=float, default=STOP_TIMES_DEFAULT,
                        metavar='K',
                        help=f"the stop as K times the predicted daily "
                             f"volatility (default: {STOP_TIMES_DEFAULT:g}, "
                             f"the measured best for the weekly strategy)")
    parser.add_argument('--risk', type=float, default=1.0, metavar='PCT',
                        help="the account risk percent for the position "
                             "size line (default: 1)")
    parser.add_argument('--date', default=None, metavar='YYYY-MM-DD',
                        help="as of this past day (the walk's honest "
                             "prediction for the next day)")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")
    args = parser.parse_args(argv)

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)
    conn = sqlite3.connect(
        f"file:{quote(str(Path(args.db).resolve()))}?mode=ro", uri=True)
    try:
        symbols = [r[0] for r in conn.execute(
            'SELECT symbol FROM symbols ORDER BY symbol').fetchall()]
        matches = resolve_asset(conn, args.asset, symbols)
        if not matches:
            print(f"No asset matches \"{args.asset}\".")
            sys.exit(1)
        if len(matches) > 1:
            print(f"\"{args.asset}\" is ambiguous - it matches:")
            for s in matches:
                print(f"  {s} ({get_display_name(conn, s) or s})")
            sys.exit(1)
        symbol = matches[0]

        ts, c = load_closes(conn, symbol)
        if ts is None or not len(c):
            print(f"{symbol} has no price data.")
            sys.exit(1)
        raw_ts = ts
        cutoff = (datetime.strptime(args.date, '%Y-%m-%d').timestamp() + 86400
                  if args.date else None)
        if cutoff is not None:
            keep = ts <= cutoff
            ts, c = ts[keep], c[keep]
        if not len(c):
            print(f"{symbol} has no price data up to {args.date}.")
            sys.exit(1)

        use_color = not args.no_color
        entry = args.entry if args.entry is not None else float(c[-1])
        anchor = datetime.fromtimestamp(int(ts[-1])).strftime('%Y-%m-%d')
        name = get_display_name(conn, symbol) or symbol

        sigma, source, sigma_date, stale = predicted_vol(conn, symbol,
                                                         raw_ts, float(ts[-1]))
        realized = None
        if len(c) >= 21:
            rets = (c[-21:] / c[-22:-1] - 1) * 100
            realized = float(np.std(rets, ddof=1))
        if sigma is None:
            sigma = realized
            source = None

        print(f"Report generated: "
              f"{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"VOLATILITY STOP  {name} ({symbol})  "
              f"{args.direction.upper()}  (the data as of {anchor})")
        print(f"Entry: {entry:.2f}"
              + ("  (your --entry)" if args.entry is not None
                 else f"  (the last close {anchor})"))
        if source:
            print(f"The predicted daily volatility: {sigma:.2f}%  "
                  f"[{source}, for {sigma_date}]")
            if stale:
                print(f"  NOTE: the stored prediction targets {sigma_date}, "
                      f"not the next trading day - run "
                      f"volatility_prediction.py for a fresh one")
        else:
            print(f"The predicted daily volatility: none stored - the "
                  f"REALIZED fallback: {sigma:.2f}% "
                  f"(the standard deviation of the last 20 daily returns)")
        if realized is not None and source:
            print(f"The realized 20-day volatility for context: "
                  f"{realized:.2f}%")
        if sigma is None or sigma <= 0:
            print("\nNo volatility to work with (no prediction stored and "
                  "less than 21 bars).")
            sys.exit(1)

        long_side = args.direction == 'long'

        def stop_price(K):
            """the stop at K x sigma from the entry, on the correct side."""
            d = K * sigma / 100.0
            return entry * (1 - d) if long_side else entry * (1 + d)

        print(f"\nTHE STOP LADDER (K x the predicted daily volatility):")
        print(f"{'K':>6}{'LEVEL':>12}{'DISTANCE':>10}   note")
        ladder = [(1.0, '1x sigma_day - the tight'), (1.5, 'the suite/suite '
                  'study default'), (2.0, 'THE MEASURED BEST (85% of the 2026 '
                  'winners survived it)'), (3.0, '3x sigma_day'),
                  (SQRT5, '1x sigma_week (the weekly one-sigma)'),
                  (2 * SQRT5, '2x sigma_week - the wide')]
        for K, note in ladder:
            mark = '  <==' if abs(K - args.stop_times) < 1e-9 else ''
            print(f"{K:>6.2f}{stop_price(K):>12.2f}"
                  f"{K * sigma:>9.2f}%   {note}{mark}")

        price = stop_price(args.stop_times)
        dist = args.stop_times * sigma
        print()
        print(colored(f"THE RECOMMENDED STOP: {price:.2f}  "
                      f"({dist:.2f}% {'below' if long_side else 'above'} "
                      f"the entry)", GREEN, use_color, bold=True))
        print(f"  {args.stop_times:g}x the predicted daily volatility "
              f"({sigma:.2f}%/day) - the calibration measured on the 2026 "
              f"weekly winners: the median adverse excursion within their "
              f"winning weeks was only 0.47x, so 2x clears the normal noise; "
              f"1.5x would have stopped 27% of them and 3x only saves 3 more")
        print(f"  the position that makes it survivable: the risk per unit "
              f"is {dist:.2f}% -> at --risk {args.risk:g}% of the account, "
              f"the position = {args.risk / dist:.2f}x the account "
              f"(no leverage; a 3x vehicle needs this smallness)")
        if not long_side:
            print(f"  (a SHORT: the stop sits ABOVE the entry - the price "
                  f"rising to {price:.2f} is the exit)")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
