#!/usr/bin/env python3
"""
volatility_prediction.py - Predict the next day's percent volatility (ML test)

Standalone machine-learning experiment - INDEPENDENT of the rest of the
project for now: it reads the OHLCV bars straight from the SQLite database
(READ-ONLY, it never writes anything) and answers one question per asset:
how volatile will tomorrow be?

For every asset it trains ONE MODEL PER ASSET (its own history only) with a
pluggable ML algorithm (default LightGBM; --model sklearn switches to
scikit-learn's histogram gradient boosting; adding another algorithm is one
entry in MODEL_FACTORIES). Each model is trained on the full OHLCV history
through backward-looking daily features - returns, gaps, ranges, candle
shape, ATR/true range, rolling volatilities and their ratios, distance to
moving averages and recent extremes, volume z-score, weekday - all
computable at day t without any knowledge of day t+1. The two targets:

  - regression: the next day's PERCENT VOLATILITY (|close-to-close
    return| * 100)
  - classification: is it a HIGH-VOLATILITY day or not - high = an actual
    volatility above the asset's own MEDIAN (measured on the training
    data) - and the model outputs its PROBABILITY (0-100%)

Modes:
  - default: predicts the day after the last stored bar of every asset
  - --asset SYMBOL: only that asset, with a verbose single-asset report
    (training range, feature importances) - the official symbol, its
    personalized display name, or an unambiguous part of either
  - --final-date YYYY-MM-DD: HISTORICAL TEST - train ONLY with data
    strictly before that date, then predict every bar from it on,
    out-of-sample, comparing predicted vs actual volatility (regression
    metrics: MAE, RMSE, skill vs the naive "tomorrow = today" predictor,
    correlation; classification metrics: accuracy, precision, recall,
    ROC AUC; plus a sample of the daily predictions)

The listings show the assets' PERSONALIZED DISPLAY NAMES - the same
"{symbol} (name)" values stored in the application's ticker list and
Operations - not the official tickers; an asset without a display name
falls back to its official symbol. The models always fetch and train by
the official symbol underneath.

Usage:
  python console_programs/volatility_prediction.py
  python console_programs/volatility_prediction.py --asset ES=F
  python console_programs/volatility_prediction.py --asset Samsung
  python console_programs/volatility_prediction.py --asset ES=F --final-date 2026-06-30
  python console_programs/volatility_prediction.py --final-date 2026-06-30
  python console_programs/volatility_prediction.py --model sklearn --no-color
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')
SEED = 42
EPS = 1e-12
MIN_TRAIN_ROWS = 40           # fewer usable training rows than this -> no model
WARMUP_BARS = 101             # the longest feature look-back (100) + one shift
MIN_BARS_DEFAULT = 250        # ~150 usable rows after the warm-up at the minimum

GREEN = '\033[32m'
RED = '\033[31m'
YELLOW = '\033[33m'
BOLD = '\033[1m'
RESET = '\033[0m'


def colored(text, color, enabled=True, bold=False):
    """text wrapped in ANSI codes; the padding must already be applied
    (the escapes would break the column alignment otherwise)."""
    if not enabled:
        return text
    prefix = (BOLD if bold else '') + (color or '')
    return f"{prefix}{text}{RESET}" if prefix else text


def prob_color(prob, enabled):
    """green = probably a quiet day, red = probably a volatile one."""
    if prob is None:
        return None
    if prob >= 0.60:
        return RED if enabled else None
    if prob <= 0.40:
        return GREEN if enabled else None
    return None


# --------------------------------------------------------------- database

def open_db_read_only(path):
    """Connect READ-ONLY: the database is never touched, not even by accident."""
    return sqlite3.connect('file:' + quote(str(Path(path).resolve()), safe='/')
                           + '?mode=ro', uri=True)


def load_symbols(conn):
    """(official symbol, personalized display name) per stored asset. The
    display name lives in each asset's "{symbol}_settings" table under the
    'display_name' key - the same place the application stores it - and
    falls back to the official symbol when unset, exactly like the ticker
    list and Operations do."""
    try:
        symbols = [r[0] for r in conn.execute(
            "SELECT symbol FROM symbols ORDER BY symbol").fetchall()]
    except sqlite3.OperationalError:
        sys.exit("The database has no symbols table - is this a pystalker database?")
    assets = []
    for symbol in symbols:
        name = ''
        try:
            row = conn.execute(
                f'SELECT value FROM "{symbol}_settings" WHERE key = ?',
                ('display_name',)).fetchone()
            name = row[0] if row and row[0] else ''
        except sqlite3.Error:
            name = ''
        assets.append((symbol, name or symbol))
    return assets


def load_bars(conn, symbol):
    """The full OHLCV history of one asset, or None when it has none."""
    try:
        rows = conn.execute(
            f'SELECT timestamp, open, high, low, close, volume FROM "{symbol}_bars" '
            f'ORDER BY timestamp').fetchall()
    except sqlite3.OperationalError:
        return None
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
    for col in ('Open', 'High', 'Low', 'Close', 'Volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    # the app renders timestamps with the local timezone - do the same so the
    # dates here match the charts
    local_tz = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
    df['Date'] = pd.to_datetime(df['ts'], unit='s', utc=True) \
        .dt.tz_convert(local_tz).dt.tz_localize(None)
    df = df.dropna(subset=['Date']).drop_duplicates(subset='Date', keep='last')
    df = df.set_index('Date').sort_index()
    # defensive: prices must be numbers and positive (the garbage-bar cleaner
    # already removed the impossible candles from the live database)
    df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])
    df = df[(df[['Open', 'High', 'Low', 'Close']] > 0).all(axis=1)]
    df['Volume'] = df['Volume'].fillna(0.0)
    return df[['Open', 'High', 'Low', 'Close', 'Volume']]


# --------------------------------------------------------------- features

def build_dataset(df):
    """One row per day t: backward-looking features + the target (day t+1's
    percent volatility, |close-to-close return| * 100) + the predicted day's
    date. Returns {'features': names, 'complete': the rows with a known
    target (the train/test material), 'next_row': the last bar's features
    (its target, tomorrow, is still unknown), 'next_date': the day it
    predicts} or None when the history is too short.

    Every feature uses data up to day t ONLY - the next day enters solely
    through the target, so a row never contains information about the day
    it predicts.
    """
    if len(df) < WARMUP_BARS + 2:
        return None
    o, h, l, c, v = df['Open'], df['High'], df['Low'], df['Close'], df['Volume']
    pc = c.shift(1)
    ret = c / pc - 1.0

    f = pd.DataFrame(index=df.index)
    f['ret'] = ret
    f['gap'] = o / pc - 1.0                       # overnight gap
    f['rng'] = (h - l) / (c + EPS)                # intraday range / close
    f['close_pos'] = (c - l) / (h - l + EPS)      # close within the day range
    f['body'] = (c - o).abs() / (c + EPS)
    co_max = pd.concat([c, o], axis=1).max(axis=1)
    co_min = pd.concat([c, o], axis=1).min(axis=1)
    f['up_wick'] = (h - co_max) / (c + EPS)
    f['dn_wick'] = (co_min - l) / (c + EPS)
    f['ret_5'] = c / c.shift(5) - 1.0
    f['ret_10'] = c / c.shift(10) - 1.0
    f['vol_5'] = ret.rolling(5).std() * 100       # close-to-close vol windows
    f['vol_10'] = ret.rolling(10).std() * 100
    f['vol_21'] = ret.rolling(21).std() * 100
    f['vol_ratio'] = f['vol_5'] / (f['vol_21'] + EPS)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1) \
        / (c + EPS) * 100                         # true range %
    f['tr'] = tr
    f['atr_14'] = tr.rolling(14).mean()
    f['atr_ratio'] = f['atr_14'] / (f['vol_21'] + EPS)   # intraday vs cc vol
    f['vol_lag1'] = ret.abs() * 100              # today's realized volatility
    f['vol_lag2'] = ret.abs().shift(1) * 100
    f['vol_lag3'] = ret.abs().shift(2) * 100
    f['vol_mean5'] = ret.abs().rolling(5).mean() * 100
    f['vol_mean21'] = ret.abs().rolling(21).mean() * 100
    f['vol_ma_ratio'] = f['vol_mean5'] / (f['vol_mean21'] + EPS)
    m100 = ret.abs().rolling(100)
    f['vol_z100'] = (f['vol_lag1'] - m100.mean() * 100) / (m100.std() * 100 + EPS)
    f['dist_sma20'] = c / c.rolling(20).mean() - 1.0
    f['dist_sma50'] = c / c.rolling(50).mean() - 1.0
    f['dist_high20'] = c / h.rolling(20).max() - 1.0      # <= 0
    f['dist_low20'] = c / l.rolling(20).min() - 1.0       # >= 0
    v_mean, v_std = v.rolling(20).mean(), v.rolling(20).std()
    f['volume_z'] = (v - v_mean) / (v_std + EPS)
    f['volume_ratio'] = v / (v_mean + EPS)
    f['dow'] = df.index.dayofweek
    f = f.astype(float)                          # uniform float64 features

    y = (c.shift(-1) / c - 1.0).abs() * 100       # day t+1's percent volatility
    target_date = df.index.to_series().shift(-1)  # the day being predicted

    features = list(f.columns)
    data = pd.concat([f, y.rename('y'), target_date.rename('tdate')], axis=1)
    complete = data.dropna()                       # usable history (known target)
    if len(complete) < MIN_TRAIN_ROWS:
        return None
    next_row = data.iloc[-1]                      # tomorrow's input features
    if next_row[features].isna().any():
        return None
    return {'features': features, 'complete': complete, 'next_row': next_row,
            'last_bar': df.index[-1],
            'next_date': df.index[-1] + pd.Timedelta(days=1)}


# --------------------------------------------------------------- models

# The pluggable ML algorithms: adding one = a pair of factory functions here
# plus one dict entry. The rest of the script only calls fit / predict /
# predict_proba, so any scikit-learn-style regressor/classifier works.
def _lightgbm_regressor():
    import lightgbm as lgb
    return lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=15,
                             min_child_samples=15, subsample=0.9, subsample_freq=1,
                             colsample_bytree=0.9, random_state=SEED, verbosity=-1)


def _lightgbm_classifier():
    import lightgbm as lgb
    return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=15,
                              min_child_samples=15, subsample=0.9, subsample_freq=1,
                              colsample_bytree=0.9, random_state=SEED, verbosity=-1)


def _sklearn_regressor():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05,
                                         max_leaf_nodes=15, min_samples_leaf=15,
                                         random_state=SEED)


def _sklearn_classifier():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05,
                                          max_leaf_nodes=15, min_samples_leaf=15,
                                          random_state=SEED)


MODEL_FACTORIES = {
    'lightgbm': {'regressor': _lightgbm_regressor, 'classifier': _lightgbm_classifier},
    'sklearn': {'regressor': _sklearn_regressor, 'classifier': _sklearn_classifier},
}


def check_model_available(name):
    if name == 'lightgbm':
        try:
            import lightgbm  # noqa: F401
        except ImportError:
            sys.exit("lightgbm is not installed - install it (pip install lightgbm) "
                     "or use --model sklearn")
    elif name == 'sklearn':
        try:
            import sklearn  # noqa: F401
        except ImportError:
            sys.exit("scikit-learn is not installed - use --model lightgbm")


def train_models(name, train_rows, features):
    """Fit the per-asset pair: the volatility regressor and the high-volatility
    classifier (its threshold = the training data's median volatility).
    Returns (regressor, classifier-or-None, threshold)."""
    X = train_rows[features]
    y = train_rows['y']
    threshold = float(np.median(y.to_numpy()))
    reg = MODEL_FACTORIES[name]['regressor']()
    reg.fit(X, y)
    labels = (y.to_numpy() > threshold).astype(int)
    cls = None
    if np.unique(labels).size == 2:            # a constant label trains nothing
        cls = MODEL_FACTORIES[name]['classifier']()
        cls.fit(X, labels)
    return reg, cls, threshold


def predict_models(reg, cls, row, features):
    """(predicted percent volatility, probability of a high-volatility day)."""
    # the row is a mixed-dtype Series (it also carries the target date), so
    # cast: the ML libraries need plain numeric columns
    X = row[features].to_frame().T.astype(float)
    vol = float(reg.predict(X)[0])
    prob = None
    if cls is not None:
        prob = float(cls.predict_proba(X)[0, 1])
    return vol, prob


# --------------------------------------------------------------- metrics

def prob_from_cell(text):
    """The probability value behind a formatted '63.2 %' table cell, or None
    ('-', empty, the '...' separator row...)."""
    text = text.strip()
    if not text or text == '-' or set(text) == {'.'}:
        return None
    return float(text.split()[0]) / 100


def rank_auc(y_true, score):
    """Mann-Whitney ROC AUC with tie-corrected ranks (no extra dependencies);
    None when the sample holds a single class."""
    y_true = np.asarray(y_true, dtype=bool)
    score = np.asarray(score, dtype=float)
    n_pos = int(y_true.sum())
    n_neg = int((~y_true).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = pd.Series(score).rank(method='average').to_numpy()
    return float((ranks[y_true].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def regression_metrics(actual, pred, naive):
    actual, pred, naive = (np.asarray(x, float) for x in (actual, pred, naive))
    out = {'mae': float(np.mean(np.abs(pred - actual))),
           'rmse': float(np.sqrt(np.mean((pred - actual) ** 2))),
           'mae_naive': float(np.mean(np.abs(naive - actual)))}
    out['skill'] = (1.0 - out['mae'] / out['mae_naive']
                    if out['mae_naive'] > 0 else None)
    out['pearson'] = (float(np.corrcoef(pred, actual)[0, 1])
                      if np.std(pred) > 0 and np.std(actual) > 0 else None)
    out['spearman'] = (float(pd.Series(pred).corr(pd.Series(actual), method='spearman'))
                       if len(actual) > 2 and np.std(pred) > 0 else None)
    return out


def classification_metrics(actual, prob, threshold):
    """High-volatility day = an actual volatility strictly above the threshold.
    The prediction counts as high when its probability >= 50%."""
    y_true = np.asarray(actual, float) > threshold
    y_pred = np.asarray(prob, float) >= 0.5
    tp = int(np.sum(y_true & y_pred))
    fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred))
    n = len(y_true)
    out = {'accuracy': float(np.mean(y_true == y_pred)),
           'n_high': int(y_true.sum()), 'n': n}
    out['precision'] = tp / (tp + fp) if tp + fp else None
    out['recall'] = tp / (tp + fn) if tp + fn else None
    n_neg = n - int(y_true.sum())
    spec = (n_neg - fp) / n_neg if n_neg else None
    out['balanced'] = (out['recall'] + spec) / 2 if spec is not None else None
    out['auc'] = rank_auc(y_true, np.asarray(prob, float))
    return out


# --------------------------------------------------------------- backtest / prediction

def run_backtest(dataset, final_date, model_name):
    """The split-at-date historical test: train ONLY with the rows whose
    predicted day lies strictly before final_date, then predict every
    following bar out-of-sample. Returns {'skip': reason} or the metrics
    plus the per-day frame."""
    complete = dataset['complete']
    cut = pd.Timestamp(final_date)
    train = complete[complete['tdate'] < cut]
    test = complete[complete['tdate'] >= cut]
    if len(train) < MIN_TRAIN_ROWS:
        return {'skip': f"only {len(train)} usable rows before {final_date} "
                        f"(need {MIN_TRAIN_ROWS})"}
    if len(test) == 0:
        return {'skip': f"no bars after {final_date}"}
    features = dataset['features']
    reg, cls, threshold = train_models(model_name, train, features)
    prob = cls.predict_proba(test[features])[:, 1] if cls is not None else None
    days = test.copy()
    days['pred'] = reg.predict(test[features])
    days['prob'] = np.nan if prob is None else prob
    reg_m = regression_metrics(days['y'], days['pred'], days['vol_lag1'])
    cls_m = classification_metrics(days['y'], days['prob'], threshold)
    return {'train': train, 'test': days, 'threshold': threshold,
            'reg': reg_m, 'cls': cls_m}


def run_prediction(dataset, model_name):
    """Train on the whole usable history and predict the day after the last
    stored bar. Returns {'skip': reason} or {'vol', 'prob', 'threshold',
    'model_reg', 'n_train', 'first', 'last'}."""
    complete = dataset['complete']
    if len(complete) < MIN_TRAIN_ROWS:
        return {'skip': f"only {len(complete)} usable rows (need {MIN_TRAIN_ROWS})"}
    features = dataset['features']
    reg, cls, threshold = train_models(model_name, complete, features)
    vol, prob = predict_models(reg, cls, dataset['next_row'], features)
    return {'vol': vol, 'prob': prob, 'threshold': threshold,
            'model_reg': reg, 'n_train': len(complete),
            'first': complete.index[0], 'last': complete.index[-1]}


# --------------------------------------------------------------- printing

def print_table(headers, rows, aligns, colors=None, use_color=True):
    """Plain padded cells first, ANSI colors applied after (the escapes
    would break the f-string widths otherwise). colors[i] is a callable
    (cell_text, row) -> colored text or None."""
    widths = [max(len(h), max((len(r[i]) for r in rows), default=0))
              for i, h in enumerate(headers)]
    print('  '.join(f"{h:{aligns[i]}{widths[i]}}" for i, h in enumerate(headers)))
    for row in rows:
        cells = [f"{row[i]:{aligns[i]}{widths[i]}}" for i in range(len(row))]
        if colors:
            for i, fn in enumerate(colors):
                if fn is not None:
                    cell = fn(cells[i], row)
                    if cell is not None:
                        cells[i] = cell
        print('  '.join(cells))


def fmt_vol(v):
    return f"{v:.2f}" if v is not None and np.isfinite(v) else '-'


def fmt_prob(p):
    return f"{p * 100:.1f} %" if p is not None and np.isfinite(p) else '-'


def fmt_metric(x, signed=False, digits=2):
    if x is None or not np.isfinite(x):
        return '-'
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def print_title(title, use_color):
    print(f"\n{colored(title, None, use_color, bold=True)}")


def print_next_day_line(dataset, pred, model_name, use_color, note=''):
    """One compact line: tomorrow's predicted volatility and probability."""
    next_date = pd.Timestamp(dataset['next_date']).date()
    vol_cell = colored(f"{fmt_vol(pred['vol'])} %", None, use_color, bold=True)
    prob_cell = colored(fmt_prob(pred['prob']),
                        prob_color(pred['prob'], use_color), use_color, bold=True)
    print(f"NEXT DAY ({next_date}, after the last bar {dataset['last_bar'].date()}): "
          f"predicted volatility {vol_cell}, probability of a high-volatility "
          f"day {prob_cell}{note}")


def print_prediction_block(dataset, pred, model_name, use_color):
    """The verbose single-asset next-day prediction."""
    print(f"Training data: {pred['first'].date()} .. {pred['last'].date()} "
          f"({pred['n_train']} rows, {len(dataset['features'])} features)")
    print(f"High-volatility threshold (training median): {pred['threshold']:.2f} %")
    print()
    print_next_day_line(dataset, pred, model_name, use_color)
    reg = pred['model_reg']
    if hasattr(reg, 'feature_importances_'):
        importances = sorted(zip(dataset['features'], reg.feature_importances_),
                             key=lambda t: -t[1])[:10]
        print(f"\nTop feature importances ({model_name} regressor):")
        name_w = max(len(name) for name, _ in importances)
        top = max(importances[0][1], 1)
        for name, value in importances:
            print(f"  {name:<{name_w}}  {'#' * int(round(20 * value / top))} {value:g}")
    else:
        print(f"\n(The {model_name} regressor does not expose feature importances)")


def print_backtest_block(dataset, bt, use_color):
    """The split-at-date historical test - the verbose single-asset form."""
    train, test = bt['train'], bt['test']
    print(f"High-volatility threshold: {bt['threshold']:.2f} % (the training median)")
    print(f"TRAIN: {train.index[0].date()} .. {train.index[-1].date()} "
          f"({len(train)} rows, volatility known through "
          f"{train['tdate'].iloc[-1].date()})")
    print(f"TEST:  {test['tdate'].iloc[0].date()} .. {test['tdate'].iloc[-1].date()} "
          f"({len(test)} days, out-of-sample)")
    r, c = bt['reg'], bt['cls']
    print("\nRegression (predicted vs actual percent volatility):")
    print(f"  MAE {r['mae']:.3f}   RMSE {r['rmse']:.3f}   "
          f"naive MAE {r['mae_naive']:.3f}   "
          f"skill {fmt_metric(r['skill'], signed=True)}   "
          f"Pearson {fmt_metric(r['pearson'])}   "
          f"Spearman {fmt_metric(r['spearman'])}")
    print("  (naive = \"tomorrow's volatility = today's\"; skill > 0 beats it)")
    print(f"\nClassification (high = actual volatility > {bt['threshold']:.2f} %):")
    print(f"  accuracy {c['accuracy'] * 100:.1f} %   "
          f"precision {fmt_metric(c['precision'])}   "
          f"recall {fmt_metric(c['recall'])}   AUC {fmt_metric(c['auc'])}   "
          f"high days {c['n_high']}/{c['n']}")

    # a sample of the daily predictions: the first and the last days
    n = len(test)
    if n <= 14:
        idx = list(range(n))
    else:
        idx = list(range(6)) + [None] + list(range(n - 6, n))
    print(f"\nDaily predictions ({n} days, first/last shown):")
    headers = ['DATE', 'ACTUAL %', 'PREDICTED %', 'NAIVE %', 'PROB HIGH', 'PRED', 'ACTUAL']
    aligns = ['<', '>', '>', '>', '>', '>', '>']
    rows = []
    for i in idx:
        if i is None:
            rows.append(('...', '', '', '', '', '', ''))
            continue
        row = test.iloc[i]
        rows.append((
            str(row['tdate'].date()),
            fmt_vol(row['y']),
            fmt_vol(row['pred']),
            fmt_vol(row['vol_lag1']),
            fmt_prob(row['prob']),
            'HIGH' if (np.isfinite(row['prob']) and row['prob'] >= 0.5) else '-',
            'HIGH' if row['y'] > bt['threshold'] else '-',
        ))

    def color_prob(cell, row):
        p = prob_from_cell(row[4])
        if p is not None:
            return colored(cell, prob_color(p, use_color), use_color)
        return None

    def color_high(color):
        def fn(cell, row):
            return colored(cell, color if use_color else None, use_color,
                           bold=(color == RED)) if cell.strip() == 'HIGH' else None
        return fn

    print_table(headers, rows, aligns,
                colors=[None, None, None, None, color_prob,
                        color_high(YELLOW), color_high(RED)])


# --------------------------------------------------------------- driver

def run(args):
    if not Path(args.db).exists():
        sys.exit(f"Database not found: {args.db}")
    check_model_available(args.model)
    use_color = not args.no_color

    conn = open_db_read_only(args.db)
    try:
        assets = load_symbols(conn)
        if args.asset is not None:
            # the official symbol, the exact display name, or an unambiguous
            # part of either
            matches = [(s, n) for s, n in assets if args.asset in (s, n)]
            if not matches:
                low = args.asset.lower()
                matches = [(s, n) for s, n in assets
                           if low in n.lower() or low in s.lower()]
            if not matches:
                hint = ', '.join(n for _, n in assets[:8])
                sys.exit(f"Asset \"{args.asset}\" is not in the database. "
                         f"Stored assets: {hint}"
                         f"{' ...' if len(assets) > 8 else ''}")
            if len(matches) > 1:
                hint = ', '.join(n for _, n in matches[:8])
                sys.exit(f"\"{args.asset}\" matches several assets: {hint} - "
                         f"be more specific")
            assets = matches
        verbose = args.asset is not None

        mode = (f"historical test (trained strictly before {args.final_date}, "
                f"out-of-sample from it on)" if args.final_date else
                "next-day prediction (trained on the full history)")
        print(colored("VOLATILITY PREDICTION", None, use_color, bold=True))
        print(f"Database: {args.db} (read-only)")
        print(f"Model: {args.model} (one per asset, seed {SEED}) | "
              f"assets: {len(assets)} | mode: {mode}\n")

        predictions, backtests, skipped = [], [], []
        for symbol, name in assets:
            df = load_bars(conn, symbol)
            if df is None:
                skipped.append((name, 'no bars stored'))
                continue
            if len(df) < args.min_bars:
                skipped.append((name, f'{len(df)} bars (< {args.min_bars})'))
                continue
            dataset = build_dataset(df)
            if dataset is None:
                skipped.append((name, f'too few usable rows after the '
                                       f'{WARMUP_BARS}-bar feature warm-up'))
                continue
            if args.final_date is not None:
                bt = run_backtest(dataset, args.final_date, args.model)
                if 'skip' in bt:
                    skipped.append((name, bt['skip']))
                else:
                    backtests.append((name, dataset, bt))
            else:
                pred = run_prediction(dataset, args.model)
                if 'skip' in pred:
                    skipped.append((name, pred['skip']))
                else:
                    predictions.append((name, dataset, pred))
    finally:
        conn.close()

    if args.final_date is None:
        # ---- next-day predictions
        if verbose:
            for name, dataset, pred in predictions:
                print_title(name, use_color)
                print_prediction_block(dataset, pred, args.model, use_color)
        elif predictions:
            headers = ['ASSET', 'LAST BAR', 'PREDICTED DAY', 'PRED VOL %',
                        'PROB HIGH', 'THRESHOLD %']
            aligns = ['<', '<', '<', '>', '>', '>']
            rows = []
            for name, dataset, pred in predictions:
                rows.append((name,
                             str(dataset['last_bar'].date()),
                             str(pd.Timestamp(dataset['next_date']).date()),
                             fmt_vol(pred['vol']),
                             fmt_prob(pred['prob']),
                             f"{pred['threshold']:.2f}"))
            rows.sort(key=lambda r: (-(0.0 if r[4] == '-' else float(r[4].split()[0])),
                                     -(0.0 if r[3] == '-' else float(r[3]))))

            def color_prob_row(cell, row):
                p = prob_from_cell(row[4])
                if p is not None:
                    return colored(cell, prob_color(p, use_color), use_color,
                                   bold=True)
                return None

            print(f"Next-day prediction per asset "
                  f"({len(predictions)} predicted, most volatile first):")
            print_table(headers, rows, aligns,
                        colors=[None, None, None, None, color_prob_row, None],
                        use_color=use_color)
    else:
        # ---- historical test results
        if verbose:
            for name, dataset, bt in backtests:
                print_title(name, use_color)
                print_backtest_block(dataset, bt, use_color)
                pred = run_prediction(dataset, args.model)
                if 'skip' not in pred:
                    print()
                    print_next_day_line(dataset, pred, args.model, use_color,
                                        note=' (model retrained on everything '
                                             'through the last bar)')
        elif backtests:
            headers = ['ASSET', 'TRAIN', 'TEST', 'MAE', 'SKILL', 'ACC', 'AUC',
                       'HIGH DAYS']
            aligns = ['<', '>', '>', '>', '>', '>', '>', '>']
            rows = []
            for name, dataset, bt in backtests:
                r, c = bt['reg'], bt['cls']
                rows.append((name, str(len(bt['train'])), str(len(bt['test'])),
                             fmt_metric(r['mae'], digits=3),
                             fmt_metric(r['skill'], signed=True),
                             f"{c['accuracy'] * 100:.0f} %",
                             fmt_metric(c['auc']),
                             f"{c['n_high']}/{c['n']}"))
            rows.sort(key=lambda r: (0.0 if r[4] == '-' else float(r[4])) * -1)

            def color_skill(cell, row):
                if row[4] != '-':
                    v = float(row[4])
                    color = GREEN if v > 0 else (RED if v < 0 else None)
                    return colored(cell, color if use_color else None, use_color,
                                   bold=True)
                return None

            print(f"Historical test per asset (final date {args.final_date}, "
                  f"{len(backtests)} assets):")
            print_table(headers, rows, aligns,
                        colors=[None, None, None, None, color_skill, None, None,
                                None],
                        use_color=use_color)
            print("\n(skill = 1 - MAE/naive MAE; naive predicts \"tomorrow's "
                  "volatility = today's\")")

    if skipped:
        shown = ', '.join(f"{s} ({r})" for s, r in skipped[:10])
        more = f" ... and {len(skipped) - 10} more" if len(skipped) > 10 else ''
        print(f"\nSkipped: {shown}{more}")
    if not predictions and not backtests:
        print("Nothing to report.")


# --------------------------------------------------------------- CLI

def date_arg(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid date {text!r} - expected YYYY-MM-DD")


def build_parser(parser):
    """This tool's flags (the standalone program; pystalker_cli.py could wire
    it in the same way if it ever joins the unified CLI)."""
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT}; "
                             f"only ever read)")
    parser.add_argument('--asset', default=None,
                        help="predict only this asset - its official symbol (e.g. "
                             "ES=F), its personalized display name, or an "
                             "unambiguous part of either; prints the verbose "
                             "single-asset report")
    parser.add_argument('--final-date', type=date_arg, default=None, metavar='YYYY-MM-DD',
                        help="historical test: train only with data strictly before "
                             "this date, then predict every following bar "
                             "out-of-sample and compare with the actual volatility")
    parser.add_argument('--model', choices=sorted(MODEL_FACTORIES), default='lightgbm',
                        help="the ML algorithm to swap in (default: lightgbm; "
                             "sklearn = scikit-learn histogram gradient boosting)")
    parser.add_argument('--min-bars', type=int, default=MIN_BARS_DEFAULT,
                        help=f"skip assets with fewer stored bars "
                             f"(default: {MIN_BARS_DEFAULT} - the feature warm-up "
                             f"alone needs {WARMUP_BARS})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Predict the next day's percent volatility per asset with a "
                    "pluggable ML algorithm (LightGBM by default), or run the "
                    "split-at-date historical test (--final-date). Standalone "
                    "machine-learning experiment - reads the database read-only.")
    build_parser(parser)
    run(parser.parse_args(argv))
    return 0


if __name__ == '__main__':
    sys.exit(main())