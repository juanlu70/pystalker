#!/usr/bin/env python3
"""
core.py - The shared machinery of the supertrend flip trade suite

The three programs of this directory (train.py, predict.py, backtest.py)
share everything through this module: the YAML trade definition, the
event collection (every supertrend flip of an asset's history with the
features and the outcome classes), the volatility lookups (the
volatility_prediction program's walked predictions and its live model)
and the model storage (one .joblib per asset inside models/, with the
config snapshot it was trained with).

The trade, defined by the YAML (the user's design): the entry at the
flip day's close - with the new trend or against it (direction: same |
opposite) - the stop at a DECIMAL (stop_times) times the PREDICTED daily
volatility (the volatility_prediction program), and the three outcomes:

  WIN   0: the stop is never hit within `days` bars AND the day-N close
           is in profit,
  STOP  1: the stop was touched within the window (out at a loss, even
           if the price recovers),
  LOSS  2: never stopped, but the day-N close is losing.

P(FAIL) = P(STOP) + P(LOSS). The flips without `days` future bars are
the still-open ones (the prediction set). The LightGBM classifier (the
volatility program's own factory and seed) is one PER ASSET, trained on
that asset's own flips.
"""
import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pystalker.core.supertrend import supertrend

SEED = 42                      # the volatility program's own seed
EPS = 1e-12
MIN_PRED_VOL = 0.05            # the volatility regression can undershoot zero
MIN_FLIPS = 40                 # fewer labeled flips than this -> no model
CLASSES = ('WIN', 'STOP', 'LOSS')
OUTCOME_OF = {0: 'WIN', 1: 'STOP', 2: 'LOSS'}

GREEN = '\033[32m'
RED = '\033[31m'
RESET = '\033[0m'


def colored(text, color, enabled=True):
    """text wrapped in ANSI codes; the padding must already be applied."""
    return f"{color}{text}{RESET}" if enabled else text

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / 'config.yaml'
DEFAULT_MODELS = HERE / 'models'

# the YAML's valid keys (a typo fails cleanly instead of being ignored)
CONFIG_KEYS = {'days', 'stop_times', 'direction', 'period', 'multiplier',
               'model', 'features'}
FEATURE_KEYS = {'moving_averages', 'rsi', 'stochastic', 'macd', 'atr',
                'bollinger', 'momentum', 'volume'}


def _fail(message):
    print(message)
    sys.exit(1)


def load_config(path=None):
    """The validated trade definition. The path defaults to this
    directory's config.yaml; every value is checked and the unknown keys
    fail with the valid ones listed."""
    import yaml
    path = Path(path) if path else DEFAULT_CONFIG
    if not path.exists():
        _fail(f"Config file not found: {path}")
    try:
        cfg = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        _fail(f"Invalid YAML in {path}: {exc}")
    if not isinstance(cfg, dict):
        _fail(f"Invalid config (a mapping expected): {path}")
    unknown = set(cfg) - CONFIG_KEYS
    if unknown:
        _fail(f"Unknown config keys {sorted(unknown)} - valid: "
              f"{sorted(CONFIG_KEYS)}")
    try:
        cfg['days'] = int(cfg.get('days', 7))
        cfg['period'] = int(cfg.get('period', 10))
        cfg['stop_times'] = float(cfg.get('stop_times', 1.5))
        cfg['multiplier'] = float(cfg.get('multiplier', 1.8))
        cfg['direction'] = str(cfg.get('direction', 'same')).lower()
        cfg['model'] = str(cfg.get('model', 'lightgbm')).lower()
        feats = cfg.get('features', {}) or {}
        unknown = set(feats) - FEATURE_KEYS
        if unknown:
            _fail(f"Unknown feature keys {sorted(unknown)} - valid: "
                  f"{sorted(FEATURE_KEYS)}")
        cfg['features'] = {
            'moving_averages': bool(feats.get('moving_averages', True)),
            'rsi': int(feats.get('rsi', 14) or 0),
            'stochastic': int(feats.get('stochastic', 0) or 0),
            'macd': bool(feats.get('macd', True)),
            'atr': bool(feats.get('atr', True)),
            'bollinger': bool(feats.get('bollinger', True)),
            'momentum': bool(feats.get('momentum', True)),
            'volume': bool(feats.get('volume', True)),
        }
    except (TypeError, ValueError) as exc:
        _fail(f"Invalid value in {path}: {exc}")
    if cfg['days'] < 1:
        _fail("days must be >= 1")
    if cfg['period'] < 1:
        _fail("period must be >= 1")
    if cfg['stop_times'] <= 0:
        _fail("stop_times must be > 0")
    if cfg['direction'] not in ('same', 'opposite'):
        _fail("direction must be 'same' or 'opposite'")
    if cfg['model'] not in ('lightgbm', 'sklearn'):
        _fail("model must be 'lightgbm' or 'sklearn'")
    return cfg


def feature_names(cfg):
    """The model's feature list: the supertrend and volatility context
    always present, the market indicators per the config's switches (the
    RSI/Stochastic periods choose whether they enter at all)."""
    names = ['side', 'age', 'beyond', 'dist_support', 'dist_resist',
             'line_slope', 'pred_vol', 'prob_high', 'stop_pct']
    ft = cfg['features']
    if ft['momentum']:
        names += ['ret1', 'ret5', 'ret7', 'ret20']
    if ft['moving_averages']:
        names += ['sma5', 'sma20', 'sma50', 'ema10', 'ema50', 'sma20_50']
    if ft['rsi']:
        names += ['rsi']
    if ft['stochastic']:
        names += ['stoch_k', 'stoch_d', 'stoch_diff']
    if ft['macd']:
        names += ['macd', 'macd_signal', 'macd_hist']
    if ft['atr']:
        names += ['atr14', 'atr_ratio']
    if ft['bollinger']:
        names += ['bb_pos', 'bb_width']
    names += ['vol10', 'vol_ratio']
    if ft['volume']:
        names += ['volume_z']
    names += ['dow']
    return names


def build_base_features(df, cfg):
    """The per-day market features (backward-looking only), one row per
    bar: everything the config may ask for is computed here and the
    model keeps only feature_names(cfg) of it."""
    o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
    pc = c.shift(1)
    ret = c / pc - 1.0
    f = pd.DataFrame(index=df.index)
    f['ret1'] = ret
    f['ret5'] = c / c.shift(5) - 1.0
    f['ret7'] = c / c.shift(7) - 1.0
    f['ret20'] = c / c.shift(20) - 1.0
    sma20, sma50 = c.rolling(20).mean(), c.rolling(50).mean()
    f['sma5'] = c / c.rolling(5).mean() - 1.0
    f['sma20'] = c / sma20 - 1.0
    f['sma50'] = c / sma50 - 1.0
    f['ema10'] = c / c.ewm(span=10, adjust=False).mean() - 1.0
    f['ema50'] = c / c.ewm(span=50, adjust=False).mean() - 1.0
    f['sma20_50'] = sma20 / sma50 - 1.0
    n = cfg['features']['rsi']
    if n:
        gain = ret.clip(lower=0.0)
        loss = (-ret).clip(lower=0.0)
        f['rsi'] = 100.0 - 100.0 / (1.0 + gain.ewm(alpha=1.0 / n, adjust=False)
                                    .mean()
                                    / (loss.ewm(alpha=1.0 / n, adjust=False)
                                       .mean() + EPS))
    n = cfg['features']['stochastic']
    if n:
        hh = h.rolling(n).max()
        ll = l.rolling(n).min()
        k = (c - ll) / (hh - ll + EPS) * 100.0
        f['stoch_k'] = k
        f['stoch_d'] = k.rolling(3).mean()
        f['stoch_diff'] = k - f['stoch_d']
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    f['macd'] = macd / c * 100.0
    f['macd_signal'] = signal / c * 100.0
    f['macd_hist'] = (macd - signal) / c * 100.0
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    f['atr14'] = tr.rolling(14).mean() / c * 100.0
    f['atr_ratio'] = f['atr14'] / (f['atr14'].rolling(20).mean() + EPS)
    sd20 = c.rolling(20).std()
    f['bb_pos'] = (c - (sma20 - 2.0 * sd20)) / (4.0 * sd20 + EPS)
    f['bb_width'] = 4.0 * sd20 / c * 100.0
    f['vol10'] = ret.abs().rolling(10).mean() * 100.0
    f['vol_ratio'] = f['vol10'] / (ret.abs().rolling(50).mean() * 100.0 + EPS)
    f['volume_z'] = (v - v.rolling(20).mean()) / (v.rolling(20).std() + EPS)
    f['dow'] = df.index.dayofweek
    return f.astype(float)


def collect_flips(df, period, multiplier):
    """Every flip of the asset's history: [(t, direction, crossed, age,
    support, resistance, line_t, line_t5)] - direction +1 = flipped Up,
    -1 = flipped Down; crossed = the broken line's value; age = the ended
    trend's age in bars; support/resistance = the chart pair with the NEW
    trend; line_t/line_t5 = the active line now and 5 bars back."""
    d, line, flip, lb, ub, bl, bu = \
        supertrend(df['High'].to_numpy(), df['Low'].to_numpy(),
                   df['Close'].to_numpy(), period, multiplier)
    n = len(df)
    out = []
    last_change = None
    for t in range(n):
        if d[t] == 0:
            continue
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


def outcome(df, t, side, entry, stop_pct, days):
    """The flip's outcome class: 0 = WIN (never stopped AND the day-N
    close in profit), 1 = STOP (the stop touched within the window), 2 =
    LOSS (never stopped, the day-N close losing); None while the window
    is still open."""
    if t + days >= len(df):
        return None
    stop = entry * (1.0 - side * stop_pct / 100.0)
    if side > 0:                 # long: the lows must stay above the stop
        stopped = bool((df['Low'].iloc[t + 1:t + days + 1] <= stop).any())
    else:                        # short: the highs stay below the stop
        stopped = bool((df['High'].iloc[t + 1:t + days + 1] >= stop).any())
    if stopped:
        return 1
    final = float(df['Close'].iloc[t + days])
    return 0 if side * (final - entry) > 0 else 2


def stop_bar(df, t, side, entry, stop_pct, days):
    """The first bar that touched the stop (None when never): the index
    within the window."""
    stop = entry * (1.0 - side * stop_pct / 100.0)
    if side > 0:
        touched = df['Low'].iloc[t + 1:t + days + 1] <= stop
    else:
        touched = df['High'].iloc[t + 1:t + days + 1] >= stop
    hits = np.nonzero(touched.to_numpy())[0]
    return int(hits[0]) + t + 1 if hits.size else None


def trade_side(flip_direction, cfg):
    """The trade's direction per the config: same = with the new trend,
    opposite = against it."""
    return flip_direction if cfg['direction'] == 'same' else -flip_direction


def open_db_read_only(path):
    """The suite never writes the database - it opens read-only."""
    if not Path(path).exists():
        print(f"Database not found: {path}")
        sys.exit(1)
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True)


def load_walk(conn):
    """The volatility program's walked predictions:
    (symbol, the predicted day) -> (predicted % volatility, high-vol prob).
    predicted_for is the day AFTER the bar that made the prediction, so a
    flip at bar t finds its stop's volatility under bar t+1's day."""
    walk = {}
    try:
        for sym, day_, vol, prob in conn.execute(
                'SELECT symbol, predicted_for, pred_vol, prob '
                'FROM volatility_accuracy_days'):
            walk[(sym, day_)] = (vol, prob)
    except sqlite3.OperationalError:
        pass
    return walk


_VP = None


def load_vp():
    """The volatility_prediction program, loaded lazily once (its model
    factories, its bars loader and its live-model machinery)."""
    global _VP
    if _VP is None:
        path = HERE.parent / 'volatility_prediction.py'
        spec = importlib.util.spec_from_file_location('volatility_prediction',
                                                     path)
        _VP = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_VP)
    return _VP


def live_volatility(conn, sym, model_name):
    """The live model's next-day prediction for one asset (the volatility
    program's own default mode: trained on the whole history, predicting
    tomorrow) - the honest analog of the stored walk for the recent
    days. (volatility %, high-vol probability) or (nan, nan) when the
    asset is too young for a model."""
    vp = load_vp()
    dataset = vp.build_dataset(vp.load_bars(conn, sym))
    if dataset is None:
        return float('nan'), float('nan')
    reg, cls, _ = vp.train_models(model_name, dataset['complete'],
                                  dataset['features'], None)
    vol, prob = vp.predict_models(reg, cls, dataset['next_row'],
                                  dataset['features'])
    return max(vol, MIN_PRED_VOL), (prob if prob is not None else float('nan'))


def asset_events(conn, sym, cfg, walk=None, live_cache=None):
    """Every flip of the asset as a trade per the config: the entry at
    the flip close, the side per direction (same/opposite), the stop at
    stop_times x the predicted volatility, the outcome class. Returns
    (events, skipped): each event a dict with the trade's recap, the
    features (feature_names(cfg)) and 'label' (None while still open)."""
    vp = load_vp()
    df = vp.load_bars(conn, sym)
    if df is None or len(df) < cfg['period'] + 2:
        return [], ['no price data']
    if walk is None:
        walk = load_walk(conn)
    names = feature_names(cfg)
    # the market indicator columns, computed once; the supertrend and
    # volatility context is per event
    market = [n for n in names if n not in
              ('side', 'age', 'beyond', 'dist_support', 'dist_resist',
               'line_slope', 'pred_vol', 'prob_high', 'stop_pct')]
    base = build_base_features(df, cfg)
    base_rows = base[market].to_numpy() if market else None
    col_of = {n: i for i, n in enumerate(market)}
    events, skipped = [], []
    for (t, flip_dir, crossed, age, support, resistance,
         line_t, line_t5) in collect_flips(df, cfg['period'],
                                            cfg['multiplier']):
        entry = float(df['Close'].iloc[t])
        side = trade_side(flip_dir, cfg)
        open_flip = t + cfg['days'] >= len(df)
        nxt = str(df.index[t + 1].date()) if t + 1 < len(df) else None
        row = walk.get((sym, nxt)) if nxt else None
        pred_vol = prob = None
        if row is not None:
            pred_vol = max(float(row[0]), MIN_PRED_VOL) if row[0] is not None \
                else MIN_PRED_VOL
            prob = float(row[1]) if row[1] is not None else float('nan')
        elif open_flip:
            key = (sym, 'live')
            if live_cache is not None and key in live_cache:
                pred_vol, prob = live_cache[key]
            else:
                pred_vol, prob = live_volatility(conn, sym, cfg['model'])
                if live_cache is not None:
                    live_cache[key] = (pred_vol, prob)
        else:
            skipped.append(f"{sym}: the flip of {df.index[t].date()} has no "
                           f"walked volatility prediction")
            continue
        stop_pct = cfg['stop_times'] * (pred_vol if pred_vol is not None
                                        else float('nan'))
        ev = {
            'symbol': sym,
            'date': str(df.index[t].date()),
            't': t, 'flip': flip_dir, 'side': side, 'entry': entry,
            'stop_pct': stop_pct,
            'stop': entry * (1.0 - side * stop_pct / 100.0)
                    if pred_vol is not None else float('nan'),
            'open': open_flip, 'label': None,
            'side_f': float(side), 'age': float(age),
            'beyond': abs(entry - crossed) / abs(crossed) * 100.0
                      if abs(crossed) > EPS else float('nan'),
            'dist_support': (entry - support) / entry * 100.0,
            'dist_resist': (resistance - entry) / entry * 100.0,
            'line_slope': (line_t - line_t5) / entry * 100.0,
            'pred_vol': pred_vol if pred_vol is not None else float('nan'),
            'prob_high': prob if prob is not None else float('nan'),
        }
        for n in market:
            ev[n] = float(base_rows[t][col_of[n]])
        if not open_flip:
            ev['label'] = outcome(df, t, side, entry, stop_pct, cfg['days'])
        events.append(ev)
    return events, skipped


def event_frame(events, cfg):
    """The features matrix of the events (a DataFrame with
    feature_names(cfg) columns, in order)."""
    names = feature_names(cfg)
    key_of = {'side': 'side_f'}          # the event dict's key for 'side'
    return pd.DataFrame([{n: e[key_of.get(n, n)] for n in names}
                         for e in events])


def model_path(models_dir, sym):
    return Path(models_dir) / f'{sym}.joblib'


def save_model(models_dir, sym, model, cfg, labeled, skipped):
    """One .joblib per asset: the classifier, the config SNAPSHOT it was
    trained with, the training date, the outcome counts and the newest
    labeled flip's date (the in-sample marker of the backtest)."""
    import joblib
    Path(models_dir).mkdir(parents=True, exist_ok=True)
    counts = {OUTCOME_OF[k]: sum(1 for e in labeled if e['label'] == k)
              for k in (0, 1, 2)}
    joblib.dump({
        'model': model,
        'config': cfg,
        'features': feature_names(cfg),
        'symbol': sym,
        'trained_at': datetime.now().astimezone(),
        'n_labeled': len(labeled),
        'counts': counts,
        'last_labeled_date': max((e['date'] for e in labeled), default=None),
        'n_skipped': len(skipped),
    }, model_path(models_dir, sym))


def load_model(models_dir, sym):
    """The stored model of an asset: the payload dict, or None."""
    import joblib
    path = model_path(models_dir, sym)
    if not path.exists():
        return None
    return joblib.load(path)
