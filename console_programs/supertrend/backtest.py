#!/usr/bin/env python3
"""
backtest.py - The probabilities of a PAST supertrend flip operation

Loads the asset's trained model (train.py) and reads the flip of the
given day as a trade per the model's stored config snapshot, printing
the model's probabilities AND the flip's real outcome side by side:

  P SUCCESS / P STOP / P DAY-N LOSS / P FAIL, then
  what really happened: WIN, or the bar that touched the stop, or the
  day-N close vs the entry.

A flip whose outcome was already known at training time is marked
IN-SAMPLE (part of the training data - its probabilities are optimistic;
a flip after the training's last labeled one is a true out-of-sample
case). The real outcome is always recomputed from the bars, never
stored.

Usage:
  python console_programs/supertrend/backtest.py --asset TSLA --date 2026-09-28
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))            # the suite's own core.py
import core   # noqa: E402

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')


def build_parser(parser):
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="the asset of the past operation (the official "
                             "symbol, its display name or an unambiguous part)")
    parser.add_argument('--date', default=None, metavar='YYYY-MM-DD',
                        help="the flip day of the past operation (required)")
    parser.add_argument('--models-dir', default=str(core.DEFAULT_MODELS),
                        help="where the trained models live "
                             f"(default: {core.DEFAULT_MODELS})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run(args):
    if args.asset is None or args.date is None:
        sys.exit("backtest.py needs --asset and --date (the flip day of the "
                 "past operation)")
    payload = core.load_model(args.models_dir, args.asset)
    if payload is None:
        sys.exit(f"No trained model for {args.asset} in {args.models_dir} - "
                 "run train.py --asset first")
    cfg = payload['config']               # the snapshot the model trained with
    use_color = not args.no_color
    vp = core.load_vp()
    conn = core.open_db_read_only(args.db)
    sym, name = vp.resolve_asset(vp.load_symbols(conn), args.asset)
    if payload['symbol'] != sym:
        conn.close()
        sys.exit(f"The model of {args.models_dir} is for {payload['symbol']}, "
                 f"not {sym}")
    events, _ = core.asset_events(conn, sym, cfg)
    conn.close()
    matches = [e for e in events if e['date'] == args.date]
    if not matches:
        sys.exit(f"No supertrend flip of {name} on {args.date} (period "
                 f"{cfg['period']}, multiplier {cfg['multiplier']:g})")
    ev = matches[-1]

    probs = payload['model'].predict_proba(
        core.event_frame([ev], cfg))[0]
    classes = list(payload['model'].classes_)
    p = {core.OUTCOME_OF[int(c)]: float(probs[i])
         for i, c in enumerate(classes)}

    side = 'LONG' if ev['side'] > 0 else 'SHORT'
    side = core.colored(side, core.GREEN if ev['side'] > 0 else core.RED,
                        use_color)
    flip = 'Up' if ev['flip'] > 0 else 'Down'
    print(f"Supertrend flip backtest {datetime.now().strftime('%Y-%m-%d')} - "
          f"{name}, the flip of {ev['date']} (period {cfg['period']}, "
          f"multiplier {cfg['multiplier']:g}, direction {cfg['direction']}, "
          f"{cfg['days']} days, the stop at {cfg['stop_times']:g}x the "
          f"predicted volatility)")
    stop = f"{ev['stop']:.2f} ({ev['stop_pct']:.2f} %)" \
        if not np.isnan(ev['stop']) else "- (no volatility model)"
    print(f"The trade: flipped {flip}, {side} at {ev['entry']:.2f}, the stop "
          f"at {stop}")
    in_sample = (payload['last_labeled_date'] is not None
                 and ev['date'] <= payload['last_labeled_date']
                 and not ev['open'])
    if in_sample:
        print(f"The flip is part of the training data (in-sample, trained on "
              f"{payload['n_labeled']} flips through "
              f"{payload['last_labeled_date']}) - its probabilities are "
              "optimistic")

    print("\nThe model said:")
    for cls in ('WIN', 'STOP', 'LOSS'):
        value = p.get(cls)
        if value is None:
            print(f"  P {cls:<6} - (never seen in the training data)")
            continue
        cell = f"{value * 100:.1f} %"
        color = core.GREEN if (cls == 'WIN') == (value >= 0.5) else core.RED
        print(f"  P {cls:<6} {core.colored(cell, color, use_color)}")
    fail = p.get('STOP', 0.0) + p.get('LOSS', 0.0)
    print(f"  P FAIL    {fail * 100:.1f} %")

    print("\nWhat really happened:")
    if ev['open']:
        print(f"  Still open - fewer than {cfg['days']} bars since the flip; "
              "check back after the window closes")
        return
    real = core.OUTCOME_OF[ev['label']]
    conn = core.open_db_read_only(args.db)
    df = vp.load_bars(conn, sym)
    conn.close()
    if ev['label'] == 1:
        bar = core.stop_bar(df, ev['t'], ev['side'], ev['entry'],
                            ev['stop_pct'], cfg['days'])
        day = df.index[bar].date() if bar is not None else '?'
        print(f"  STOP - the stop {ev['stop']:.2f} was touched on {day} - "
              f"{core.colored('FAIL', core.RED, use_color)}")
    elif ev['label'] == 0:
        final = float(df['Close'].iloc[ev['t'] + cfg['days']])
        print(f"  WIN - never stopped, the day-{cfg['days']} close "
              f"{final:.2f} vs the entry {ev['entry']:.2f} "
              f"({(final - ev['entry']) * ev['side'] / ev['entry'] * 100:+.2f} %"
              f")")
    else:
        final = float(df['Close'].iloc[ev['t'] + cfg['days']])
        print(f"  LOSS - never stopped but the day-{cfg['days']} close "
              f"{final:.2f} vs the entry {ev['entry']:.2f} "
              f"({(final - ev['entry']) * ev['side'] / ev['entry'] * 100:+.2f} %"
              f")")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The trained model's probabilities for a PAST supertrend "
                    "flip, with its real outcome and the in-sample note")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()
