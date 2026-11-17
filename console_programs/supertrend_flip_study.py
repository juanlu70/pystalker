#!/usr/bin/env python3
"""
supertrend_flip_study.py - The failure study of the supertrend flip signals

How often does the supertrend signal fail? (the user's study) Every flip
of every asset - the close crossing the ACTIVE line, the classic signal
(a flip Up breaks the Down/resistance line, a flip Down breaks the
Up/support line) - becomes a trade, its outcome is measured, and a
LightGBM model learns to predict the failure:

  * the trade: the entry at the flip day's CLOSE with the new trend
    (long on a flip Up, short on a flip Down),
  * the stop: 1.5x the PREDICTED VOLATILITY of the volatility_prediction
    program - the honest daily walk stored in volatility_accuracy_days
    (each prediction was made with no future data; the regression can
    undershoot zero, so it is clamped at 0.05 %) - around the entry,
  * WIN: the stop is never hit within --days (default 7) bars AND the
    close --days bars later is in profit,
  * FAIL: the stop was hit (out at a loss even if it recovers) or the
    --days close is losing. The flips without --days future bars are
    the still-open ones - the prediction set.

The features (everything known at the flip): the supertrend context (the
trade's side, the age of the trend that just ended, the beyond % of the
crossed line, the distances to both channel lines, the line's slope),
the predicted volatility and its high-volatility probability, the
averages (SMA 5/20/50 and EMA 10/50 ratios, the SMA20/50 cross), RSI(14),
MACD 12/26/9 (normalized), ATR(14) and its ratio, the Bollinger(20, 2)
position and width, the momentum (1/5/7/20-day returns), the realized
volatility, the volume z-score and the day of the week.

The model: the 80/20 check with a CHRONOLOGICAL split (the user's
choice) - the earlier 80% of the labeled flips (by date) trains the
LightGBM classifier and the latest 20% is checked (accuracy, ROC AUC,
precision/recall of the failures, the confusion matrix, against the
naive majority baseline). Then the final model trains on ALL the
labeled flips and predicts the STILL-OPEN ones (the last --days days):
the failure probability of every flip whose outcome is not known yet.

The still-open flips' volatility comes from the live volatility model
(volatility_prediction.py's own machinery trained on the asset's whole
history, predicting the next day - the honest analog of the stored walk,
which only reaches the walk's last run).

The database is only read (mode=ro); the program is standalone, like
the volatility programs (not wired into pystalker_cli.py).

Usage:
  python console_programs/supertrend_flip_study.py
  python console_programs/supertrend_flip_study.py --asset TSLA
  python console_programs/supertrend_flip_study.py --days 10 --stop-mult 2
  python console_programs/supertrend_flip_study.py --model sklearn --no-color
"""
import argparse
import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.supertrend import (SUPERTREND_MULTIPLIER, SUPERTREND_PERIOD,
                                       supertrend)

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'

EPS = 1e-12
SEED = 42                      # the volatility program's own seed
MIN_PRED_VOL = 0.05            # the regression can undershoot zero (%)

# the study's features: the flip's supertrend context + the market context
EVENT_FEATURES = ['long', 'age', 'beyond', 'dist_support', 'dist_resist',
                  'line_slope', 'pred_vol', 'prob_high', 'stop_pct']
BASE_FEATURES = [
    'ret1', 'ret5', 'ret7', 'ret20',
    'sma5', 'sma20', 'sma50', 'ema10', 'ema50', 'sma20_50',
    'rsi14', 'macd', 'macd_signal', 'macd_hist',
    'atr14', 'atr_ratio', 'bb_pos', 'bb_width',
    'vol10', 'vol_ratio', 'volume_z', 'dow',
]
FEATURES = EVENT_FEATURES + BASE_FEATURES


def colored(text, color, enabled=True):
    """text wrapped in ANSI codes; the padding must already be applied."""
    return f"{color}{text}{RESET}" if enabled else text


def _load_sibling(name):
    """A sibling console program (loaded for its machinery) - the same lazy
    file-based loading the other tools use."""
    path = Path(__file__).resolve().parent / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def open_db_read_only(path):
    """The study never writes - the database opens read-only."""
    if not Path(path).exists():
        print(f"Database not found: {path}")
        sys.exit(1)
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def build_parser(parser):
    """This tool's flags, shared by the standalone program and any caller."""
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--asset', default=None,
                        help="study a single asset instead of all (the "
                             "official symbol, its display name or an "
                             "unambiguous part of either)")
    parser.add_argument('--period', type=int, default=SUPERTREND_PERIOD,
                        help=f"the supertrend's ATR period "
                             f"(default: {SUPERTREND_PERIOD})")
    parser.add_argument('--multiplier', type=float, default=SUPERTREND_MULTIPLIER,
                        help=f"the supertrend's multiplier "
                             f"(default: {SUPERTREND_MULTIPLIER:g})")
    parser.add_argument('--days', type=int, default=7, metavar='N',
                        help="the outcome window: the trade must be winning "
                             "N bars after the flip (default: 7)")
    parser.add_argument('--stop-mult', type=float, default=1.5, metavar='X',
                        help="the stop distance: X times the predicted "
                             "volatility (default: 1.5)")
    parser.add_argument('--model', default='lightgbm', choices=['lightgbm', 'sklearn'],
                        help="the ML algorithm (default: lightgbm; sklearn = "
                             "scikit-learn's HistGradientBoosting)")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def build_base_features(df):
    """The per-day market features (backward-looking only), one row per bar -
    the averages, RSI, MACD, ATR, Bollinger, momentum, volatility and
    volume of the study."""
    o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
    pc = c.shift(1)
    ret = c / pc - 1.0
    f = pd.DataFrame(index=df.index)
    f['ret1'] = ret
    f['ret5'] = c / c.shift(5) - 1.0
    f['ret7'] = c / c.shift(7) - 1.0
    f['ret20'] = c / c.shift(20) - 1.0
    f['sma5'] = c / c.rolling(5).mean() - 1.0
    f['sma20'] = c / c.rolling(20).mean() - 1.0
    f['sma50'] = c / c.rolling(50).mean() - 1.0
    f['ema10'] = c / c.ewm(span=10, adjust=False).mean() - 1.0
    f['ema50'] = c / c.ewm(span=50, adjust=False).mean() - 1.0
    f['sma20_50'] = c.rolling(20).mean() / c.rolling(50).mean() - 1.0
    # RSI(14), Wilder's smoothing
    gain = ret.clip(lower=0.0)
    loss = (-ret).clip(lower=0.0)
    f['rsi14'] = 100.0 - 100.0 / (1.0 + gain.ewm(alpha=1.0 / 14, adjust=False).mean()
                                  / (loss.ewm(alpha=1.0 / 14, adjust=False).mean()
                                     + EPS))
    # MACD 12/26/9, normalized by the close
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    f['macd'] = macd / c * 100.0
    f['macd_signal'] = signal / c * 100.0
    f['macd_hist'] = (macd - signal) / c * 100.0
    # ATR(14) as a percent of the close, and vs its own 20-bar mean
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    f['atr14'] = tr.rolling(14).mean() / c * 100.0
    f['atr_ratio'] = f['atr14'] / (f['atr14'].rolling(20).mean() + EPS)
    # the Bollinger(20, 2) position and width
    m20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    f['bb_pos'] = (c - (m20 - 2.0 * sd20)) / (4.0 * sd20 + EPS)
    f['bb_width'] = 4.0 * sd20 / c * 100.0
    # the realized close-to-close volatility and its trend
    f['vol10'] = ret.abs().rolling(10).mean() * 100.0
    f['vol_ratio'] = f['vol10'] / (ret.abs().rolling(50).mean() * 100.0 + EPS)
    # the volume z-score and the day of the week
    f['volume_z'] = (v - v.rolling(20).mean()) / (v.rolling(20).std() + EPS)
    f['dow'] = df.index.dayofweek
    return f.astype(float)


def collect_flips(df, period, multiplier):
    """Every flip of the asset's history: [(t, direction, crossed, age,
    support, resistance, line_t, line_t5)] - direction +1 = flipped Up (the
    close broke the Down/resistance line, a LONG), -1 = flipped Down (the
    close broke the Up/support line, a SHORT); crossed = the broken line's
    value, age = the ended trend's age in bars, support/resistance = the
    chart pair with the NEW trend, line_t/line_t5 = the active line now and
    5 bars back (its slope)."""
    d, line, flip, lb, ub, bl, bu = \
        supertrend(df['High'].to_numpy(), df['Low'].to_numpy(),
                   df['Close'].to_numpy(), period, multiplier)
    n = len(df)
    out = []
    last_change = None                 # the last flip or the seeded first bar
    for t in range(n):
        if d[t] == 0:
            continue                   # still in the warm-up
        if last_change is None:
            last_change = t
        if flip[t]:
            old_dir = d[t - 1]
            crossed = float(lb[t] if old_dir == 1 else ub[t])
            direction = 1 if d[t] > 0 else -1
            support = float(lb[t] if direction > 0 else bl[t])
            resistance = float(bu[t] if direction > 0 else ub[t])
            t5 = max(t - 5, int(np.argmax(d != 0)))
            out.append((t, direction, crossed, int(t - last_change),
                        support, resistance, float(line[t]),
                        float(line[t5])))
            last_change = t
    return out


def outcome_label(df, t, direction, entry, stop_pct, days):
    """The flip's outcome: 1 = FAIL (the stop hit within the window, or the
    --days close losing), 0 = WIN (never stopped AND in profit), None when
    the window is still open (fewer than --days future bars)."""
    if t + days >= len(df):
        return None
    stop = entry * (1.0 - direction * stop_pct / 100.0)
    if direction > 0:                 # long: the lows must stay above the stop
        stopped = bool((df['Low'].iloc[t + 1:t + days + 1] <= stop).any())
    else:                             # short: the highs stay below the stop
        stopped = bool((df['High'].iloc[t + 1:t + days + 1] >= stop).any())
    final = float(df['Close'].iloc[t + days])
    win = (not stopped) and direction * (final - entry) > 0
    return int(not win)


def run(args):
    use_color = not args.no_color
    vp = _load_sibling('volatility_prediction')
    vp.check_model_available(args.model)
    conn = open_db_read_only(args.db)

    # the volatility program's walked predictions: (symbol, the predicted
    # day) -> (the predicted percent volatility, the high-vol probability).
    # predicted_for is the day AFTER the bar that made the prediction, so a
    # flip at bar t finds its stop's volatility under bar t+1's day.
    walk = {}
    try:
        for sym, day, vol, prob in conn.execute(
                'SELECT symbol, predicted_for, pred_vol, prob '
                'FROM volatility_accuracy_days'):
            walk[(sym, day)] = (vol, prob)
    except sqlite3.OperationalError:
        pass
    if not walk:
        print("Note: volatility_accuracy_days is empty - run "
              "volatility_accuracy.py --daily first; without the walked "
              "predictions only the still-open flips (the live volatility "
              "model) can be studied\n")

    # the assets (the --asset filter keeps the study on one asset)
    named = vp.load_symbols(conn)
    if args.asset is not None:
        named = [vp.resolve_asset(named, args.asset)]
    names = {sym: name for sym, name in named}

    events = []                       # the flips with their features
    skipped_no_vol = skipped_early = 0
    n_flips = 0
    for sym, _ in named:
        df = vp.load_bars(conn, sym)
        if df is None or len(df) < args.period + 2:
            continue
        base = build_base_features(df)
        base_cols = {name: i for i, name in enumerate(base.columns)}
        base_rows = base.to_numpy()
        flips = collect_flips(df, args.period, args.multiplier)
        n_flips += len(flips)
        for (t, direction, crossed, age, support, resistance,
             line_t, line_t5) in flips:
            entry = float(df['Close'].iloc[t])
            open_flip = t + args.days >= len(df)
            # the stop's volatility: the walk's prediction for the day after
            # the flip bar (made at the flip bar, no future leaked); the
            # still-open flips fall back to the live model (filled later)
            nxt = str(df.index[t + 1].date()) if t + 1 < len(df) else None
            row = walk.get((sym, nxt)) if nxt else None
            if row is None and not open_flip:
                skipped_no_vol += 1
                continue
            # the supertrend context at the flip bar
            beyond = abs(entry - crossed) / abs(crossed) * 100.0 \
                if abs(crossed) > EPS else float('nan')
            ev = {
                'symbol': sym, 'name': names[sym],
                'date': str(df.index[t].date()),
                't': t, 'direction': direction, 'entry': entry,
                'long': 1.0 if direction > 0 else 0.0,
                'age': float(age), 'beyond': beyond,
                'dist_support': (entry - support) / entry * 100.0,
                'dist_resist': (resistance - entry) / entry * 100.0,
                'line_slope': (line_t - line_t5) / entry * 100.0,
                'pred_vol': None, 'prob_high': None, 'stop_pct': None,
                'open': open_flip, 'label': None,
            }
            if row is not None:
                vol, prob = row
                ev['pred_vol'] = max(float(vol), MIN_PRED_VOL) \
                    if vol is not None else MIN_PRED_VOL
                ev['prob_high'] = float(prob) if prob is not None \
                    else float('nan')
                ev['stop_pct'] = args.stop_mult * ev['pred_vol']
            for name in BASE_FEATURES:
                ev[name] = float(base_rows[t][base_cols[name]])
            # the labeled flips need complete features (the averages' warm-up
            # and the supertrend context); the still-open ones keep missing
            # values - the model handles them natively
            if not open_flip:
                ev['label'] = outcome_label(df, t, direction, entry,
                                            ev['stop_pct'], args.days)
                if np.isnan([ev[f] for f in FEATURES]).any():
                    skipped_early += 1
                    continue
            events.append(ev)
    conn.close()

    labeled = [e for e in events if e['label'] is not None]
    opens = [e for e in events if e['open']]
    n_fail = sum(e['label'] for e in labeled)

    # ---- the report
    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Supertrend flip failure study {datetime.now().strftime('%Y-%m-%d')} "
          f"(period {args.period}, multiplier {args.multiplier:g}) - every flip "
          "is a trade with the new trend, the entry at the flip close, the "
          f"stop at {args.stop_mult:g}x the predicted volatility, winning "
          f"after {args.days} days")
    scope = f" of {args.asset}" if args.asset is not None else " of every asset"
    print(f"The flips{scope}: {n_flips} collected")
    if n_flips == 0:
        print("No flips - nothing to study")
        return
    if labeled:
        rate = n_fail / len(labeled) * 100.0
        failed_s = f"{n_fail} failed ({rate:.2f} %)"
        won_s = f"{len(labeled) - n_fail} won ({100.0 - rate:.2f} %)"
        print(f"  labeled (the outcome known): {len(labeled)} - "
              f"{colored(failed_s, RED, use_color)}, "
              f"{colored(won_s, GREEN, use_color)}")
    if skipped_no_vol:
        print(f"  skipped: {skipped_no_vol} without the stored volatility "
              f"prediction (not in the daily walk)"
              + (f", {skipped_early} too early for the features"
                 if skipped_early else ''))
    elif skipped_early:
        print(f"  skipped: {skipped_early} too early for the features")
    print(f"  still open (the last {args.days} bars, the prediction set): "
          f"{len(opens)}\n")

    if not labeled or len(np.unique([e['label'] for e in labeled])) < 2:
        print("Not enough labeled flips of both outcomes to train a model")
        return

    # the chronological split: the earlier 80% trains, the latest 20% checks
    labeled.sort(key=lambda e: (e['date'], e['symbol']))
    n_train = int(len(labeled) * 0.8)
    if n_train < 2:
        # LightGBM cannot fit a single row (and no honest split exists there)
        print(f"Too few labeled flips ({len(labeled)}) for the 80/20 split - "
              "the base failure rate above is the study's result")
        return
    train, test = labeled[:n_train], labeled[n_train:]

    def frame(evs):
        return pd.DataFrame([{f: e[f] for f in FEATURES} for e in evs])

    Xtr, ytr = frame(train), np.array([e['label'] for e in train])
    Xte, yte = frame(test), np.array([e['label'] for e in test])
    clf = vp.MODEL_FACTORIES[args.model]['classifier']()
    clf.fit(Xtr, ytr)
    pte = clf.predict_proba(Xte)[:, 1]
    pred = (pte >= 0.5).astype(int)

    from sklearn.metrics import (accuracy_score, confusion_matrix,
                                 precision_score, recall_score, roc_auc_score)
    acc = accuracy_score(yte, pred)
    try:
        auc = roc_auc_score(yte, pte)
    except ValueError:
        auc = None                     # a one-class test window
    prec = precision_score(yte, pred, zero_division=0)
    rec = recall_score(yte, pred, zero_division=0)
    cm = confusion_matrix(yte, pred, labels=[0, 1])
    naive = max(ytr.mean(), 1.0 - ytr.mean())   # always the train's majority

    print(f"The 80/20 chronological check ({args.model}, seed {SEED}): "
          f"{len(train)} trained (through {train[-1]['date']}), "
          f"{len(test)} checked (from {test[0]['date']})")
    print(f"  the test's failures: {int(yte.sum())} of {len(yte)} "
          f"({yte.mean() * 100:.2f} %) - the train's rate was "
          f"{ytr.mean() * 100:.2f} %")
    print(f"  accuracy {acc * 100:.2f} % (the naive majority baseline: "
          f"{naive * 100:.2f} %)")
    if auc is not None:
        print(f"  ROC AUC {auc:.4f} - the failure recall {rec * 100:.2f} %, "
              f"the failure precision {prec * 100:.2f} %")
    print("  the confusion (rows: the real win/fail, columns: the call): "
          f"win->win {cm[0, 0]}, win->fail {cm[0, 1]}, "
          f"fail->win {cm[1, 0]}, fail->fail {cm[1, 1]}\n")

    # the final model: every labeled flip, then the still-open predictions
    Xall, yall = frame(labeled), np.array([e['label'] for e in labeled])
    final = vp.MODEL_FACTORIES[args.model]['classifier']()
    final.fit(Xall, yall)
    imps = sorted(zip(FEATURES, final.feature_importances_),
                  key=lambda x: -(x[1] if x[1] == x[1] else 0.0))[:10]
    top = max((imp for _, imp in imps), default=0.0)
    print("The final model (trained on every labeled flip) - the top features:")
    for name, imp in imps:
        bar = int(imp / top * 30) if top > 0 and imp == imp else 0
        print(f"  {name:<14} {imp:7.0f}  {'#' * bar}")
    print()

    if not opens:
        print(f"No still-open flips - every flip of the last {args.days} bars "
              "has its outcome; run again after a new flip")
        return
    # the still-open flips without a walked volatility prediction get the
    # LIVE model's next-day prediction (the program's own default mode)
    need_live = sorted({e['symbol'] for e in opens if e['pred_vol'] is None})
    if need_live:
        conn = open_db_read_only(args.db)
        for sym in need_live:
            dataset = vp.build_dataset(vp.load_bars(conn, sym))
            reg = cls = None
            if dataset is not None:
                reg, cls, _ = vp.train_models(args.model, dataset['complete'],
                                              dataset['features'], None)
            for e in opens:
                if e['symbol'] != sym or e['pred_vol'] is not None:
                    continue
                if reg is None:
                    e['pred_vol'] = float('nan')   # too young for a live model
                    e['stop_pct'] = float('nan')
                    continue
                vol, prob = vp.predict_models(reg, cls, dataset['next_row'],
                                              dataset['features'])
                e['pred_vol'] = max(vol, MIN_PRED_VOL)
                e['prob_high'] = prob if prob is not None else float('nan')
                e['stop_pct'] = args.stop_mult * e['pred_vol']
        conn.close()
    Xop = frame(opens)
    for e, p in zip(opens, final.predict_proba(Xop)[:, 1]):
        e['p_fail'] = float(p)
    opens.sort(key=lambda e: -e['p_fail'])
    print(f"The prediction - the {len(opens)} still-open flip(s), the most "
          "likely failures first:")
    print(f"{'P FAIL':>7}  {'FLIP DAY':<10}  {'ASSET':<26}  {'SIDE':<5}  "
          f"{'ENTRY':>10}  {'STOP':>10}  {'STOP %':>7}")
    for e in opens:
        stop = e['entry'] * (1.0 - e['direction'] * e['stop_pct'] / 100.0) \
            if not np.isnan(e['stop_pct']) else float('nan')
        # too young for the live volatility model: no stop computable ('-')
        stop_s = f"{stop:>10.2f}" if not np.isnan(stop) else f"{'-':>10}"
        stoppct_s = f"{e['stop_pct']:>6.2f}%" \
            if not np.isnan(e['stop_pct']) else f"{'-':>7}"
        side = colored('LONG', GREEN, use_color) if e['direction'] > 0 \
            else colored('SHORT', RED, use_color)
        pf = f"{e['p_fail'] * 100:.1f} %"
        pf = colored(f"{pf:>7}", RED if e['p_fail'] >= 0.6 else
                     (GREEN if e['p_fail'] <= 0.4 else None), use_color)
        print(f"{pf}  {e['date']:<10}  {e['name']:<26}  {side:<5}  "
              f"{e['entry']:>10.2f}  {stop_s}  {stoppct_s}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The supertrend flip failure study: label every flip as a "
                    "trade (the stop at 1.5x the predicted volatility, winning "
                    "after 7 days), learn the failures with LightGBM, check on "
                    "the latest 20% and predict the still-open flips")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()
