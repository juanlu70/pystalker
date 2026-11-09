#!/usr/bin/env python3
"""
status.py - The per-asset snapshot (the status command of pystalker_cli.py)

One row per asset (sorted by its display name) with:

  * the last close, colored by its daily move (green when it went up
    since the previous bar, red when it went down, plain when it did
    not move or there is no previous bar),
  * the DAY % column - the percent change along the day - and the
    WEEK % column next to it - the percent change along the last week
    (vs the last close at least 7 days older), both colored the same
    way ('-' when the history is shorter or there is a single bar),
  * the LAST UPDATE date (when the shown data was last refreshed -
    the source asset's row for copies, '-' when never updated),
  * the nearest drawn channel: its kind (Ascending green, Descending
    red) and the percentage distances to the upper and lower lines,
    with the CH BREAK column (the line the close went beyond: Upper
    green, Lower red, '-' while inside),
  * the supertrend bands (period 10, multiplier 1.8): the percentage
    distances to the Up line - the support below the price - and the
    Down line - the resistance above it - with the ST BREAK column
    (the band the close went beyond, same coding).

'-' marks what does not apply (no channel, or too few bars for the
supertrend's warm-up); assets without any bars are listed in the
Skipped note.

--date YYYY-MM-DD shows the status AS OF a past date: only the bars up
to that date, so the close, the daily and weekly changes, the channel
lines (drawings are anchored at bar positions) and the supertrend bands
are all evaluated at that moment of the history.

The scanning logic is the application's own cores
(pystalker/core/channel_scanner.py, pystalker/core/supertrend.py).
The database is only read.

Usage:
  python pystalker_cli.py status                     (the unified program)
  python pystalker_cli.py status --asset BTC-USD
  python pystalker_cli.py status --date 2026-11-04
  python pystalker_cli.py status --period 5 --multiplier 2
  python console_programs/status.py --db /path/to/pystalker.db   (standalone)
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.channel_scanner import (evaluate_channel, get_assets,
                                            get_source_symbol, load_channels)
from pystalker.core.operations import (fmt_gain, fmt_price, get_display_name)
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                        supertrend)

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'


def colored(text, color, enabled=True):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    return f"{color}{text}{RESET}" if enabled else text


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


def build_parser(parser):
    """This tool's flags, shared by the standalone program and pystalker_cli.py."""
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


def run(args):

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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The per-asset snapshot: the last close with its daily and "
                    "weekly changes, the channel and the supertrend distances")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()