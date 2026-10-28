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

RECENCY WEIGHTING (--half-life YEARS, default 0 = uniform): volatility
drifts along with prices and inflation, so each training day's weight can
HALVE every YEARS of age - the last times teach the model the most while
ALL the historical data keeps training it, the old times just fading.
Measured on the live database, uniform weights predicted slightly better
on both out-of-sample windows tried, so uniform is the default and the
weighting is opt-in; the accuracy walks accept the same flag and record
the configuration used, so their stored MATCH % / DAY MATCH % always
measure exactly this configured predictor.

Modes:
  - default: predicts the day after the last stored bar of every asset AND
    records every prediction in the predictions journal (below), so its
    result can be checked over the following week; --no-store skips the
    recording. The listing's LAST FIELDS read the stored history: MATCH %
    is the historical weekly accuracy, AVG DAY % the average realized daily
    volatility and DAY MATCH % the day-call accuracy - all computed by the
    batch companion volatility_accuracy.py (below).
  - --asset SYMBOL: only that asset, with a verbose single-asset report
    (training range, feature importances, journal so far) - the official
    symbol, its personalized display name, or an unambiguous part of either
  - --final-date YYYY-MM-DD: HISTORICAL TEST - train ONLY with data
    strictly before that date, then predict every bar from it on,
    out-of-sample, comparing predicted vs actual volatility (regression
    metrics: MAE, RMSE, skill vs the naive "tomorrow = today" predictor,
    correlation; classification metrics: accuracy, precision, recall,
    ROC AUC; plus a sample of the daily predictions). Backtest runs are
    never stored - only true forward predictions enter the journal.
  - --weekly: the weekly percentage of the assets - Friday closes: each
    week's last close vs the previous week's (the classic market week).
    With --asset the full history of that asset; otherwise recent stats
    (last week, 4-week and 12-week and all-time averages) per asset.
    Nothing is stored: the series derives from the bars in milliseconds.
  - --results: the predictions journal checked against its outcomes - each
    stored prediction vs the signed weekly percentage of its predicted
    day's week, with the per-asset averages (the "average prediction to
    result" table). Nothing is stored.

The predictions journal is the ONLY thing this script ever writes: one new
table, volatility_predictions, appended by default-mode runs - one row per
(asset, predicted day); re-running the same day updates it. Every recorded
prediction is a TRUE FORWARD TEST: it was made before its outcome existed,
unlike any backtest. The outcomes are always computed from the current
bars at display time and never stored (so they can never go stale when
bars are cleaned or updated): the result of a prediction is the signed
weekly percentage of its predicted day's Friday-close weekly bar - the
last Friday close at or before the predicted day to the first Friday close
after it (for the usual runs, after the Friday close, that is exactly the
week following the prediction). A prediction stays PENDING until that
second Friday close exists.

The MATCH % field is a different animal: it comes from volatility_accuracy.py,
the batch companion that walks EVERY week of the stored history, makes the
prediction as of each week's end using only data known by then (models
retrained yearly), and counts the weeks whose high/low call matched the
real outcome - "10 weeks, 5 right = 50% success". The per-asset result is
stored in the volatility_accuracy table and read here; re-run the batch to
refresh it.

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
  python console_programs/volatility_prediction.py --weekly
  python console_programs/volatility_prediction.py --weekly --asset '005930.KS (Samsung)'
  python console_programs/volatility_prediction.py --results
  python console_programs/volatility_accuracy.py --asset ES=F    (the MATCH % batch)
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


def resolve_asset(assets, pattern):
    """The single (symbol, display name) behind an --asset pattern: the
    official symbol, the exact display name, or an unambiguous part of
    either. Exits with a clean error when nothing or several match - the
    predictor and the accuracy walker share this so they never drift."""
    matches = [(s, n) for s, n in assets if pattern in (s, n)]
    if not matches:
        low = pattern.lower()
        matches = [(s, n) for s, n in assets
                   if low in n.lower() or low in s.lower()]
    if not matches:
        hint = ', '.join(n for _, n in assets[:8])
        sys.exit(f"Asset \"{pattern}\" is not in the database. "
                 f"Stored assets: {hint}"
                 f"{' ...' if len(assets) > 8 else ''}")
    if len(matches) > 1:
        hint = ', '.join(n for _, n in matches[:8])
        sys.exit(f"\"{pattern}\" matches several assets: {hint} - "
                 f"be more specific")
    return matches[0]


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
    df['ts'] = pd.to_numeric(df['ts'], errors='coerce')
    df = df.dropna(subset=['ts'])
    # render the timestamps exactly like the application does (the system's
    # local time WITH its DST rules - a fixed offset would fold two source
    # stamps onto the same local day around DST transitions), normalized to
    # the calendar day; some sources stamp their daily bars at different UTC
    # hours, so ONE BAR PER DAY is kept - the last stamp of the day wins
    df['Date'] = pd.to_datetime(
        [datetime.datetime.fromtimestamp(int(t)) for t in df['ts']]).normalize()
    df = df.sort_values('ts')
    df = df.drop_duplicates(subset='Date', keep='last')
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

# The recency weighting (--half-life YEARS): each training day's weight
# halves every YEARS of age, so recent times teach the model the most while
# ALL the history keeps training it. Default 0 = uniform weights - measured
# on the live database, uniform predicted slightly better on both
# out-of-sample windows tried, so the weighting is opt-in.
HALF_LIFE_DEFAULT = 0.0

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


def time_decay_weights(index, half_life_years):
    """The recency weights of one training frame: each day's weight halves
    every half_life_years of age, the age measured in calendar days from
    the frame's LAST day (the training moment's 'now' - in the accuracy
    walks every retrain therefore emphasizes its own recent past). None
    when the weighting is disabled."""
    if not half_life_years:
        return None
    age_days = (index[-1] - index) / pd.Timedelta(days=1)   # positive with age
    return np.power(0.5, np.asarray(age_days) / (365.25 * half_life_years))


def train_models(name, train_rows, features, half_life=None):
    """Fit the per-asset pair: the volatility regressor and the high-volatility
    classifier (its threshold = the training data's median volatility).
    half_life (years) applies the recency weighting to BOTH models through
    sample weights. Returns (regressor, classifier-or-None, threshold)."""
    X = train_rows[features]
    y = train_rows['y']
    threshold = float(np.median(y.to_numpy()))
    weights = time_decay_weights(train_rows.index, half_life)
    reg = MODEL_FACTORIES[name]['regressor']()
    reg.fit(X, y, sample_weight=weights)
    labels = (y.to_numpy() > threshold).astype(int)
    cls = None
    if np.unique(labels).size == 2:            # a constant label trains nothing
        cls = MODEL_FACTORIES[name]['classifier']()
        cls.fit(X, labels, sample_weight=weights)
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
    # balanced accuracy needs BOTH classes in the window: when the test days
    # are all quiet (no high day) or all wild (no quiet day), one of the two
    # sides is undefined and so is their average
    out['balanced'] = ((out['recall'] + spec) / 2
                       if spec is not None and out['recall'] is not None else None)
    out['auc'] = rank_auc(y_true, np.asarray(prob, float))
    return out


# ------------------------------------------------- weekly percentages (Friday closes)

def weekly_closes(df):
    """(friday_dates, closes, last_bar_dates): each CLOSED week's last close,
    labeled by its Friday - W-FRI buckets, the classic market week. A market
    closed on Friday uses the previous trading day's close; a 24/7 market's
    weekend bars belong to the bucket ending on the following Friday. A
    trailing week whose Friday lies beyond the last stored bar is still
    OPEN and is left out, so no phantom 'week' can be built from weekend
    bars that predate the prediction."""
    weeks = pd.DataFrame({
        'close': df['Close'].resample('W-FRI').last(),
        'last': df.index.to_series().resample('W-FRI').last(),
    }).dropna()
    weeks = weeks[weeks.index <= df.index[-1]]      # only weeks already closed
    return weeks.index, weeks['close'].to_numpy(), pd.DatetimeIndex(weeks['last'])


def weekly_history(df):
    """(friday_dates, closes, weekly_pct): the full-history weekly percentage
    series - each closed week's last close vs the previous week's, signed."""
    fridays, closes, _ = weekly_closes(df)
    if len(closes) < 2:
        return fridays, closes, np.array([])
    pct = (closes[1:] / closes[:-1] - 1.0) * 100.0
    return fridays, closes, pct


def weekly_result_for(fridays, closes, last_dates, day):
    """The signed weekly percentage behind a prediction for `day`: the move
    from the last Friday close at or before `day` to the first Friday close
    after it - the Friday-to-Friday weekly bar the predicted day falls in
    (for the usual runs, after the Friday close, that is exactly the week
    following the prediction). None while that week is still open: the
    Friday must have closed in the data AND the week's close must not
    predate the predicted day, so the prediction stays pending until then."""
    day = pd.Timestamp(day)
    prev = np.asarray(fridays <= day)
    if not prev.any():
        return None
    nxt = np.asarray(fridays > day)
    if not nxt.any():
        return None
    j = int(np.argmax(nxt))
    if last_dates[j] < day:
        return None                    # the week's close predates the prediction
    i = int(np.nonzero(prev)[0][-1])
    return float((closes[j] / closes[i] - 1.0) * 100.0)


# ------------------------------------------------- predictions journal

def load_journal(conn):
    """The stored predictions per symbol (the journal), oldest first. Empty
    when the table does not exist yet."""
    try:
        rows = conn.execute(
            'SELECT symbol, predicted_date, predicted_vol, prob_high, '
            'threshold, model, made_at FROM volatility_predictions '
            'ORDER BY symbol, predicted_date').fetchall()
    except sqlite3.OperationalError:
        return {}
    journal = {}
    for symbol, date, vol, prob, thr, model, made_at in rows:
        journal.setdefault(symbol, []).append(
            {'predicted_date': date, 'vol': vol, 'prob': prob,
             'threshold': thr, 'model': model, 'made_at': made_at})
    return journal


def load_accuracy(conn):
    """The stored weekly-accuracy results (from the volatility_accuracy
    batch program): {symbol: {'weeks', 'right', 'match_pct',
    'computed_at'}}. Empty when the table does not exist yet."""
    try:
        rows = conn.execute(
            'SELECT symbol, weeks, right_weeks, match_pct, computed_at '
            'FROM volatility_accuracy').fetchall()
    except sqlite3.OperationalError:
        return {}
    return {sym: {'weeks': w, 'right': r, 'match_pct': p, 'computed_at': c}
            for sym, w, r, p, c in rows}


def load_daily(conn):
    """The stored DAILY walk summaries (from the volatility_accuracy batch
    program, --daily): {symbol: {'days', 'avg_pred', 'avg_real', 'mae',
    'skill', 'match_pct', 'computed_at'}}. Empty when the table does not
    exist yet."""
    try:
        rows = conn.execute(
            'SELECT symbol, days, avg_pred, avg_real, mae, skill, match_pct, '
            'computed_at FROM volatility_daily').fetchall()
    except sqlite3.OperationalError:
        return {}
    return {sym: {'days': d, 'avg_pred': ap, 'avg_real': ar, 'mae': m,
                  'skill': s, 'match_pct': mp, 'computed_at': c}
            for sym, d, ap, ar, m, s, mp, c in rows}


def verify_journal(df, rows):
    """Check one asset's stored predictions against their outcomes: each is
    verified with the signed weekly percentage of its predicted day's
    Friday-close weekly bar; a prediction whose week is still incomplete
    stays pending. Returns {'weeks': aligned result or None per row,
    'n_verified', 'n_pending', 'avg_week', 'avg_pred_vol'} - the averages
    pair each stored prediction with the week it produced, so they compare
    like with like."""
    fridays, closes, last_dates = weekly_closes(df)
    weeks = [weekly_result_for(fridays, closes, last_dates, r['predicted_date'])
             for r in rows]
    verified = [w for w in weeks if w is not None]
    pred_vols = [r['vol'] for r, w in zip(rows, weeks)
                 if w is not None and r['vol'] is not None]
    return {'weeks': weeks, 'n_verified': len(verified),
            'n_pending': len(weeks) - len(verified),
            'avg_week': float(np.mean(verified)) if verified else None,
            'avg_pred_vol': float(np.mean(pred_vols)) if pred_vols else None}


def _ensure_column(conn, table, column, decl):
    """SQLite has no ADD COLUMN IF NOT EXISTS: add it only when missing
    (the rows stored before the column existed keep NULL - their config
    was the unweighted one)."""
    cols = [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {decl}')


def store_predictions(db_path, new_rows, model, half_life=None):
    """Append/update the journal - the ONLY write this script ever does:
    one new table, volatility_predictions, one row per (asset, predicted
    day); re-running the same day updates it (INSERT OR REPLACE), never
    duplicating. Returns the number of rows stored."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS volatility_predictions ('
            'symbol TEXT NOT NULL, '
            'predicted_date TEXT NOT NULL, '
            'made_at TEXT NOT NULL, '
            'predicted_vol REAL, '
            'prob_high REAL, '
            'threshold REAL, '
            'model TEXT NOT NULL, '
            'half_life REAL, '
            'PRIMARY KEY (symbol, predicted_date))')
        _ensure_column(conn, 'volatility_predictions', 'half_life', 'REAL')
        made_at = datetime.datetime.now().isoformat(timespec='seconds')
        conn.executemany(
            'INSERT OR REPLACE INTO volatility_predictions '
            '(symbol, predicted_date, made_at, predicted_vol, prob_high, '
            'threshold, model, half_life) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            [(symbol, date, made_at, vol, prob, thr, model, half_life)
             for symbol, date, vol, prob, thr in new_rows])
        conn.commit()
        return len(new_rows)
    finally:
        conn.close()


# --------------------------------------------------------------- backtest / prediction

def run_backtest(dataset, final_date, model_name, half_life=None):
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
    reg, cls, threshold = train_models(model_name, train, features, half_life)
    prob = cls.predict_proba(test[features])[:, 1] if cls is not None else None
    days = test.copy()
    days['pred'] = reg.predict(test[features])
    days['prob'] = np.nan if prob is None else prob
    reg_m = regression_metrics(days['y'], days['pred'], days['vol_lag1'])
    cls_m = classification_metrics(days['y'], days['prob'], threshold)
    return {'train': train, 'test': days, 'threshold': threshold,
            'reg': reg_m, 'cls': cls_m}


def run_prediction(dataset, model_name, half_life=None):
    """Train on the whole usable history and predict the day after the last
    stored bar. Returns {'skip': reason} or {'vol', 'prob', 'threshold',
    'model_reg', 'n_train', 'first', 'last'}."""
    complete = dataset['complete']
    if len(complete) < MIN_TRAIN_ROWS:
        return {'skip': f"only {len(complete)} usable rows (need {MIN_TRAIN_ROWS})"}
    features = dataset['features']
    reg, cls, threshold = train_models(model_name, complete, features, half_life)
    vol, prob = predict_models(reg, cls, dataset['next_row'], features)
    return {'vol': vol, 'prob': prob, 'threshold': threshold,
            'model_reg': reg, 'n_train': len(complete),
            'first': complete.index[0], 'last': complete.index[-1]}


# --------------------------------------------------------------- printing

def match_color(value, enabled):
    """green = the historical weekly accuracy clearly above a coin flip,
    red = clearly below."""
    if value is None:
        return None
    if value >= 0.55:
        return GREEN if enabled else None
    if value <= 0.45:
        return RED if enabled else None
    return None


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


def fmt_signed_pct(x, digits=2):
    return f"{x:+.{digits}f}" if x is not None and np.isfinite(x) else '-'


def signed_from_cell(text):
    """The signed value behind a formatted '+1.05' / '-0.32' cell, or None
    ('-', empty, the '...' separator...)."""
    text = text.strip()
    if not text or set(text) == {'.'}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def sign_color(value, enabled):
    """green = a positive move, red = a negative one."""
    if value is None or not np.isfinite(value):
        return None
    if value > 0:
        return GREEN if enabled else None
    if value < 0:
        return RED if enabled else None
    return None


def week_cell_color(use_color):
    """The color callback for a signed weekly-percentage cell."""
    def fn(cell, row):
        value = signed_from_cell(cell)
        if value is not None:
            return colored(cell, sign_color(value, use_color), use_color, bold=True)
        return None
    return fn


def print_weekly_block(df, use_color):
    """--weekly --asset: the full-history weekly percentage listing."""
    fridays, closes, pct = weekly_history(df)
    print(f"Weekly percentage - Friday closes ({len(fridays)} weeks)")
    if len(closes) < 2:
        print("  not enough data for a single weekly bar")
        return
    rows = [(str(fridays[0].date()), fmt_vol(float(closes[0])), '-')]
    for f, c, p in zip(fridays[1:], closes[1:], pct):
        rows.append((str(f.date()), fmt_vol(float(c)), fmt_signed_pct(float(p))))
    color = week_cell_color(use_color)
    print_table(['WEEK ENDING', 'CLOSE', 'WEEK %'], rows, ['<', '>', '>'],
                colors=[None, None, color], use_color=use_color)
    print(f"all-time average weekly move: "
          f"{colored(fmt_signed_pct(float(np.mean(pct))) + ' %', sign_color(float(np.mean(pct)), use_color), use_color)}")


def print_results_block(rows, v, use_color):
    """--results --asset: the journal listing with each prediction's outcome."""
    headers = ['PREDICTED FOR', 'PRED VOL %', 'PROB HIGH', 'WEEK %', 'STATUS']
    aligns = ['<', '>', '>', '>', '<']
    table = [(r['predicted_date'], fmt_vol(r['vol']), fmt_prob(r['prob']),
              fmt_signed_pct(w), 'verified' if w is not None else 'pending')
             for r, w in zip(rows, v['weeks'])]
    color = week_cell_color(use_color)
    print(f"Stored predictions: {len(rows)} "
          f"({v['n_verified']} verified, {v['n_pending']} pending)")
    print_table(headers, table, aligns,
                colors=[None, None, None, color, None], use_color=use_color)
    if v['avg_week'] is not None:
        print(f"\naverage predicted volatility (verified rows): "
              f"{fmt_vol(v['avg_pred_vol'])} %   average weekly result: "
              f"{colored(fmt_signed_pct(v['avg_week']) + ' %',
                         sign_color(v['avg_week'], use_color), use_color, bold=True)}")
    else:
        print("\nno verified prediction yet - the weeks are still incomplete")


def print_journal_block(jrows, v, use_color):
    """The compact journal summary of the verbose single-asset default mode."""
    print(f"\nJournal so far: {len(jrows)} stored prediction(s), "
          f"{v['n_verified']} verified, {v['n_pending']} pending"
          + (f", average weekly result "
             f"{colored(fmt_signed_pct(v['avg_week']) + ' %',
                        sign_color(v['avg_week'], use_color), use_color, bold=True)}"
             if v['avg_week'] is not None else ""))


def print_accuracy_line(acc, use_color):
    """The stored historical weekly accuracy (the volatility_accuracy batch
    program) - the same number the listing shows as MATCH %."""
    color = match_color(acc['match_pct'], use_color)
    print(f"\nHistorical weekly accuracy: "
          f"{colored(fmt_prob(acc['match_pct']), color, use_color, bold=True)} "
          f"({acc['right']}/{acc['weeks']} weeks right, yearly walk, "
          f"computed {acc['computed_at']})")


def print_daily_line(d, use_color):
    """The stored DAILY walk summary (the same batch program, --daily) - the
    numbers the listing shows as AVG DAY % and DAY MATCH %."""
    skill = fmt_metric(d['skill'], signed=True)
    match = colored(fmt_prob(d['match_pct']), match_color(d['match_pct'], use_color),
                    use_color, bold=True)
    print(f"Daily walk: average day volatility {fmt_vol(d['avg_real'])} % "
          f"(the model's average prediction {fmt_vol(d['avg_pred'])} %) over "
          f"{d['days']} days, MAE {d['mae']:.3f} (skill {skill}), day match "
          f"{match} (computed {d['computed_at']})")


def run_weekly(conn, assets, args, use_color):
    """--weekly: the weekly percentage of the assets (Friday closes).
    Nothing is stored - the series derives from the bars."""
    verbose = args.asset is not None
    rows, n_small = [], 0
    for symbol, name in assets:
        df = load_bars(conn, symbol)
        if df is None or len(df) < 2:
            n_small += 1
            continue
        if verbose:
            print_title(name, use_color)
            print_weekly_block(df, use_color)
            continue
        _, _, pct = weekly_history(df)
        if len(pct) < 1:
            n_small += 1
            continue
        rows.append((name,
                     fmt_signed_pct(float(pct[-1])),
                     fmt_signed_pct(float(np.mean(pct[-4:]))),
                     fmt_signed_pct(float(np.mean(pct[-12:]))),
                     fmt_signed_pct(float(np.mean(pct))),
                     str(len(pct))))
    if verbose:
        return
    if rows:
        rows.sort(key=lambda r: signed_from_cell(r[1]) or 0.0, reverse=True)
        color = week_cell_color(use_color)
        print(f"Weekly percentage per asset (Friday closes, {len(rows)} assets):")
        print_table(['ASSET', 'LAST WEEK %', 'AVG 4W %', 'AVG 12W %',
                     'ALL-TIME %', 'WEEKS'],
                    rows, ['<', '>', '>', '>', '>', '>'],
                    colors=[None, color, color, color, color, None],
                    use_color=use_color)
        print("\n(AVG NW = the mean of the last N weekly closes, fewer when "
              "the history is younger)")
    if n_small:
        print(f"\nSkipped: {n_small} asset(s) without two weekly closes")
    if not rows:
        print("Nothing to report.")


def run_results(conn, assets, args, use_color):
    """--results: the predictions journal checked against its outcomes.
    Nothing is stored - the outcomes derive from the bars."""
    verbose = args.asset is not None
    journal = load_journal(conn)
    if not journal:
        print("The predictions journal is empty - run the default mode (each "
              "run records one prediction per asset in "
              "volatility_predictions) and check back once the following "
              "weeks have passed.")
        return
    names = dict(assets)

    def all_pending(rows):
        return {'weeks': [None] * len(rows), 'n_verified': 0,
                'n_pending': len(rows), 'avg_week': None, 'avg_pred_vol': None}

    if verbose:
        symbol, name = assets[0]
        rows = journal.get(symbol)
        if not rows:
            print(f"No stored prediction for {name} yet - run the default "
                  "mode first.")
            return
        df = load_bars(conn, symbol)
        v = verify_journal(df, rows) if df is not None else all_pending(rows)
        print_title(name, use_color)
        print_results_block(rows, v, use_color)
        return
    summaries = []
    for symbol in sorted(journal):
        rows = journal[symbol]
        df = load_bars(conn, symbol)
        v = verify_journal(df, rows) if df is not None else all_pending(rows)
        summaries.append((names.get(symbol, symbol), len(rows), v))
    table = [(name, str(n), str(v['n_verified']), str(v['n_pending']),
              fmt_vol(v['avg_pred_vol']), fmt_signed_pct(v['avg_week']))
             for name, n, v in summaries]
    table.sort(key=lambda r: abs(signed_from_cell(r[5]) or 0.0), reverse=True)
    n_total = sum(n for _, n, _ in summaries)
    n_ver = sum(v['n_verified'] for _, _, v in summaries)
    print(f"Predictions journal vs outcomes ({len(summaries)} assets, "
          f"{n_total} stored, {n_ver} verified):")
    print_table(['ASSET', 'PREDICTIONS', 'VERIFIED', 'PENDING',
                 'AVG PRED VOL %', 'AVG WEEK %'],
                table, ['<', '>', '>', '>', '>', '>'],
                colors=[None, None, None, None, None, week_cell_color(use_color)],
                use_color=use_color)
    print("\n(the result of a prediction = the signed weekly percentage of "
          "its predicted day's Friday-close week; it stays pending until "
          "that Friday close exists)")


# --------------------------------------------------------------- driver

def run(args):
    if not Path(args.db).exists():
        sys.exit(f"Database not found: {args.db}")
    use_color = not args.no_color
    training_mode = not args.weekly and not args.results
    if training_mode:
        check_model_available(args.model)

    conn = open_db_read_only(args.db)
    try:
        assets = load_symbols(conn)
        if args.asset is not None:
            assets = [resolve_asset(assets, args.asset)]
        verbose = args.asset is not None

        if args.weekly:
            mode = "weekly percentages (Friday closes)"
        elif args.results:
            mode = "predictions journal vs outcomes"
        elif args.final_date:
            mode = (f"historical test (trained strictly before {args.final_date}, "
                    f"out-of-sample from it on)")
        else:
            mode = "next-day prediction (trained on the full history)"
        print(colored("VOLATILITY PREDICTION", None, use_color, bold=True))
        print(f"Database: {args.db} (read-only)")
        info = f"assets: {len(assets)} | mode: {mode}"
        if training_mode:
            recency = (f"half-life {args.half_life:g} y"
                       if args.half_life else "uniform weights")
            info = f"Model: {args.model} (one per asset, seed {SEED}, {recency}) | {info}"
        print(info + "\n")

        if args.weekly:
            run_weekly(conn, assets, args, use_color)
            return
        if args.results:
            run_results(conn, assets, args, use_color)
            return

        # the journal of past predictions: the default mode verifies them
        # against the following weeks; backtests never touch it
        journal = load_journal(conn) if args.final_date is None else {}
        # the stored historical weekly accuracy (the volatility_accuracy
        # batch program): the last field of the listing
        accuracy = load_accuracy(conn) if args.final_date is None else {}
        # the stored daily walk summaries (the same batch program, --daily):
        # the average realized daily volatility and the day-call accuracy
        daily = load_daily(conn) if args.final_date is None else {}
        predictions, backtests, skipped, to_store = [], [], [], []
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
            dataset['symbol'] = symbol
            if args.final_date is not None:
                bt = run_backtest(dataset, args.final_date, args.model,
                                  args.half_life)
                if 'skip' in bt:
                    skipped.append((name, bt['skip']))
                else:
                    backtests.append((name, dataset, bt))
            else:
                pred = run_prediction(dataset, args.model, args.half_life)
                if 'skip' in pred:
                    skipped.append((name, pred['skip']))
                else:
                    jrows = journal.get(symbol)
                    jview = verify_journal(df, jrows) if jrows else None
                    predictions.append((name, dataset, pred, jrows, jview))
                    to_store.append((symbol,
                                     str(pd.Timestamp(dataset['next_date']).date()),
                                     pred['vol'], pred['prob'],
                                     pred['threshold']))
        # record this run's predictions in the journal - the only write the
        # script ever does (default mode only; backtests never enter it)
        if to_store and not args.no_store:
            try:
                n = store_predictions(args.db, to_store, args.model,
                                      args.half_life)
                print(f"Journal: {n} prediction(s) stored in "
                      "volatility_predictions (one row per asset per day; "
                      "re-running updates it)\n")
            except sqlite3.Error as e:
                print(f"WARNING: predictions not stored ({e})\n")
    finally:
        conn.close()

    if args.final_date is None:
        # ---- next-day predictions (default mode)
        if verbose:
            for name, dataset, pred, jrows, jview in predictions:
                print_title(name, use_color)
                print_prediction_block(dataset, pred, args.model, use_color)
                if jview is not None:
                    print_journal_block(jrows, jview, use_color)
                acc = accuracy.get(dataset['symbol'])
                if acc is not None:
                    print_accuracy_line(acc, use_color)
                day = daily.get(dataset['symbol'])
                if day is not None:
                    print_daily_line(day, use_color)
        elif predictions:
            headers = ['ASSET', 'LAST BAR', 'PREDICTED DAY', 'PRED VOL %',
                        'PROB HIGH', 'THRESHOLD %', 'VERIFIED', 'AVG WEEK %',
                        'MATCH %', 'AVG DAY %', 'DAY MATCH %']
            aligns = ['<', '<', '<', '>', '>', '>', '>', '>', '>', '>', '>']
            rows = []
            for name, dataset, pred, jrows, jview in predictions:
                symbol = dataset['symbol']
                acc = accuracy.get(symbol)
                day = daily.get(symbol)
                rows.append((name,
                             str(dataset['last_bar'].date()),
                             str(pd.Timestamp(dataset['next_date']).date()),
                             fmt_vol(pred['vol']),
                             fmt_prob(pred['prob']),
                             f"{pred['threshold']:.2f}",
                             f"{jview['n_verified']}/{len(jrows)}" if jview else '-',
                             fmt_signed_pct(jview['avg_week']) if jview else '-',
                             fmt_prob(acc['match_pct']) if acc else '-',
                             fmt_vol(day['avg_real']) if day else '-',
                             fmt_prob(day['match_pct']) if day else '-'))
            rows.sort(key=lambda r: (-(0.0 if r[4] == '-' else float(r[4].split()[0])),
                                     -(0.0 if r[3] == '-' else float(r[3]))))

            def color_prob_row(cell, row):
                p = prob_from_cell(row[4])
                if p is not None:
                    return colored(cell, prob_color(p, use_color), use_color,
                                   bold=True)
                return None

            def color_match_row(cell, row):
                p = prob_from_cell(cell)
                if p is not None:
                    return colored(cell, match_color(p, use_color), use_color,
                                   bold=True)
                return None

            print(f"Next-day prediction per asset "
                  f"({len(predictions)} predicted, most volatile first):")
            print_table(headers, rows, aligns,
                        colors=[None, None, None, None, color_prob_row, None,
                                None, week_cell_color(use_color), color_match_row,
                                None, color_match_row],
                        use_color=use_color)
            print("\n(VERIFIED = journal predictions whose following week is "
                  "complete, AVG WEEK % = their average signed weekly move - "
                  "full detail with --results; MATCH % = the historical "
                  "weekly accuracy stored by volatility_accuracy.py; AVG DAY "
                  "% = the average realized daily volatility and DAY MATCH % "
                  "= the day-call accuracy of its --daily walk)")
    else:
        # ---- historical test results
        if verbose:
            for name, dataset, bt in backtests:
                print_title(name, use_color)
                print_backtest_block(dataset, bt, use_color)
                pred = run_prediction(dataset, args.model, args.half_life)
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


def half_life_arg(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid half-life {text!r} - a number "
                                         f"of years expected (e.g. 1, 2, 0.5)")
    if value < 0:
        raise argparse.ArgumentTypeError("the half-life cannot be negative")
    return value


def build_parser(parser):
    """This tool's flags (the standalone program; pystalker_cli.py could wire
    it in the same way if it ever joins the unified CLI)."""
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT}); only "
                             f"ever read, except the journal appends of the "
                             f"default mode (the volatility_predictions table)")
    parser.add_argument('--asset', default=None,
                        help="predict only this asset - its official symbol (e.g. "
                             "ES=F), its personalized display name, or an "
                             "unambiguous part of either; prints the verbose "
                             "single-asset report")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--final-date', type=date_arg, default=None, metavar='YYYY-MM-DD',
                       help="historical test: train only with data strictly before "
                            "this date, then predict every following bar "
                            "out-of-sample and compare with the actual volatility "
                            "(never stored in the journal)")
    group.add_argument('--weekly', action='store_true',
                       help="list the weekly percentage of the assets - Friday "
                            "closes, each week's last close vs the previous "
                            "week's; all history with --asset, recent stats per "
                            "asset otherwise; nothing is stored")
    group.add_argument('--results', action='store_true',
                       help="the predictions journal checked against its outcomes: "
                            "each stored prediction vs the signed weekly "
                            "percentage of its predicted day's week, with the "
                            "per-asset averages; nothing is stored")
    parser.add_argument('--no-store', action='store_true',
                        help="do not record this run's predictions in the journal "
                             "(the default mode stores one row per asset per day "
                             "in volatility_predictions)")
    parser.add_argument('--model', choices=sorted(MODEL_FACTORIES), default='lightgbm',
                        help="the ML algorithm to swap in (default: lightgbm; "
                             "sklearn = scikit-learn histogram gradient boosting)")
    parser.add_argument('--half-life', type=half_life_arg,
                        default=HALF_LIFE_DEFAULT, metavar='YEARS',
                        help=f"recency weighting: each training day's weight "
                             f"halves every this many years of age, so the last "
                             f"times matter more than the older ones while ALL "
                             f"the history keeps training the model "
                             f"(default: {HALF_LIFE_DEFAULT:g} = uniform weights; "
                             f"e.g. 1 for a one-year half-life)")
    parser.add_argument('--min-bars', type=int, default=MIN_BARS_DEFAULT,
                        help=f"skip assets with fewer stored bars "
                             f"(default: {MIN_BARS_DEFAULT} - the feature warm-up "
                             f"alone needs {WARMUP_BARS})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Predict the next day's percent volatility per asset with a "
                    "pluggable ML algorithm (LightGBM by default), recording every "
                    "prediction in a journal to check its result over the following "
                    "week (--results), list the weekly percentages (--weekly), or "
                    "run the split-at-date historical test (--final-date). "
                    "Standalone machine-learning experiment - the database is only "
                    "read, except the journal appends of the default mode.")
    build_parser(parser)
    run(parser.parse_args(argv))
    return 0


if __name__ == '__main__':
    sys.exit(main())