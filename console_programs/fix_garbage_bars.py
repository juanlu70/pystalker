#!/usr/bin/env python3
"""
fix_garbage_bars.py - Remove garbage daily bars from all assets

Scans every asset's bars table for rows that cannot be real prices and
deletes them:

  1. non-numeric / non-positive prices (open, high, low or close NULL,
     NaN, infinite or <= 0),
  2. structurally broken candles (high < low, high below the body,
     low above the body),
  3. isolated extreme spikes: a bar priced more than --factor (default 50)
     times the median of its neighbours (or less than 1/factor of it) - a
     single absurd candle in an otherwise normal series (e.g. a 3,375,000
     high on a $10 asset), unlike a genuine rally or crash whose
     neighbouring candles climb or fall gradually.

Every removed bar is printed (date + values + reason). The database is
backed up first (a consistent SQLite snapshot, "<db>.bak-<timestamp>"),
and --dry-run reports without changing anything. The removed days come
back clean on the next "update" if the data provider serves them
properly now.

Run it while the pystalker program is closed.

Usage:
  python console_programs/fix_garbage_bars.py
  python console_programs/fix_garbage_bars.py --dry-run
  python console_programs/fix_garbage_bars.py --asset AGPU
  python console_programs/fix_garbage_bars.py --factor 100
  python console_programs/fix_garbage_bars.py --db /path/to/pystalker.db
"""
import argparse
import math
import sqlite3
import statistics
import sys
from datetime import datetime
from pathlib import Path

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')
NEIGHBORS = 5        # bars on each side used to judge an isolated spike
MIN_NEIGHBORS = 3    # fewer than this: not enough context, skip the check


def backup_db(db_path):
    """Consistent snapshot backup of the database (SQLite backup API)."""
    backup_path = f"{db_path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    src.backup(dst)
    dst.close()
    src.close()
    return backup_path


def list_bars_tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_bars'")
    return sorted(r[0] for r in cur.fetchall())


def parse_value(value):
    """The price as a float, or None when it is not a usable number."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def garbage_rows(rows, factor):
    """The garbage rows of one asset: [(rowid, timestamp, reason)].

    rows: [(rowid, timestamp, open, high, low, close)] ordered by time.
    """
    closes = [parse_value(r[5]) for r in rows]
    flagged = []          # (index, reason) - collected first, resolved below
    for i, (rowid, ts, o_raw, h_raw, l_raw, c_raw) in enumerate(rows):
        o, h, l, c = (parse_value(v) for v in (o_raw, h_raw, l_raw, c_raw))
        if o is None or h is None or l is None or c is None:
            flagged.append((i, 'non-numeric price'))
            continue
        if o <= 0 or h <= 0 or l <= 0 or c <= 0:
            flagged.append((i, 'non-positive price'))
            continue
        body_hi, body_lo = max(o, c), min(o, c)
        # a generous relative tolerance: providers store high/low with less
        # precision than open/close on old history (violations up to ~1% are
        # normal there) - only outright impossible bars are broken candles
        eps = max(1e-9, body_hi * 0.05)
        if h < l or h < body_hi - eps or l > body_lo + eps:
            flagged.append((i, f'broken candle (open {o:g} high {h:g} '
                                f'low {l:g} close {c:g})'))
            continue

    reasons = dict(flagged)
    for i in range(len(rows)):
        if i in reasons:
            continue
        neighbours = [closes[j] for j in range(max(0, i - NEIGHBORS),
                                               min(len(rows), i + NEIGHBORS + 1))
                       if j != i and j not in reasons]
        if len(neighbours) < MIN_NEIGHBORS:
            continue
        median = statistics.median(neighbours)
        if median <= 0:
            continue
        o, h, l, c = (parse_value(v) for v in rows[i][2:6])
        if max(o, h, l, c) > median * factor:
            reasons[i] = (f'isolated spike (bar up to {max(o, h, l, c):g} '
                          f'vs neighbours ~{median:g})')
        elif min(o, h, l, c) < median / factor:
            reasons[i] = (f'isolated dip (bar down to {min(o, h, l, c):g} '
                         f'vs neighbours ~{median:g})')

    return [(rows[i][0], rows[i][1], reasons[i])
            for i in sorted(reasons)]


def main():
    parser = argparse.ArgumentParser(
        description="Remove garbage daily bars (non-numeric/non-positive prices, "
                    "broken candles, isolated extreme spikes) from the pystalker database")
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="clean a single asset instead of all (the exact database symbol)")
    parser.add_argument('--factor', type=float, default=50.0,
                        help="an isolated bar counts as garbage when it is this many times "
                             "its neighbours' median price (default: 50)")
    parser.add_argument('--dry-run', action='store_true',
                        help="report what would be cleaned without changing anything")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    tables = list_bars_tables(conn)
    if args.asset is not None:
        wanted = f'{args.asset}_bars'      # sqlite_master stores names unquoted
        tables = [t for t in tables if t == wanted]
        if not tables:
            print(f"No bars table for {args.asset}")
            conn.close()
            sys.exit(1)

    # scan first, report everything, then delete
    found = []      # (table, [(rowid, ts, reason)])
    for table in tables:
        rows = conn.execute(
            f'SELECT rowid, timestamp, open, high, low, close FROM "{table}" '
            f'ORDER BY timestamp').fetchall()
        if not rows:
            continue
        garbage = garbage_rows(rows, args.factor)
        if garbage:
            found.append((table, garbage))

    print(f"Scanned {len(tables)} bars table(s) in {db_path}")
    if not found:
        print("\nNo garbage bars found. Database is already clean.")
        conn.close()
        return

    print(f"\nGarbage bars ({sum(len(g) for _, g in found)} in "
          f"{len(found)} of {len(tables)} asset(s)):\n")

    def show(value):
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return str(value) if value is not None else "NULL"

    for table, garbage in found:
        symbol = table[:-len('_bars')].strip('"')
        print(f"{symbol}: {len(garbage)} bar(s)")
        for rowid, ts, reason in garbage:
            row = conn.execute(
                f'SELECT open, high, low, close FROM "{table}" WHERE rowid = ?',
                (rowid,)).fetchone()
            date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            print(f"  {date}  open {show(row[0])}  high {show(row[1])}  "
                  f"low {show(row[2])}  close {show(row[3])}   ({reason})")
    print()

    if args.dry_run:
        print("Dry run: nothing changed.")
        conn.close()
        return

    backup_path = backup_db(db_path)
    print(f"Backup written to: {backup_path}\n")

    removed = 0
    for table, garbage in found:
        for rowid, _, _ in garbage:
            conn.execute(f'DELETE FROM "{table}" WHERE rowid = ?', (rowid,))
            removed += 1
    conn.commit()
    print(f"Removed {removed} garbage bar(s). The days come back clean on the "
          f"next update if the provider serves them properly now.")
    conn.close()


if __name__ == '__main__':
    main()