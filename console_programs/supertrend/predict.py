#!/usr/bin/env python3
"""
predict.py - The probabilities of a NEW supertrend flip case

Loads the asset's trained model (train.py) and reads its latest flip -
or the flip of --date YYYY-MM-DD - as a trade per the model's stored
config snapshot, printing the three outcome probabilities:

  P SUCCESS   the stop never hit within `days` bars AND day-N in profit
  P STOP      the stop reached within the window
  P DAY-N LOSS never stopped, the day-N close losing
  (P FAIL = P STOP + P DAY-N LOSS)

with the trade's recap (the side per the config's direction, the entry
at the flip close, the stop at stop_times x the predicted daily
volatility, the success window). The flip's own outcome is not yet
known while it is still open - the printed probabilities are the
prediction. A warning shows when the current config.yaml differs from
the snapshot the model was trained with (the snapshot always wins).

Usage:
  python console_programs/supertrend/predict.py --asset TSLA
  python console_programs/supertrend/predict.py --asset TSLA --date 2026-11-11
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
                        help="the asset whose flip is predicted (the official "
                             "symbol, its display name or an unambiguous part)")
    parser.add_argument('--date', default=None, metavar='YYYY-MM-DD',
                        help="the flip day to read (default: the asset's "
                             "latest flip)")
    parser.add_argument('--config', default=None,
                        help="only used to WARN when it differs from the "
                             "model's training snapshot")
    parser.add_argument('--models-dir', default=str(core.DEFAULT_MODELS),
                        help="where the trained models live "
                             f"(default: {core.DEFAULT_MODELS})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def _find_flip(events, date):
    if date is None:
        return events[-1]
    matches = [e for e in events if e['date'] == date]
    return matches[-1] if matches else None


def run(args):
    if args.asset is None:
        sys.exit("predict.py needs --asset (whose flip is predicted?)")
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
    ev = _find_flip(events, args.date)
    if ev is None:
        sys.exit(f"No supertrend flip of {name} on {args.date} "
                 f"(period {cfg['period']}, multiplier {cfg['multiplier']:g})")

    # the current config is only a warning source - the snapshot wins
    if args.config or core.DEFAULT_CONFIG.exists():
        current = core.load_config(args.config)
        drift = {k: (current[k], cfg[k]) for k in core.CONFIG_KEYS
                 if current.get(k) != cfg.get(k)}
        if drift:
            print("Note: the current config differs from the training "
                  "snapshot - the snapshot is used:")
            for k, (now, then) in sorted(drift.items()):
                print(f"  {k}: now {now!r}, trained {then!r}")

    probs = payload['model'].predict_proba(
        core.event_frame([ev], cfg))[0]
    classes = list(payload['model'].classes_)   # the classes the model saw
    p = {core.OUTCOME_OF[int(c)]: float(probs[i])
         for i, c in enumerate(classes)}

    side = 'LONG' if ev['side'] > 0 else 'SHORT'
    side = core.colored(side, core.GREEN if ev['side'] > 0 else core.RED,
                        use_color)
    flip = 'Up' if ev['flip'] > 0 else 'Down'
    print(f"Supertrend flip prediction {datetime.now().strftime('%Y-%m-%d')} - "
          f"{name} (period {cfg['period']}, multiplier "
          f"{cfg['multiplier']:g}, direction {cfg['direction']}, "
          f"{cfg['days']} days, the stop at {cfg['stop_times']:g}x the "
          f"predicted volatility)")
    print(f"The flip: {ev['date']} - flipped {flip}, the close "
          f"{ev['entry']:.2f}")
    stop = f"{ev['stop']:.2f} ({ev['stop_pct']:.2f} %)" \
        if not np.isnan(ev['stop']) else "- (no volatility model)"
    print(f"The trade: {side} at {ev['entry']:.2f}, the stop at {stop}")
    print("\nThe probabilities:")
    for cls in ('WIN', 'STOP', 'LOSS'):
        value = p.get(cls)
        if value is None:
            print(f"  P {cls:<6} - (never seen in the training data)")
            continue
        cell = f"{value * 100:.1f} %"
        color = core.GREEN if (cls == 'WIN') == (value >= 0.5) else core.RED
        print(f"  P {cls:<6} {core.colored(cell, color, use_color)}")
    fail = p.get('STOP', 0.0) + p.get('LOSS', 0.0)
    print(f"  P FAIL    {fail * 100:.1f} %   (the stop reached + the day-N "
          f"loss)")
    if ev['open']:
        print(f"\nThe flip is still open (fewer than {cfg['days']} bars "
              "since it) - its outcome is not known yet; this is the "
              "prediction")
    else:
        print(f"\nThe outcome of this flip is already known "
              f"({core.OUTCOME_OF[ev['label']]}) - backtest.py shows the "
              f"full evaluation of a past flip")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read a NEW supertrend flip case and print the trained "
                    "model's probabilities: success, stop reached, day-N loss")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()
