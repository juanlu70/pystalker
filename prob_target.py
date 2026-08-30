#!/usr/bin/env python3
"""
prob_target.py - Risk/reward probability analysis for all assets

For each asset computes the probability of hitting a 20% target vs a 5% stop,
in both LONG and SHORT directions, using three models:

  1. Closer (empirical) - historical frequency
  2. Lognormal          - lognormal with recent volatility
  3. GradientBoosting   - sklearn GradientBoostingClassifier

Usage:
  python prob_target.py
  python prob_target.py --symbol BTC-USD
  python prob_target.py --target-pct 20 --stop-pct 5 --horizon 20
  python prob_target.py --symbol BTC-USD --date 2026-06-25
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler


DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')
MIN_BARS = 100


def get_symbols(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols ORDER BY symbol")
    syms = [r[0] for r in cur.fetchall()]
    conn.close()
    return syms


def load_bars(db_path, symbol):
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(
            f'SELECT * FROM "{symbol}_bars" ORDER BY timestamp', conn
        )
    except Exception:
        conn.close()
        return pd.DataFrame()
    conn.close()
    if df.empty:
        return df
    df['date'] = pd.to_datetime(df['timestamp'], unit='s')
    df = df.set_index('date')
    return df


def prob_closer(df, tgt_down, tgt_up, horizon):
    low_roll = df['low'].rolling(horizon).min().shift(-horizon)
    high_roll = df['high'].rolling(horizon).max().shift(-horizon)
    valid = low_roll.notna() & high_roll.notna()
    if valid.sum() == 0:
        return np.nan, np.nan, np.nan, np.nan
    pdn = (low_roll[valid] <= tgt_down).mean()
    pup = (high_roll[valid] >= tgt_up).mean()
    return pdn, pup


def prob_lognormal(df, tgt_down, tgt_up, horizon, vol_win=20):
    rets = df['close'].pct_change().dropna()
    w = min(vol_win, len(rets))
    sigma = rets.iloc[-w:].std() * np.sqrt(horizon)
    if sigma == 0:
        return np.nan, np.nan
    c = df['close'].iloc[-1]
    pdn = stats.norm.cdf(np.log(tgt_down / c) / sigma)
    pup = 1 - stats.norm.cdf(np.log(tgt_up / c) / sigma)
    return pdn, pup


def prob_gb(df, tgt_down, tgt_up, horizon):
    d = df.copy()
    d['r1'] = d['close'].pct_change(1)
    d['r3'] = d['close'].pct_change(3)
    d['r5'] = d['close'].pct_change(5)
    d['r10'] = d['close'].pct_change(10)
    d['r20'] = d['close'].pct_change(20)
    d['v10'] = d['r1'].rolling(10).std()
    d['v20'] = d['r1'].rolling(20).std()
    d['rng'] = (d['high'] - d['low']) / d['close']
    d['ra10'] = d['rng'].rolling(10).mean()
    d['ra20'] = d['rng'].rolling(20).mean()
    d['vc'] = d['volume'].pct_change(1)
    d['fmin'] = d['low'].rolling(horizon).min().shift(-horizon)
    d['fmax'] = d['high'].rolling(horizon).max().shift(-horizon)
    d['ydn'] = (d['fmin'] <= tgt_down).astype(int)
    d['yup'] = (d['fmax'] >= tgt_up).astype(int)

    feats = ['close', 'r1', 'r3', 'r5', 'r10', 'r20',
             'v10', 'v20', 'rng', 'ra10', 'ra20', 'vc']
    d[feats] = d[feats].replace([np.inf, -np.inf], np.nan)
    tr = d.dropna(subset=feats + ['ydn', 'yup'])
    if len(tr) < 50:
        return np.nan, np.nan

    X = tr[feats].values
    ydn = tr['ydn'].values
    yup = tr['yup'].values
    last = d.iloc[-1:][feats].replace([np.inf, -np.inf], np.nan).dropna()
    if last.empty:
        return np.nan, np.nan

    sc = StandardScaler()
    Xs = sc.fit_transform(X)
    Xp = sc.transform(last.values.reshape(1, -1))

    def _fit_one(y):
        if len(np.unique(y)) < 2:
            return float(y[0])
        gb = GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            subsample=0.8, random_state=42
        )
        gb.fit(Xs, y)
        p = gb.predict_proba(Xp)[0]
        return p[1] if len(p) > 1 else float('nan')

    return _fit_one(ydn), _fit_one(yup)


def main():
    ap = argparse.ArgumentParser(
        description='Risk/reward probability: 20%% target vs 5%% stop for all assets.'
    )
    ap.add_argument('--symbol', '-s', default=None,
                    help='Restrict to a single asset (default: all)')
    ap.add_argument('--target-pct', '-t', type=float, default=20,
                    help='Target %% from entry (default: 20)')
    ap.add_argument('--stop-pct', type=float, default=5,
                    help='Stop %% from entry (default: 5)')
    ap.add_argument('--horizon', '-H', type=int, default=10,
                    help='Trading-day horizon (default: 10)')
    ap.add_argument('--db', default=DB_DEFAULT,
                    help=f'Database path (default: {DB_DEFAULT})')
    ap.add_argument('--date', '-d', default=None,
                    help='Reference date YYYY-MM-DD (default: last bar)')
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"Database not found: {db}", file=sys.stderr)
        sys.exit(1)

    tgt_pct = args.target_pct
    stop_pct = args.stop_pct

    symbols = [args.symbol] if args.symbol else get_symbols(str(db))
    results = []

    for i, sym in enumerate(symbols):
        df = load_bars(str(db), sym)
        if df.empty or len(df) < MIN_BARS:
            continue

        if args.date:
            df = df.loc[:pd.Timestamp(args.date)]
            if df.empty or len(df) < MIN_BARS:
                continue

        c = df['close'].iloc[-1]
        long_tgt = c * (1 + tgt_pct / 100)
        long_stop = c * (1 - stop_pct / 100)
        short_tgt = c * (1 - tgt_pct / 100)
        short_stop = c * (1 + stop_pct / 100)

        print(f"\r  Processing {sym} ({i+1}/{len(symbols)})...", end='', flush=True, file=sys.stderr)

        cdn, cup = prob_closer(df, short_tgt, long_tgt, args.horizon)
        csdn, csup = prob_closer(df, long_stop, short_stop, args.horizon)
        ldn, lup = prob_lognormal(df, short_tgt, long_tgt, args.horizon)
        lsdn, lsup = prob_lognormal(df, long_stop, short_stop, args.horizon)
        gdn, gup = prob_gb(df, short_tgt, long_tgt, args.horizon)
        gsdn, gsup = prob_gb(df, long_stop, short_stop, args.horizon)

        results.append(dict(
            sym=sym, close=c, date=df.index[-1].date(),
            long_tgt=long_tgt, long_stop=long_stop,
            short_tgt=short_tgt, short_stop=short_stop,
            cdn=cdn, cup=cup, csdn=csdn, csup=csup,
            ldn=ldn, lup=lup, lsdn=lsdn, lsup=lsup,
            gdn=gdn, gup=gup, gsdn=gsdn, gsup=gsup,
        ))

    print(file=sys.stderr)

    if not results:
        print("No assets with enough data.", file=sys.stderr)
        sys.exit(1)

    sw = max(len(r['sym']) for r in results)
    sw = max(sw, 8)

    def fp(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return '  N/A  '
        return f'{v*100:5.1f}%'

    def edge(ptgt, pstop):
        if ptgt is None or pstop is None:
            return '  N/A  '
        if np.isnan(ptgt) or np.isnan(pstop):
            return '  N/A  '
        if pstop < 0.005 and ptgt < 0.005:
            return '   ~0  '
        if pstop < 0.005:
            return '  >>1  '
        r = ptgt / pstop
        if r > 999:
            return '  >>1  '
        return f'{r:5.2f}x'

    w1 = sw + 14
    hdr = (
        f"{'Symbol':<{sw}}  {'Close':>12}  {'Date':>10}  "
        f"{'Model':<18}  "
        f"{'LONG':^23}  "
        f"{'SHORT':^23}"
    )
    sep = '\u2500' * len(hdr)
    sub = (
        f"{'':<{w1}}  {'':>18}  "
        f"{'P(tgt+' + str(int(tgt_pct)) + '%)':>9} {'P(stp-' + str(int(stop_pct)) + '%)':>9} {'Edge':>5}  "
        f"{'P(tgt-' + str(int(tgt_pct)) + '%)':>9} {'P(stp+' + str(int(stop_pct)) + '%)':>9} {'Edge':>5}"
    )

    print(f"\n  Target: {tgt_pct}%  |  Stop: {stop_pct}%  |  Horizon: {args.horizon} days")
    print(f"  LONG  = take profit +{tgt_pct}% vs stop loss -{stop_pct}%")
    print(f"  SHORT = take profit -{tgt_pct}% vs stop loss +{stop_pct}%")
    print(f"  Edge  = P(target) / P(stop) — above 1.0x means favourable")
    print()
    print(f"  {sep}")
    print(f"  {hdr}")
    print(f"  {sub}")
    print(f"  {sep}")

    for r in results:
        row = f"{r['sym']:<{sw}}  {r['close']:>12,.2f}  {str(r['date']):>10}"
        print(f"  {row}  {'Closer':<18}  "
              f"{fp(r['cup']):>9} {fp(r['csdn']):>9} {edge(r['cup'], r['csdn']):>5}  "
              f"{fp(r['cdn']):>9} {fp(r['csup']):>9} {edge(r['cdn'], r['csup']):>5}")
        print(f"  {'':<{w1}}  {'Lognormal':<18}  "
              f"{fp(r['lup']):>9} {fp(r['lsdn']):>9} {edge(r['lup'], r['lsdn']):>5}  "
              f"{fp(r['ldn']):>9} {fp(r['lsup']):>9} {edge(r['ldn'], r['lsup']):>5}")
        print(f"  {'':<{w1}}  {'GradientBoosting':<18}  "
              f"{fp(r['gup']):>9} {fp(r['gsdn']):>9} {edge(r['gup'], r['gsdn']):>5}  "
              f"{fp(r['gdn']):>9} {fp(r['gsup']):>9} {edge(r['gdn'], r['gsup']):>5}")
        print(f"  {sep}")

    print()


if __name__ == '__main__':
    main()