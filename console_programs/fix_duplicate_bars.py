#!/usr/bin/env python3
"""
fix_duplicate_bars.py - One-time repair for duplicated daily bars

A timezone bug in the download path (yfinance returns tz-aware timestamps,
which were stored as true-UTC epochs, differing from the historical local
midnight epochs) left some assets with TWO rows per day. Affected charts
show two candles per day and all bar-indexed drawings (trendlines, channels)
shift to wrong positions.

This script:
  1. makes a backup copy of the database (consistent SQLite backup),
  2. for every *_bars table keeps ONE row per calendar day:
     - prefers the row already stored at local midnight (the canonical form
       used by the app's history),
     - otherwise keeps the earliest row of the day and rewrites its
       timestamp to local midnight, so future downloads REPLACE it
       instead of adding rows again,
     - deletes the remaining duplicate rows of the day.

Run it while the pystalker program is closed.

Usage:
  python fix_duplicate_bars.py
  python fix_duplicate_bars.py --db path/to/pystalker.db
  python fix_duplicate_bars.py --dry-run   (report only, change nothing)
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')


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


def plan_table(conn, table):
    """Compute the (delete_rowids, rewrite) plan for one table.

    rewrite is a list of (new_timestamp, rowid).
    """
    cur = conn.cursor()
    rows = cur.execute(f'SELECT timestamp, rowid FROM "{table}" ORDER BY timestamp').fetchall()
    by_day = {}
    for ts, rowid in rows:
        local = datetime.fromtimestamp(ts)
        by_day.setdefault((local.year, local.month, local.day), []).append((ts, rowid))

    delete_rowids = []
    rewrites = []
    for day, day_rows in by_day.items():
        midnight = int(datetime(*day).timestamp())
        keep = None
        for ts, rowid in day_rows:
            if ts == midnight:
                keep = (ts, rowid)
                break
        if keep is None:
            ts, rowid = day_rows[0]  # earliest row of the day
            keep = (ts, rowid)
            if ts != midnight:
                rewrites.append((midnight, rowid))
        for ts, rowid in day_rows:
            if rowid != keep[1]:
                delete_rowids.append(rowid)
    return len(rows), len(by_day), delete_rowids, rewrites


def main():
    parser = argparse.ArgumentParser(description="Remove duplicated daily bars from the pystalker database")
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--dry-run', action='store_true', help="report what would be cleaned without changing anything")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    # quick pre-scan: does anything need cleaning?
    conn = sqlite3.connect(db_path)
    tables = list_bars_tables(conn)
    needs_work = False
    for table in tables:
        _, _, delete_rowids, rewrites = plan_table(conn, table)
        if delete_rowids or rewrites:
            needs_work = True
            break
    conn.close()

    if not needs_work:
        print(f"Scanning {len(tables)} bars tables in {db_path}")
        print("\nNo duplicated or non-midnight bars found. Database is already clean.")
        return

    if not args.dry_run:
        backup_path = backup_db(db_path)
        print(f"Backup written to: {backup_path}")

    conn = sqlite3.connect(db_path)
    tables = list_bars_tables(conn)
    print(f"Scanning {len(tables)} bars tables in {db_path}\n")

    total_deleted = total_rewritten = 0
    for table in tables:
        rows, days, delete_rowids, rewrites = plan_table(conn, table)
        if not delete_rowids and not rewrites:
            continue
        total_deleted += len(delete_rowids)
        total_rewritten += len(rewrites)
        action = "would delete" if args.dry_run else "deleting"
        print(f"{table}: {rows} rows over {days} days -> {action} {len(delete_rowids)} duplicates, "
              f"{'would normalize' if args.dry_run else 'normalizing'} {len(rewrites)} timestamps")
        if args.dry_run:
            continue
        cur = conn.cursor()
        if delete_rowids:
            cur.executemany(f'DELETE FROM "{table}" WHERE rowid = ?', [(r,) for r in delete_rowids])
        for new_ts, rowid in rewrites:
            cur.execute(f'UPDATE "{table}" SET timestamp = ? WHERE rowid = ?', (new_ts, rowid))
        conn.commit()

    conn.close()

    if total_deleted == 0 and total_rewritten == 0:
        print("\nNo duplicated bars found. Database is already clean.")
        return

    if args.dry_run:
        print(f"\nDRY RUN: {total_deleted} duplicate rows would be deleted, "
              f"{total_rewritten} timestamps normalized. No changes made.")
    else:
        print(f"\nDone: {total_deleted} duplicate rows deleted, "
              f"{total_rewritten} timestamps normalized to local midnight.")


if __name__ == '__main__':
    main()