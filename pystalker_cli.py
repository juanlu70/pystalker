#!/usr/bin/env python3
"""
pystalker_cli.py - The unified PyStalker command-line tool

One program with a command for every console tool of the project (the old
standalone programs live in console_programs/ and still run on their own).
Every command keeps the flags of its original program:

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
               day); --channels or --supertrend scans
               one alone. The section flags --near,
               --broken and --open-broken print ONLY that section of the
               listing (combinable; they take precedence over the scan
               flags and run the scans their sections need). --historical
               (needs --asset) scans the asset's WHOLE HISTORY: every
               occurrence of a broken channel, a supertrend flip or an
               open broken supertrend channel, one chronological list (one
               occurrence per episode), with --broken/--open-broken
               filtering the event types.
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
  python pystalker_cli.py scanner --broken                   (only that section)
  python pystalker_cli.py scanner --near --open-broken       (two sections alone)
  python pystalker_cli.py scanner --historical --asset TSLA  (TSLA's event history)
  python pystalker_cli.py status
  python pystalker_cli.py status --asset BTC-USD
  python pystalker_cli.py status --date 2026-11-04
  python pystalker_cli.py list phemex --search Tesla
  python pystalker_cli.py list pionex --type perp

  python pystalker_cli.py <command> --help     lists the flags of a command
"""
import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))          # the pystalker package imports
TOOLS_DIR = ROOT / 'console_programs'


def _tool(module_name):
    """Load a console program from console_programs/ (lazily, so a problem
    in one tool never affects the others)."""
    path = TOOLS_DIR / f'{module_name}.py'
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='pystalker_cli.py',
        description="The unified PyStalker command-line tool "
                    "(operations, update, scanner, status, list)")
    sub = parser.add_subparsers(dest='command', metavar='command')

    def command(name, module_name, help_text):
        tool = _tool(module_name)
        sub_parser = sub.add_parser(name, help=help_text)
        tool.build_parser(sub_parser)
        sub_parser.set_defaults(func=tool.run)

    command('operations', 'operations_list',
            "list the trading operations journal")
    command('update', 'update_data',
            "update all assets' data from their data sources")
    command('scanner', 'scanner',
            "scan the drawn channels and/or the supertrend indicator "
            "(default: both)")
    command('status', 'status',
            "the last close with its daily and weekly changes, last update "
            "date, channel and supertrend distances of every asset")

    # list: the second argument is the exchange
    list_parser = sub.add_parser(
        'list', help="list the assets of an exchange (phemex, pionex)")
    list_sub = list_parser.add_subparsers(dest='exchange', metavar='exchange',
                                          required=True)
    for exchange, module_name in (('phemex', 'phemex_assets'),
                                  ('pionex', 'pionex_assets')):
        tool = _tool(module_name)
        exchange_parser = list_sub.add_parser(exchange,
                                             help=f"the {exchange} products")
        tool.build_parser(exchange_parser)
        exchange_parser.set_defaults(func=tool.run)

    args = parser.parse_args(argv)
    if args.command is None:
        # running the program without any command: show the help screen
        # with all the commands instead of the usage error
        parser.print_help()
        return
    args.func(args)


if __name__ == '__main__':
    main()