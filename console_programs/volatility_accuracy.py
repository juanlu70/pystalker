#!/usr/bin/env python3
"""
volatility_accuracy.py - Historical weekly accuracy of the volatility predictor

The batch companion of volatility_prediction.py: it walks EVERY week of an
asset's stored history and, at each week's end (the last bar of the week -
the classic Friday close), makes the SAME prediction the daily tool makes,
using ONLY data available at that moment, then checks it against what the
FOLLOWING week really did. Each week is a hit or a miss, and the final
per-asset result is a MATCH PERCENTAGE - "10 weeks, 5 right = 50% success".

The check per week (as agreed with the user):
  - prediction: the model's high-volatility probability at the week's last
    bar - >= 50% calls the following week a HIGH-volatility week
  - reality: the following week's average daily |close-to-close move| %
    above the model's training median (the predictor's own "high"
    definition, extended to a week)
  - MATCH when the call and the reality agree (high/high or low/low)

No future ever leaks into a model: models are retrained YEARLY (per the
user's choice), each new year on everything known by its first week's end,
and every week of that year is predicted with that model - an
expanding-window walk-forward. The walk needs training history, so the
first evaluated week of an asset is the first one with enough usable rows
(the predictor's own minimum); before that there is nothing to predict with.
Every training applies the RECENCY WEIGHTING shared with the predictor
(--half-life YEARS, default uniform: each day's weight halves every YEARS
of age, anchored at the training moment) so the stored accuracy measures
exactly the configured predictor.

The per-asset summary is STORED in the database (the volatility_accuracy
table - one row per asset, INSERT OR REPLACE): weeks walked, weeks right,
the match fraction, the model and the timestamp. The WEEK-BY-WEEK detail is
stored too (the volatility_accuracy_weeks table: one row per evaluated week
- the outcome week, the call's probability, the call, the real outcome, the
hit), wholesale-refreshed per asset so it always mirrors the current bars.
Browse it with --weeks: every stored week of one asset with --asset, or of
all assets at once (a full report meant for redirecting to a file).
volatility_prediction.py shows the summary as the LAST FIELD of its listing
(MATCH %). --dry-run walks without storing anything.

The DAILY mirror (--daily): the same walk-forward at day granularity - every
day of the history predicts the NEXT day (same yearly retraining, same
no-leakage cutoffs) and is checked against what really happened. The
per-day rows (predicted volatility, probability, the realized volatility,
the high/low call and hit) are stored in volatility_accuracy_days, the
per-asset summary (average predicted vs average REALIZED daily volatility,
MAE, skill vs the naive "tomorrow = today", the day-call match fraction)
in volatility_daily - volatility_prediction.py shows the average realized
daily volatility (AVG DAY %) and the day-call accuracy (DAY MATCH %) as
its new last fields. Browse the stored days with --days.

Usage:
  python console_programs/volatility_accuracy.py                    (weekly walk, all assets)
  python console_programs/volatility_accuracy.py --daily            (daily walk, all assets)
  python console_programs/volatility_accuracy.py --daily --asset ES=F (one asset, verbose)
  python console_programs/volatility_accuracy.py --weeks --asset ES=F  (the stored weeks)
  python console_programs/volatility_accuracy.py --days --asset ES=F   (the stored days)
  python console_programs/volatility_accuracy.py --weeks > report.txt   (all weeks, all assets)
  python console_programs/volatility_accuracy.py --dry-run --no-color
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import volatility_prediction as vp


# --------------------------------------------------------------- the walk

def week_grid(df):
    """The closed weeks of an asset: (friday label, last bar date, the
    week's mean |close-to-close move| %) - one row per week already closed
    in the data (an open trailing week is left out)."""
    rets = (df['Close'] / df['Close'].shift(1) - 1.0).abs() * 100.0
    grid = pd.DataFrame({
        'close': df['Close'].resample('W-FRI').last(),
        'last': df.index.to_series().resample('W-FRI').last(),
        'mean_abs_ret': rets.resample('W-FRI').mean(),
    }).dropna()
    grid = grid[grid.index <= df.index[-1]]
    return grid


def walk_asset(df, model_name, half_life=None):
    """The weekly walk-forward over one asset's whole history. Returns
    {'skip': reason} or {'weeks', 'right', 'match_pct', 'trainings',
    'detail'} - detail rows are (week_end, probability, call_high,
    real_high, hit) per evaluated week, trainings are (year, cutoff date,
    training rows)."""
    dataset = vp.build_dataset(df)
    if dataset is None:
        return {'skip': f'too few usable rows after the '
                        f'{vp.WARMUP_BARS}-bar feature warm-up'}
    complete, features = dataset['complete'], dataset['features']
    grid = week_grid(df)
    if len(grid) < 2:
        return {'skip': 'fewer than two closed weeks'}

    reg = cls = None
    threshold = None
    model_year = None
    weeks = right = 0
    trainings, detail = [], []
    for i in range(len(grid) - 1):
        predict_point = grid['last'].iloc[i]      # the week's last bar
        if predict_point not in complete.index:
            continue
        # everything known at the prediction moment
        train_rows = complete[complete['tdate'] <= predict_point]
        if len(train_rows) < vp.MIN_TRAIN_ROWS:
            continue                             # not enough history yet
        if model_year is None or predict_point.year != model_year:
            # the yearly retrain: the first week of a new year rebuilds the
            # model on everything known by that moment
            model_year = predict_point.year
            reg, cls, threshold = vp.train_models(model_name, train_rows,
                                                   features, half_life)
            trainings.append((model_year, predict_point.date(),
                              len(train_rows)))
        if cls is None:
            continue          # a flat stretch trains no high/low classifier
        _, prob = vp.predict_models(reg, cls, complete.loc[predict_point],
                                    features)
        real_high = grid['mean_abs_ret'].iloc[i + 1] > threshold
        call_high = prob is not None and prob >= 0.5
        weeks += 1
        hit = call_high == bool(real_high)
        right += int(hit)
        detail.append((grid.index[i + 1].date(), prob, call_high,
                       bool(real_high), hit))
    if weeks == 0:
        return {'skip': 'no week admitted a high/low model (flat history?)'}
    return {'weeks': weeks, 'right': right, 'match_pct': right / weeks,
            'trainings': trainings, 'detail': detail}


def walk_asset_daily(df, model_name, half_life=None):
    """The DAILY mirror of the weekly walk: every day of the history
    predicts the NEXT one - same yearly retraining, same no-leakage cutoff
    (the model of each year trains on everything known by its first walked
    day) - and is checked against what really happened. Batched per year so
    a 25-year asset needs one predict call per year. Returns {'skip':
    reason} or the summary plus 'detail' (one row per evaluated day) and
    'trainings'."""
    dataset = vp.build_dataset(df)
    if dataset is None:
        return {'skip': f'too few usable rows after the '
                        f'{vp.WARMUP_BARS}-bar feature warm-up'}
    complete, features = dataset['complete'], dataset['features']
    days_idx = pd.DatetimeIndex(complete.index)
    tdates = pd.DatetimeIndex(complete['tdate'])
    ys = complete['y'].to_numpy(float)
    naives = complete['vol_lag1'].to_numpy(float)
    n = len(complete)
    # the training cutoff at day t: the rows whose target day is already
    # known by then (target day <= t) - a contiguous prefix, counted per day
    counts = tdates.searchsorted(days_idx, side='right')
    if not (counts >= vp.MIN_TRAIN_ROWS).any():
        return {'skip': f'not enough training history (need '
                        f'{vp.MIN_TRAIN_ROWS} usable rows)'}
    i0 = int(np.argmax(counts >= vp.MIN_TRAIN_ROWS))
    # one model per calendar year of the walked days
    years = days_idx.year.to_numpy()
    bounds = [i0] + [i for i in range(i0 + 1, n)
                     if years[i] != years[i - 1]] + [n]
    detail, trainings = [], []
    days = n_called = n_hit = 0
    sum_pred = sum_real = sum_abs = sum_naive = 0.0
    for a, b in zip(bounds[:-1], bounds[1:]):
        train_n = int(counts[a])
        reg, cls, threshold = vp.train_models(model_name,
                                               complete.iloc[:train_n],
                                               features, half_life)
        trainings.append((int(years[a]), days_idx[a].date(), train_n))
        X = complete[features].iloc[a:b]
        preds = reg.predict(X)
        probs = cls.predict_proba(X)[:, 1] if cls is not None else None
        for k in range(b - a):
            j = a + k
            pred, actual = float(preds[k]), float(ys[j])
            prob = float(probs[k]) if probs is not None else None
            real = actual > threshold
            call = hit = None
            if prob is not None:
                call = prob >= 0.5
                hit = call == real
                n_called += 1
                n_hit += int(hit)
            days += 1
            sum_pred += pred
            sum_real += actual
            sum_abs += abs(pred - actual)
            sum_naive += abs(naives[j] - actual)
            detail.append((str(tdates[j].date()), pred, prob, actual,
                           None if call is None else int(call), int(real),
                           None if hit is None else int(hit)))
    mae = sum_abs / days
    mae_naive = sum_naive / days
    return {'days': days,
            'avg_pred': sum_pred / days, 'avg_real': sum_real / days,
            'mae': mae, 'mae_naive': mae_naive,
            'skill': (1.0 - mae / mae_naive) if mae_naive > 0 else None,
            'match_pct': (n_hit / n_called) if n_called else None,
            'n_called': n_called, 'n_hit': n_hit,
            'detail': detail, 'trainings': trainings}


# --------------------------------------------------------------- storage

def store_accuracy(db_path, results, model_name, half_life=None):
    """Store the per-asset summaries AND the week-by-week rows - the only
    writes this program does: the volatility_accuracy table (one row per
    asset, INSERT OR REPLACE) and the volatility_accuracy_weeks table (one
    row per evaluated week, wholesale-refreshed per asset so it always
    mirrors the current bars). Returns (assets, weeks stored)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS volatility_accuracy ('
            'symbol TEXT PRIMARY KEY, '
            'weeks INTEGER, '
            'right_weeks INTEGER, '
            'match_pct REAL, '
            'model TEXT, '
            'computed_at TEXT, '
            'half_life REAL)')
        vp._ensure_column(conn, 'volatility_accuracy', 'half_life', 'REAL')
        vp._ensure_column(conn, 'volatility_accuracy', 'model', 'TEXT')
        vp._ensure_column(conn, 'volatility_accuracy', 'computed_at', 'TEXT')
        conn.execute(
            'CREATE TABLE IF NOT EXISTS volatility_accuracy_weeks ('
            'symbol TEXT NOT NULL, '
            'week_end TEXT NOT NULL, '        # the outcome week's Friday
            'prob REAL, '                    # the call's probability, at the week end before
            'call_high INTEGER, '            # 1 = the model called a high-volatility week
            'real_high INTEGER, '            # 1 = the real week was above the threshold
            'hit INTEGER, '                  # 1 = call and reality agreed
            'PRIMARY KEY (symbol, week_end))')
        computed_at = datetime.datetime.now().isoformat(timespec='seconds')
        weeks_stored = 0
        for symbol, r in results:
            conn.execute(
                'INSERT OR REPLACE INTO volatility_accuracy '
                '(symbol, weeks, right_weeks, match_pct, model, computed_at, '
                'half_life) VALUES (?, ?, ?, ?, ?, ?, ?)',
                (symbol, r['weeks'], r['right'], r['match_pct'], model_name,
                 computed_at, half_life))
            conn.execute('DELETE FROM volatility_accuracy_weeks WHERE symbol = ?',
                         (symbol,))
            week_rows = [(symbol, str(week_end), prob, int(call_high),
                         int(real_high), int(hit))
                         for week_end, prob, call_high, real_high, hit
                         in r['detail']]
            conn.executemany(
                'INSERT INTO volatility_accuracy_weeks '
                '(symbol, week_end, prob, call_high, real_high, hit) '
                'VALUES (?, ?, ?, ?, ?, ?)', week_rows)
            weeks_stored += len(week_rows)
        conn.commit()
        return len(results), weeks_stored
    finally:
        conn.close()


def store_daily(db_path, results, model_name, half_life=None):
    """Store the DAILY layer - the per-asset summary (volatility_daily: one
    row per asset, INSERT OR REPLACE) and the day-by-day rows
    (volatility_accuracy_days: one row per evaluated day,
    wholesale-refreshed per asset so it always mirrors the current bars).
    Returns (assets, days stored)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS volatility_daily ('
            'symbol TEXT PRIMARY KEY, '
            'days INTEGER, '
            'avg_pred REAL, '            # the model's average predicted daily volatility
            'avg_real REAL, '            # the average REALIZED daily volatility
            'mae REAL, '
            'skill REAL, '               # 1 - MAE / naive MAE (NULL when naive is 0)
            'match_pct REAL, '           # high/low day calls (NULL when no classifier)
            'model TEXT, '
            'computed_at TEXT, '
            'half_life REAL)')
        vp._ensure_column(conn, 'volatility_daily', 'half_life', 'REAL')
        vp._ensure_column(conn, 'volatility_daily', 'model', 'TEXT')
        vp._ensure_column(conn, 'volatility_daily', 'computed_at', 'TEXT')
        conn.execute(
            'CREATE TABLE IF NOT EXISTS volatility_accuracy_days ('
            'symbol TEXT NOT NULL, '
            'predicted_for TEXT NOT NULL, '   # the day that was predicted
            'pred_vol REAL, '
            'prob REAL, '
            'actual_vol REAL NOT NULL, '
            'call_high INTEGER, '             # NULL when no classifier that year
            'real_high INTEGER, '
            'hit INTEGER, '
            'PRIMARY KEY (symbol, predicted_for))')
        computed_at = datetime.datetime.now().isoformat(timespec='seconds')
        days_stored = 0
        for symbol, r in results:
            conn.execute(
                'INSERT OR REPLACE INTO volatility_daily '
                '(symbol, days, avg_pred, avg_real, mae, skill, match_pct, '
                'model, computed_at, half_life) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (symbol, r['days'], r['avg_pred'], r['avg_real'], r['mae'],
                 r['skill'], r['match_pct'], model_name, computed_at,
                 half_life))
            conn.execute('DELETE FROM volatility_accuracy_days WHERE symbol = ?',
                         (symbol,))
            day_rows = [(symbol, day, pred, prob, actual, call, real, hit)
                        for day, pred, prob, actual, call, real, hit
                        in r['detail']]
            conn.executemany(
                'INSERT INTO volatility_accuracy_days '
                '(symbol, predicted_for, pred_vol, prob, actual_vol, '
                'call_high, real_high, hit) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                day_rows)
            days_stored += len(day_rows)
        conn.commit()
        return len(results), days_stored
    finally:
        conn.close()


# --------------------------------------------------------------- printing

def fmt_pct(p):
    return f"{p * 100:.1f} %"


def print_weeks_table(rows, use_color):
    """The week table (WEEK | CALL | PROB | REAL | MATCH), shared by the
    verbose walk's sample and the --weeks listing of the stored rows."""
    def color_match(cell, row):
        if cell == 'OK':
            return vp.colored(cell, vp.GREEN, use_color, bold=True)
        if cell == 'X':
            return vp.colored(cell, vp.RED, use_color, bold=True)
        return None

    vp.print_table(['WEEK', 'CALL', 'PROB', 'REAL', 'MATCH'], rows,
                   ['<', '>', '>', '>', '>'],
                   colors=[None, None, None, None, color_match],
                   use_color=use_color)


def weeks_table_rows(weeks):
    """Plain rows for print_weeks_table from (week_end, prob, call_high,
    real_high, hit) tuples."""
    return [(str(week_end) if not isinstance(week_end, str) else week_end,
             'HIGH' if call_high else 'low',
             f"{prob * 100:.1f} %" if prob is not None else '-',
             'HIGH' if real_high else 'low',
             'OK' if hit else 'X')
            for week_end, prob, call_high, real_high, hit in weeks]


def print_verbose_walk(name, r, model_name, use_color):
    """--asset: the detailed walk - retrain points, per-year matches and a
    sample of the evaluated weeks."""
    print(f"Weekly walk ({model_name}, yearly retraining)")
    print(f"Retrain points: {len(r['trainings'])} "
          f"({r['trainings'][0][1]} .. {r['trainings'][-1][1]}, "
          f"{r['trainings'][0][2]} .. {r['trainings'][-1][2]} training rows)")
    # per-year match counts
    per_year = {}
    for week_end, _, _, _, hit in r['detail']:
        y = week_end.year
        n, ok = per_year.get(y, (0, 0))
        per_year[y] = (n + 1, ok + int(hit))
    print("\nPer year:")
    for y in sorted(per_year):
        n, ok = per_year[y]
        cell = f"{ok / n * 100:5.1f} %" if n else '  -  '
        print(f"  {y}  {ok:3d}/{n:<3d} {cell}")
    # a sample of the evaluated weeks
    n = len(r['detail'])
    idx = list(range(6)) + [None] + list(range(n - 6, n)) if n > 14 \
        else list(range(n))
    print(f"\nEvaluated weeks ({n}, first/last shown; the full history is "
          f"stored and browsable with --weeks):")
    rows = []
    for i in idx:
        if i is None:
            rows.append(('...', '', '', '', ''))
            continue
        rows.append(weeks_table_rows([r['detail'][i]])[0])
    print_weeks_table(rows, use_color)
    # the summary line, the number the predictor shows
    match = r['match_pct']
    color = vp.GREEN if use_color and match >= 0.55 else \
        (vp.RED if use_color and match <= 0.45 else None)
    print(f"\n{name}: {r['right']}/{r['weeks']} weeks right = "
          f"{vp.colored(fmt_pct(match), color, use_color, bold=True)} match")


def print_weeks_section(name, weeks, use_color):
    """One asset's stored weeks: the full table plus its summary line."""
    print(vp.colored(name, None, use_color, bold=True))
    print_weeks_table(weeks_table_rows(weeks), use_color)
    right = sum(int(hit) for *_, hit in weeks)
    n = len(weeks)
    color = vp.GREEN if use_color and right / n >= 0.55 else \
        (vp.RED if use_color and right / n <= 0.45 else None)
    print(f"  {right}/{n} weeks right = "
          f"{vp.colored(fmt_pct(right / n), color, use_color, bold=True)} match\n")


def list_weeks(conn, assets, args, use_color):
    """""--weeks: browse the STORED week-by-week results of the walk (one
    asset with --asset, every asset otherwise - a full report meant for
    redirecting to a file)."""
    try:
        rows = conn.execute(
            'SELECT symbol, week_end, prob, call_high, real_high, hit '
            'FROM volatility_accuracy_weeks ORDER BY symbol, week_end').fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        print("No stored weeks yet - run volatility_accuracy.py first "
              "(without --dry-run) to walk and store them.")
        return
    names = dict(assets)
    by_symbol = {}
    for symbol, week_end, prob, call_high, real_high, hit in rows:
        by_symbol.setdefault(symbol, []).append(
            (week_end, prob, bool(call_high), bool(real_high), bool(hit)))
    if args.asset is not None:
        symbol = assets[0][0]
        print_weeks_section(names.get(symbol, symbol), by_symbol.get(symbol, []),
                            use_color)
        return
    for symbol in sorted(by_symbol):
        print_weeks_section(names.get(symbol, symbol), by_symbol[symbol],
                            use_color)


def print_days_table(rows, use_color):
    """The day table (PREDICTED FOR | PRED VOL % | ACTUAL % | PROB | MATCH)."""
    def color_match(cell, row):
        if cell == 'OK':
            return vp.colored(cell, vp.GREEN, use_color, bold=True)
        if cell == 'X':
            return vp.colored(cell, vp.RED, use_color, bold=True)
        return None

    vp.print_table(['PREDICTED FOR', 'PRED VOL %', 'ACTUAL %', 'PROB HIGH',
                    'MATCH'], rows, ['<', '>', '>', '>', '>'],
                   colors=[None, None, None, None, color_match],
                   use_color=use_color)


def day_table_rows(days):
    """Plain rows for print_days_table from the stored day tuples."""
    return [(day,
             f"{pred:.2f}" if pred is not None else '-',
             f"{actual:.2f}",
             f"{prob * 100:.1f} %" if prob is not None else '-',
             'OK' if hit == 1 else ('X' if hit == 0 else '-'))
            for day, pred, prob, actual, call, real, hit in days]


def print_verbose_daily(r, model_name, use_color):
    """--daily --asset: the detailed daily walk - retrain points, per-year
    matches and a sample of the evaluated days."""
    print(f"Daily walk ({model_name}, yearly retraining)")
    print(f"Retrain points: {len(r['trainings'])} "
          f"({r['trainings'][0][1]} .. {r['trainings'][-1][1]}, "
          f"{r['trainings'][0][2]} .. {r['trainings'][-1][2]} training rows)")
    per_year = {}
    for day, _, _, _, _, _, hit in r['detail']:
        y = day[:4]
        n, ok, called = per_year.get(y, (0, 0, 0))
        per_year[y] = (n + 1, ok + (hit == 1), called + (hit is not None))
    print("\nPer year (day calls):")
    for y in sorted(per_year):
        n, ok, called = per_year[y]
        cell = f"{ok / called * 100:5.1f} %" if called else '  -  '
        print(f"  {y}  {ok:4d}/{called:<4d} {cell}")
    n = len(r['detail'])
    idx = list(range(6)) + [None] + list(range(n - 6, n)) if n > 14 \
        else list(range(n))
    print(f"\nEvaluated days ({n}, first/last shown; the full history is "
          f"stored and browsable with --days):")
    rows = [('...', '', '', '', '') if i is None
            else day_table_rows([r['detail'][i]])[0] for i in idx]
    print_days_table(rows, use_color)
    skill = f"{r['skill']:+.2f}" if r['skill'] is not None else '-'
    match = f"{r['match_pct'] * 100:.1f} %" if r['match_pct'] is not None else '-'
    print(f"\n{r['days']} days - average predicted {r['avg_pred']:.2f} % vs "
          f"realized {r['avg_real']:.2f} %, MAE {r['mae']:.3f} "
          f"(naive {r['mae_naive']:.3f}, skill {skill}), day match {match} "
          f"({r['n_hit']}/{r['n_called']} called days)")


def print_days_section(name, days, summary, use_color):
    """One asset's stored days: the full table plus its summary line."""
    print(vp.colored(name, None, use_color, bold=True))
    print_days_table(day_table_rows(days), use_color)
    if summary:
        skill = f"{summary['skill']:+.2f}" if summary['skill'] is not None else '-'
        match = (f"{summary['match_pct'] * 100:.1f} %"
                 if summary['match_pct'] is not None else '-')
        print(f"  {summary['days']} days - avg predicted "
              f"{summary['avg_pred']:.2f} % vs realized "
              f"{summary['avg_real']:.2f} %, MAE {summary['mae']:.3f} "
              f"(skill {skill}), day match {match}\n")


def list_days(conn, assets, args, use_color):
    """--days: browse the STORED day-by-day results of the daily walk (one
    asset with --asset, every asset otherwise - a full report meant for
    redirecting to a file)."""
    try:
        summaries = {sym: {'days': d, 'avg_pred': ap, 'avg_real': ar, 'mae': m,
                          'skill': s, 'match_pct': mp}
                     for sym, d, ap, ar, m, s, mp in conn.execute(
                         'SELECT symbol, days, avg_pred, avg_real, mae, '
                         'skill, match_pct FROM volatility_daily').fetchall()}
        rows = conn.execute(
            'SELECT symbol, predicted_for, pred_vol, prob, actual_vol, '
            'call_high, real_high, hit FROM volatility_accuracy_days '
            'ORDER BY symbol, predicted_for').fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        print("No stored days yet - run volatility_accuracy.py --daily first "
              "(without --dry-run) to walk and store them.")
        return
    names = dict(assets)
    by_symbol = {}
    for sym, day, pred, prob, actual, call, real, hit in rows:
        by_symbol.setdefault(sym, []).append(
            (day, pred, prob, actual, call, real, hit))
    if args.asset is not None:
        sym = assets[0][0]
        print_days_section(names.get(sym, sym), by_symbol.get(sym, []),
                           summaries.get(sym), use_color)
        return
    for sym in sorted(by_symbol):
        print_days_section(names.get(sym, sym), by_symbol[sym],
                           summaries.get(sym), use_color)


# --------------------------------------------------------------- driver

def run(args):
    if not Path(args.db).exists():
        sys.exit(f"Database not found: {args.db}")
    browsing = args.weeks or args.days
    if not browsing:
        vp.check_model_available(args.model)
    use_color = not args.no_color

    conn = vp.open_db_read_only(args.db)
    try:
        assets = vp.load_symbols(conn)
        if args.asset is not None:
            assets = [vp.resolve_asset(assets, args.asset)]
        verbose = args.asset is not None

        mode = ("browsing the stored weekly results" if args.weeks else
                "browsing the stored daily results" if args.days else
                "daily walk, yearly retraining" if args.daily else
                "weekly walk, yearly retraining")
        print(vp.colored("VOLATILITY ACCURACY", None, use_color, bold=True))
        print(f"Database: {args.db} (read-only, except the results tables)")
        info = f"assets: {len(assets)} | mode: {mode}"
        if not browsing:
            recency = (f"half-life {args.half_life:g} y"
                       if args.half_life else "uniform weights")
            info = (f"Model: {args.model} (one per asset, seed {vp.SEED}, "
                    f"{recency}) | {info}")
        print(info + "\n")

        if args.weeks:
            list_weeks(conn, assets, args, use_color)
            return
        if args.days:
            list_days(conn, assets, args, use_color)
            return

        results, skipped = [], []
        for symbol, name in assets:
            df = vp.load_bars(conn, symbol)
            if df is None:
                skipped.append((name, 'no bars stored'))
                continue
            if len(df) < args.min_bars:
                skipped.append((name, f'{len(df)} bars (< {args.min_bars})'))
                continue
            r = walk_asset_daily(df, args.model, args.half_life) if args.daily \
                else walk_asset(df, args.model, args.half_life)
            if 'skip' in r:
                skipped.append((name, r['skip']))
                continue
            results.append((symbol, name, r))
            if args.daily:
                if verbose:
                    print_verbose_daily(r, args.model, use_color)
                else:
                    skill = f" {r['skill']:+.2f}" if r['skill'] is not None else ''
                    match = fmt_pct(r['match_pct']) if r['match_pct'] is not None else '-'
                    print(f"{name}: {r['days']} days, avg {r['avg_pred']:.2f} "
                          f"vs {r['avg_real']:.2f} %, MAE {r['mae']:.3f} "
                          f"(skill{skill}), day match {match}")
            elif verbose:
                print_verbose_walk(name, r, args.model, use_color)
            else:
                print(f"{name}: {r['right']}/{r['weeks']} weeks right "
                      f"-> {fmt_pct(r['match_pct'])} match")
    finally:
        conn.close()

    if args.dry_run:
        print(f"\n--dry-run: nothing stored ({len(results)} result(s) walked)")
    elif results:
        if args.daily:
            n, days = store_daily(args.db, [(s, r) for s, _, r in results],
                                   args.model, args.half_life)
            print(f"\nStored {n} result(s) in volatility_daily and {days:,} day "
                  f"rows in volatility_accuracy_days "
                  f"(volatility_prediction.py shows the averages as AVG DAY % "
                  f"and the day calls as DAY MATCH %; browse with --days)")
        else:
            n, weeks = store_accuracy(args.db, [(s, r) for s, _, r in results],
                                      args.model, args.half_life)
            print(f"\nStored {n} result(s) in volatility_accuracy and {weeks} week "
                  f"rows in volatility_accuracy_weeks "
                  f"(volatility_prediction.py shows the summaries as MATCH %; "
                  f"browse the weeks with --weeks)")

    if skipped:
        shown = ', '.join(f"{s} ({reason})" for s, reason in skipped[:10])
        more = f" ... and {len(skipped) - 10} more" if len(skipped) > 10 else ''
        print(f"\nSkipped: {shown}{more}")
    if not results:
        print("Nothing to report.")


# --------------------------------------------------------------- CLI

def build_parser(parser):
    """This tool's flags (the standalone program)."""
    parser.add_argument('--db', default=vp.DB_DEFAULT,
                        help=f"path to the database (default: {vp.DB_DEFAULT}); "
                             f"read-only except the volatility_accuracy results "
                             f"table")
    parser.add_argument('--asset', default=None,
                        help="walk only this asset - its official symbol (e.g. "
                             "ES=F), its personalized display name, or an "
                             "unambiguous part of either; prints the verbose walk")
    parser.add_argument('--model', choices=sorted(vp.MODEL_FACTORIES),
                        default='lightgbm',
                        help="the ML algorithm to swap in (default: lightgbm)")
    parser.add_argument('--half-life', type=vp.half_life_arg,
                        default=vp.HALF_LIFE_DEFAULT, metavar='YEARS',
                        help=f"recency weighting of the walk's trainings: each "
                             f"day's weight halves every this many years of age "
                             f"(default: {vp.HALF_LIFE_DEFAULT:g} = uniform, the "
                             f"predictor's own default; e.g. 1 for a one-year "
                             f"half-life)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--daily', action='store_true',
                       help="walk DAYS instead of weeks: every day of the history "
                            "predicts the next one (same yearly retraining) - "
                            "the per-day rows are stored in "
                            "volatility_accuracy_days and the per-asset summary "
                            "(average predicted vs realized daily volatility, "
                            "MAE, skill, day-call match) in volatility_daily")
    group.add_argument('--days', action='store_true',
                       help="do not walk: browse the STORED day-by-day results "
                            "of the --daily walk - every stored day of one "
                            "asset with --asset, or of all assets at once (a "
                            "very long report, best redirected to a file)")
    group.add_argument('--weeks', action='store_true',
                       help="do not walk: browse the STORED week-by-week "
                            "results - every stored week of one asset with "
                            "--asset, or of all assets at once (a full report, "
                            "best redirected to a file)")
    parser.add_argument('--dry-run', action='store_true',
                        help="walk and report without storing the results")
    parser.add_argument('--min-bars', type=int, default=vp.MIN_BARS_DEFAULT,
                        help=f"skip assets with fewer stored bars "
                             f"(default: {vp.MIN_BARS_DEFAULT})")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Walk every week of the stored history, make the "
                    "volatility prediction as of each week's end (yearly "
                    "walk-forward retraining) and check it against what the "
                    "following week really did - the per-asset match "
                    "percentage and the week-by-week results are stored in the "
                    "database (browse the weeks with --weeks), and the "
                    "summaries are shown by volatility_prediction.py as "
                    "MATCH %.")
    build_parser(parser)
    run(parser.parse_args(argv))
    return 0


if __name__ == '__main__':
    sys.exit(main())