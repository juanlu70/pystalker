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
                 and which only one. The two tables' titles carry the
                 day, like every other section's title. The broken/flipped
                 summary then breaks its events down (the user's
                 request): the broken channels by the line they broke
                 and the flips by their direction, each count with its
                 percentage of that event type's total

The OPEN BROKEN SUPERTREND CHANNEL alert (the last bar's open outside
the supertrend band range, whatever the candle's direction) CLOSES the
listing: it does not fire often, so the very end is where it is easiest
to locate - after the by-asset view in --all mode, after the report in
--supertrend mode.

The section flags (the user's request) print ONLY one part of the
listing: --near the NEAR A CHANNEL LINE / TOUCHING THE SUPERTREND LINE
table, --broken the BROKEN CHANNEL / SUPERTREND FLIP table, --open-broken
the OPEN BROKEN SUPERTREND CHANNEL alert; several can be combined and
print in the listing's order. They take precedence over
--channels/--supertrend/--all and run the scans their sections need
(the by-asset tables both scans, the alert the supertrend one); an empty
section prints its "No ..." line, so a section-only run always shows the
scan ran.

The --historical flag (the user's request) scans ONE asset's WHOLE
HISTORY of events instead of its last bar: every occurrence of a broken
channel, a supertrend flip or an open broken supertrend channel, ONE
chronological list (the user's choices) with each event's date and the
established notification wording - one occurrence per episode, the first
bar of each stretch outside a line (a price or an open can stay beyond
for many bars; that is one event, at the bar it started). It needs
--asset; --broken shows only the broken channel + supertrend flip
occurrences, --open-broken only the open broken ones (--near is
ignored - touching is a state, not an event), and the other flags keep
their meanings (--date: the history up to that day, --period and
--multiplier: the supertrend parameters).

The flags of both original tools are kept, each documented for the scan it
belongs to: --max-proximity (both scans, default 10%), --asset (both
scans, the single-asset filter - the standalone programs keep their
--symbol flag), --date (both scans: a past day - only the bars up to
that date, so the channels and the supertrend are evaluated at that
moment of the history), --lower-than (channels), --period and
--multiplier (supertrend). The original standalone programs
console_programs/channel_scanner.py and console_programs/supertrend.py
keep running on their own with the same flags as before.

Usage:
  python pystalker_cli.py scanner                            (channels + supertrend)
  python pystalker_cli.py scanner --channels
  python pystalker_cli.py scanner --supertrend --period 10 --multiplier 3
  python pystalker_cli.py scanner --all --asset BTC-USD --max-proximity 5
  python pystalker_cli.py scanner --date 2026-11-04          (that day's scans)
  python pystalker_cli.py scanner --broken                    (only that section)
  python pystalker_cli.py scanner --near --open-broken        (two sections alone)
  python pystalker_cli.py scanner --historical --asset TSLA   (TSLA's event history)
  python pystalker_cli.py scanner --historical --asset TSLA --open-broken
  python console_programs/scanner.py --db /path/to/pystalker.db   (standalone)
"""
import argparse
import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.channel_scanner import (scan_channel_break_history,
                                            scan_channel_proximity)
from pystalker.core.operations import get_display_name
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                        scan_supertrend, scan_supertrend_history)

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


def _date_arg(text):
    """The --date flag's value: a YYYY-MM-DD date."""
    try:
        datetime.strptime(text, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"the date must be YYYY-MM-DD (got {text!r})")
    return text


def run(args):

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

    channel_tool = _load_sibling('channel_scanner')
    supertrend_tool = _load_sibling('supertrend')

    conn = sqlite3.connect(args.db)
    res_channels = names_channels = None
    res_supertrend = names_supertrend = None
    if run_channels:
        res_channels = scan_channel_proximity(
            conn, max_proximity=args.max_proximity, symbol=args.asset,
            lower_than=args.lower_than, cutoff=cutoff)
        names_channels = channel_tool.resolve_names(conn, res_channels)
    if run_supertrend:
        res_supertrend = scan_supertrend(
            conn, period=args.period, multiplier=args.multiplier,
            max_proximity=args.max_proximity, symbol=args.asset,
            cutoff=cutoff)
        names_supertrend = supertrend_tool.resolve_names(conn, res_supertrend)
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
            supertrend_tool.print_open_broken_alert(res_supertrend,
                                                    names_supertrend, args,
                                                    section_mode=True)
        return

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
    if res_supertrend is not None:
        # the OPEN BROKEN SUPERTREND CHANNEL alert closes the listing: it
        # does not fire often, so the very end is where it is easiest to
        # locate (after the by-asset view in --all mode)
        supertrend_tool.print_open_broken_alert(res_supertrend,
                                                names_supertrend, args)


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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan the drawn channels and/or the supertrend indicator "
                    "(default: both)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()