#!/usr/bin/env python3
"""
scanner.py - The fused scanner: channels and/or supertrend

The 'scanner' command of pystalker_cli.py: one command, two scanners.

  --channels     the channel scanner's report: assets whose price is near
                 a drawn channel line, plus broken channels
  --supertrend   the supertrend scanner's report: assets whose close is
                 touching the supertrend line (period 10, multiplier 1.8)
                 or crossed it (the trend flipped)
  --all          both scans at the same time - and this is also the
                 DEFAULT: a bare 'pystalker_cli.py scanner' runs both
                 (the user's choice). After the two reports, the
                 both-scans-by-asset view: one row per asset with its
                 channel condition and its supertrend condition side by
                 side ('-' when the asset has only one), sorted by the
                 assets' display names - the near/touching table and the
                 broken/flipped one, each closed by the counts of assets
                 with both conditions / only the channel's / only the
                 supertrend's, to see which assets have both conditions
                 and which only one

The flags of both original tools are kept, each documented for the scan it
belongs to: --max-proximity (both scans, default 10%), --asset (both
scans, the single-asset filter - the standalone programs keep their
--symbol flag), --lower-than (channels), --period and --multiplier
(supertrend). The original standalone programs
console_programs/channel_scanner.py and console_programs/supertrend.py
keep running on their own with the same flags as before.

Usage:
  python pystalker_cli.py scanner                            (channels + supertrend)
  python pystalker_cli.py scanner --channels
  python pystalker_cli.py scanner --supertrend --period 10 --multiplier 3
  python pystalker_cli.py scanner --all --asset BTC-USD --max-proximity 5
  python console_programs/scanner.py --db /path/to/pystalker.db   (standalone)
"""
import argparse
import importlib.util
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.channel_scanner import scan_channel_proximity
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                        scan_supertrend)

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'


def colored(text, color, enabled=True):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    return f"{color}{text}{RESET}" if enabled else text


def _load_sibling(name):
    """A sibling console program (loaded for its report printer) - the same
    lazy file-based loading pystalker_cli.py uses, so this program runs
    standalone AND wired into the unified CLI."""
    path = Path(__file__).resolve().parent / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_parser(parser):
    """This tool's flags, shared by the standalone program and pystalker_cli.py."""
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
                        help="scan a single asset instead of all (both scans; the standalone "
                             "programs keep their --symbol flag)")
    parser.add_argument('--lower-than', type=float, default=None, metavar='PRICE',
                        help="(channels) keep only the assets whose last price is at this "
                             "price or lower (e.g. --lower-than 15)")
    parser.add_argument('--period', type=int, default=SUPERTREND_PERIOD,
                        help=f"(supertrend) the ATR period (default: {SUPERTREND_PERIOD})")
    parser.add_argument('--multiplier', type=float, default=SUPERTREND_MULTIPLIER,
                        help=f"(supertrend) the multiplier (default: {SUPERTREND_MULTIPLIER:g})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run(args):

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    # --channels: only the channel scan; --supertrend: only the supertrend
    # scan; --all or bare: both (the user's choice for the default)
    run_channels = not args.supertrend
    run_supertrend = not args.channels
    both = run_channels and run_supertrend

    channel_tool = _load_sibling('channel_scanner')
    supertrend_tool = _load_sibling('supertrend')

    conn = sqlite3.connect(args.db)
    res_channels = names_channels = None
    res_supertrend = names_supertrend = None
    if run_channels:
        res_channels = scan_channel_proximity(
            conn, max_proximity=args.max_proximity, symbol=args.asset,
            lower_than=args.lower_than)
        names_channels = channel_tool.resolve_names(conn, res_channels)
    if run_supertrend:
        res_supertrend = scan_supertrend(
            conn, period=args.period, multiplier=args.multiplier,
            max_proximity=args.max_proximity, symbol=args.asset)
        names_supertrend = supertrend_tool.resolve_names(conn, res_supertrend)
    conn.close()

    if res_channels is not None:
        if both:
            print("Channel scanner:")
        channel_tool.print_channel_report(res_channels, names_channels, args)
    if res_supertrend is not None:
        if both:
            print("\nSupertrend:")
        supertrend_tool.print_supertrend_report(res_supertrend,
                                                names_supertrend, args)
    if both:
        print_fused_view(res_channels, names_channels, res_supertrend,
                         names_supertrend, args)


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
    mode (the user's request): one row per asset with its channel condition
    and its supertrend condition side by side, '-' when the asset has only
    one of them, sorted by the assets' display names (case-insensitive,
    the user's choice) - so it is easy to see which assets have both
    conditions and which only one. Two tables: near a channel line /
    touching the supertrend line, and broken channel / supertrend flip;
    each is closed by the count of assets with both conditions, only the
    channel's and only the supertrend's. The color coding is the reports'
    one (Ascending/Upper/Up in green, Descending/Lower/Down in red)."""
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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan the drawn channels and/or the supertrend indicator "
                    "(default: both)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()