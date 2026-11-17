#!/usr/bin/env python3
"""
train.py - Train (or retrain) an asset's supertrend flip trade model

One LightGBM model PER ASSET (the user's design), trained on all the
supertrend flips of that asset's history, each flip a trade per the YAML
config (console_programs/supertrend/config.yaml - days for success, the
stop at a decimal times the predicted daily volatility, same or opposite
direction, the indicator switches). The three outcome classes:

  WIN   the stop never hit within `days` bars AND the day-N close in profit
  STOP  the stop touched within the window (out at a loss even if it recovers)
  LOSS  never stopped, but the day-N close losing

The trained model is stored as models/SYMBOL.joblib with the config
snapshot it was trained with, so the predictions (predict.py, backtest.py)
always use the same trade definition. Assets with fewer than
40 labeled flips (or fewer than two outcome classes) are skipped with
their counts - re-train after new data arrives to refresh a model.

Usage:
  python console_programs/supertrend/train.py                  (every asset)
  python console_programs/supertrend/train.py --asset TSLA
  python console_programs/supertrend/train.py --config my.yaml --asset KBWB
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
                        help="train a single asset instead of all")
    parser.add_argument('--config', default=None,
                        help="the trade definition's YAML "
                             f"(default: {core.DEFAULT_CONFIG})")
    parser.add_argument('--models-dir', default=str(core.DEFAULT_MODELS),
                        help="where the trained models are stored "
                             f"(default: {core.DEFAULT_MODELS})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def run(args):
    cfg = core.load_config(args.config)
    vp = core.load_vp()
    vp.check_model_available(cfg['model'])
    use_color = not args.no_color
    conn = core.open_db_read_only(args.db)
    named = vp.load_symbols(conn)
    if args.asset is not None:
        named = [vp.resolve_asset(named, args.asset)]
    walk = core.load_walk(conn)

    print(f"Supertrend flip trade training {datetime.now().strftime('%Y-%m-%d')} "
          f"- period {cfg['period']}, multiplier {cfg['multiplier']:g}, "
          f"direction {cfg['direction']}, {cfg['days']} days, the stop at "
          f"{cfg['stop_times']:g}x the predicted volatility "
          f"({cfg['model']}, seed {core.SEED})")
    print(f"Config: {args.config or core.DEFAULT_CONFIG} | "
          f"models: {args.models_dir}\n")

    trained = skipped = 0
    for sym, name in named:
        events, _ = core.asset_events(conn, sym, cfg, walk)
        labeled = [e for e in events if e['label'] is not None]
        counts = {core.OUTCOME_OF[k]: sum(1 for e in labeled
                                           if e['label'] == k)
                  for k in (0, 1, 2)}
        if len(labeled) < core.MIN_FLIPS:
            print(f"{name}: skipped - {len(labeled)} labeled flips "
                  f"(< {core.MIN_FLIPS})")
            skipped += 1
            continue
        if sum(v > 0 for v in counts.values()) < 2:
            print(f"{name}: skipped - {len(labeled)} labeled flips but only "
                  f"one outcome class ({counts})")
            skipped += 1
            continue
        y = np.array([e['label'] for e in labeled])
        clf = vp.MODEL_FACTORIES[cfg['model']]['classifier']()
        clf.fit(core.event_frame(labeled, cfg), y)
        core.save_model(args.models_dir, sym, clf, cfg, labeled, [])
        ccounts = ', '.join(f"{v} {k}" for k, v in counts.items())
        print(f"{name}: trained on {len(labeled)} flips ({ccounts}) - "
              f"{len([e for e in events if e['open']])} still open - "
              f"{core.model_path(args.models_dir, sym).name} "
              f"{core.colored('stored', core.GREEN, use_color)}")
        trained += 1
    conn.close()
    print(f"\n{trained} model(s) trained, {skipped} skipped")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Train (or retrain) the per-asset supertrend flip trade "
                    "models: every flip a trade per the YAML config, three "
                    "outcome classes, one LightGBM model per asset")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()
