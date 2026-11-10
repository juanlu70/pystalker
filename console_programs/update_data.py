#!/usr/bin/env python3
"""
update_data.py - Update all assets' data (File > Update All Stock Data)

The console twin of the application's "Update All Stock Data": fetches the
daily candles of every asset in the database from the data source that
serves it (each asset remembers whether it came from Yahoo Finance, Phemex
or Pionex - exactly like the menu point) and merges them into the database
(new bars are added, existing ones refreshed; nothing is deleted).

Copies (assets that share another asset's bars through their source_symbol
setting) are skipped: they always use their source asset's fresh bars. Per
symbol the tool reports the source, the total bars, the newest bar date
and how many bars the update added; failures are shown in red and do not
stop the run. The logic is the application's own core (Database and
DataManager), so the console update and the menu point behave identically.

Note: like the application, this tool WRITES the database. If the
application is running at the same time, its charts keep the previous data
until refreshed.

Usage:
  python pystalker_cli.py update                          (the unified program)
  python pystalker_cli.py update --symbol BTC-USD
  python console_programs/update_data.py --db /path/to/pystalker.db   (standalone)
"""
import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.database import Database
from pystalker.core.providers import DataManager

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'


def colored(text, color, enabled=True):
    return f"{color}{text}{RESET}" if enabled else text


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


def build_parser(parser):
    """This tool's flags, shared by the standalone program and pystalker_cli.py."""
    parser.add_argument('--db', default=DB_DEFAULT, help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--symbol', default=None,
                        help="update a single asset instead of all (the exact database symbol)")
    parser.add_argument('--no-color', action='store_true', help="plain text without ANSI colors")


def run(args):

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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Update all assets' stock data from the terminal "
                    "(the File > Update All Stock Data twin)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()