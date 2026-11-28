#!/usr/bin/env python3
"""
next_week_recommendation.py - The best asset for the next week

Standalone (plain sqlite3 and numpy on the database file, no pystalker
imports): the weekly recommendation program built from the discoveries
of docs/all_2026_best_performing.md - the 48-week analysis of every
best trade of 2026. It applies the report's five rules to the CURRENT
week's data and ranks the candidates for the NEXT week:

  RULE 1 THE VEHICLE: the 3x leveraged products won 22/48 weeks and the
       semiconductor/AI complex 31/48 - so every candidate is
       IDENTIFIED FROM THE BARS (the 90-day daily-returns regression
       against SOXX and SPY): a 3x semis vehicle (slope ~+/-3 vs SOXX,
       the bull or the inverse), a high-beta single (slope >= 1.8 vs
       SPY), or a plain asset. The vehicle carries the biggest score
       weight - it is half the edge.
  RULE 2 THE EXPLOSION ZONE: 26/48 winners came off a >=10% move of
       the same asset the PRIOR week (13 momentum continuations + 13
       snapback reversals) - so the candidate pool is exactly that:
       the assets that moved >= --min-move (default 10%) in the last
       completed week (Friday close vs Friday close, the --weekly
       logic).
  RULE 3 THE FUEL: the winners' weeks delivered a median 7.2x the
       PREDICTED daily volatility, with prob_high >= 0.6 in 15/26 of
       the measurable weeks - so the fuel is the volatility
       predictor's stored call for the next trading day: the journal
       (volatility_predictions, its latest row) on a live run, the
       honest as-of walk (volatility_accuracy_days) with --date.
       Run volatility_prediction.py first for a fresh journal.
  RULE 4 THE DIRECTION IS NOT FORECAST - the report's honest split:
       from this exact setup the 2026 winners went 13 continuations
       and 13 snapbacks (a coin flip), and the regime label persisted
       only 43% of the weeks (20/46) - so the program recommends the
       ASSET (the where, which the data really measured) and prints
       BOTH trade setups (the long entry and the short entry, each
       with its 2x-predicted-volatility stop, the calibration of
       volatility_stop.py) instead of pretending to know the side.
  RULE 5 THE CLUSTER: the winners clustered (22 distinct assets in 48
       weeks) - so the cluster is scored (the semis/AI complex that
       won 65% of the weeks first, then the other 2026 clusters) and
       the pool is where the candidates come from.

The recommendation for the week after the last data day (the --date
flag runs it as of a past day: the pool week is the ISO week of the
last bar up to that date). The database is only READ (mode=ro).

Usage:
  python console_programs/next_week_recommendation.py
  python console_programs/next_week_recommendation.py --top 8
  python console_programs/next_week_recommendation.py --min-move 7
  python console_programs/next_week_recommendation.py --date 2026-11-20
"""
import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import numpy as np

DB_DEFAULT = str(Path.home() / '.pystalker' / 'pystalker.db')

# the report's stop calibration: 2x the predicted daily volatility let
# 85% of the 2026 winners run (the median adverse excursion was only
# 0.47x) - the level volatility_stop.py recommends
STOP_TIMES = 2.0

# the 2026 clusters (docs/all_2026_best_performing.md, Rule 5): the
# fixed families of the year's winners; the 3x semis VEHICLES are
# detected from the bars, the single names live here
SEMIS_SINGLES = {'SNDK', 'SNDKUSDT', 'SMCI', 'SMCIUSDT', 'LITE', 'LITEUSDT',
                 'ALAB', 'ALABUSDT', 'NBIS', 'NBISUSDT', 'IONQ', 'IONQUSDT',
                 'MU', 'TSM', 'AMD', 'NVDA', 'AVGO', 'TSMUSDT'}
BIOTECH = {'MRNA', 'MRNAUSDT', 'CYPH', 'CYPHUSDT', 'CRCL', 'CRCLUSDT',
           'TEM', 'TEMUSDT'}
VOLATILITY = {'^VIX', 'UVXY', 'UVXYUSDT'}
ENERGY = {'NG=F', 'NGUSDT', 'AGPU', 'AGPUUSDT', 'PL=F'}

# the regime indexes (Rule 4's honest input)
REGIME_INDEXES = ('SPY', 'SOXX', '^VIX')

GREEN = '\033[32m'
RED = '\033[31m'
BOLD = '\033[1m'
RESET = '\033[0m'


def colored(text, color, enabled=True, bold=False):
    """text wrapped in ANSI codes; the padding must already be applied."""
    if not enabled or color is None:
        return text
    prefix = BOLD if bold else ''
    return f"{prefix}{color}{text}{RESET}"


def get_display_name(conn, symbol):
    """The personalized display name, None when there is none - read
    straight from the settings table (this program is standalone)."""
    try:
        row = conn.execute(
            f'SELECT value FROM "{symbol}_settings" WHERE key = ?',
            ('display_name',)).fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def load_closes(conn, symbol):
    """(timestamps, closes) of the asset's daily bars; empty when it
    has no table."""
    try:
        rows = conn.execute(
            f'SELECT timestamp, close FROM "{symbol}_bars" '
            f'WHERE close IS NOT NULL ORDER BY timestamp').fetchall()
    except sqlite3.OperationalError:
        return np.array([]), np.array([])
    if not rows:
        return np.array([]), np.array([])
    return (np.array([int(r[0]) for r in rows]),
            np.array([float(r[1]) for r in rows]))


def iso_week(ts):
    d = datetime.fromtimestamp(int(ts)).isocalendar()
    return (d[0], d[1])


def weekly_move(ts, c, week, prev_week):
    """The asset's move of the ISO week vs the previous week's close
    (the --weekly logic: each asset's own last close of each week),
    None when either week is missing."""
    last_cur = last_prev = None
    for i, t in enumerate(ts):
        w = iso_week(t)
        if w == prev_week:
            last_prev = float(c[i])
        elif w == week:
            last_cur = float(c[i])
    if last_cur is None or last_prev is None or last_prev <= 0:
        return None, None
    pct = (last_cur / last_prev - 1) * 100.0
    return pct, last_cur


def slope_vs(ref_ts, ref_c, ts, c, upto, days=90):
    """The slope and correlation of the asset's daily returns against a
    reference's over the trailing `days` returns ending at upto."""
    def rets(a_ts, a_c):
        m = a_ts <= upto
        ats, ac = a_ts[m][-days - 1:], a_c[m][-days - 1:]
        return {int(ats[i]): (ac[i + 1] / ac[i] - 1) * 100
                for i in range(len(ats) - 1) if ac[i] > 0}
    r1, r2 = rets(ref_ts, ref_c), rets(ts, c)
    common = sorted(set(r1) & set(r2))
    if len(common) < 40:
        return None, None
    x = np.array([r1[t] for t in common])
    y = np.array([r2[t] for t in common])
    return float(np.polyfit(x, y, 1)[0]), float(np.corrcoef(x, y)[0, 1])


def classify_vehicle(symbol, slope_soxx, r_soxx, slope_spy, r_spy):
    """(the vehicle label, the score 0-10) - identified from the bars,
    never from the name (the report's method). The INVERSE vehicles
    correlate NEGATIVELY with their underlying, so both tests use the
    absolute values. The volatility family is labeled what it is (it
    also moves opposite the semis, but it is not a leveraged product
    of them)."""
    if symbol in VOLATILITY:
        if slope_soxx is not None:
            return (f"the volatility vehicle (slope {slope_soxx:+.1f} vs SOXX)", 8)
        return ("the volatility vehicle", 8)
    if slope_soxx is not None and abs(slope_soxx) >= 1.8 and abs(r_soxx) >= 0.55:
        return (f"3x semis {'BULL' if slope_soxx > 0 else 'INVERSE'} "
                f"(slope {slope_soxx:+.1f} vs SOXX)", 10)
    if slope_spy is not None and abs(slope_spy) >= 1.8:
        return (f"high-beta single (slope {slope_spy:+.1f} vs SPY)", 7)
    return ("plain", 3)


def cluster_of(symbol, vehicle):
    v = vehicle.lower()
    if '3x semis' in v:
        return 'semis/AI', 5
    if symbol in SEMIS_SINGLES:
        return 'semis/AI', 5
    if symbol in BIOTECH:
        return 'biotech', 3
    if symbol in VOLATILITY:
        return 'volatility', 3
    if symbol in ENERGY:
        return 'energy', 3
    return 'other', 1


def latest_fuel(conn, symbol, first_day):
    """(pred_vol, prob, source, prediction_date) - the honest call for
    the first trading day after the anchor: the as-of walk first (only
    when that day is known, the --date runs), the journal as the
    fallback (the live runs: its latest row is the freshest call)."""
    if first_day:
        row = conn.execute(
            'SELECT pred_vol, prob FROM volatility_accuracy_days '
            'WHERE symbol = ? AND predicted_for = ?', (symbol, first_day)).fetchone()
        if row and row[0] is not None:
            return row[0], row[1], 'the as-of walk', first_day
    rows = conn.execute(
        'SELECT predicted_vol, prob_high, predicted_date FROM volatility_predictions '
        'WHERE symbol = ? ORDER BY made_at DESC LIMIT 1', (symbol,)).fetchall()
    if rows:
        return rows[0][0], rows[0][1], 'the journal', rows[0][2]
    return None, None, None, None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="the best asset for the NEXT week - the 2026 strategy "
                    "report's five rules (the vehicle, the explosion zone, "
                    "the fuel, the honest direction split, the cluster) "
                    "applied to the current week's data")
    parser.add_argument('--db', default=DB_DEFAULT,
                        help=f"path to the database (default: {DB_DEFAULT})")
    parser.add_argument('--min-move', type=float, default=10.0, metavar='PCT',
                        help="the explosion-zone threshold: the assets that "
                             "moved at least this percent in the completed "
                             "week (default: 10)")
    parser.add_argument('--top', type=int, default=5, metavar='N',
                        help="how many candidates to list (default: 5)")
    parser.add_argument('--date', default=None, metavar='YYYY-MM-DD',
                        help="run as of this past day (the pool week is the "
                             "ISO week of the last bar up to it)")
    parser.add_argument('--no-color', action='store_true',
                        help="plain text without ANSI colors")
    args = parser.parse_args(argv)

    if not Path(args.db).exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)
    conn = sqlite3.connect(
        f"file:{quote(str(Path(args.db).resolve()))}?mode=ro", uri=True)
    try:
        symbols = [r[0] for r in conn.execute(
            'SELECT symbol FROM symbols ORDER BY symbol').fetchall()]
        if not symbols:
            print("The database has no assets yet.")
            sys.exit(1)

        # the anchor: the newest bar at or before --date (or the newest)
        cutoff = (datetime.strptime(args.date, '%Y-%m-%d').timestamp() + 86400
                  if args.date else None)
        closes = {}
        raw_ts = {}
        anchor_ts = 0
        for s in symbols:
            ts, c = load_closes(conn, s)
            if not len(c):
                continue
            raw_ts[s] = ts
            if cutoff is not None:
                keep = ts <= cutoff
                ts, c = ts[keep], c[keep]
            if len(c):
                closes[s] = (ts, c)
                anchor_ts = max(anchor_ts, float(ts[-1]))
        if not closes:
            print(f"No price data{' up to ' + args.date if args.date else ''}.")
            sys.exit(1)
        anchor = datetime.fromtimestamp(int(anchor_ts))
        pool_week = iso_week(anchor_ts)
        # the previous ISO week that exists in the data
        all_weeks = sorted({iso_week(t) for ts, _ in closes.values()
                            for t in ts})
        prevs = [w for w in all_weeks if w < pool_week]
        if not prevs:
            print("Not enough history for a completed prior week.")
            sys.exit(1)
        prev_week = prevs[-1]

        use_color = not args.no_color
        pool_day = datetime.fromtimestamp(int(anchor_ts)).strftime('%Y-%m-%d')

        # the regime (Rule 4's input, honestly weak: 43% persistence)
        regime_parts, regime = [], 'mixed'
        idx_moves = {}
        for s in REGIME_INDEXES:
            if s not in closes:
                continue
            pct, _ = weekly_move(*closes[s], pool_week, prev_week)
            if pct is not None:
                idx_moves[s] = pct
        if all(s in idx_moves for s in REGIME_INDEXES):
            if idx_moves['SPY'] > 0 and idx_moves['SOXX'] > 0 and idx_moves['^VIX'] < 0:
                regime = 'risk-on'
            elif idx_moves['SPY'] < 0 and idx_moves['SOXX'] < 0 and idx_moves['^VIX'] > 0:
                regime = 'risk-off'

        # the pool (Rule 2): the explosion zone
        pool = []
        for s, (ts, c) in closes.items():
            pct, last = weekly_move(ts, c, pool_week, prev_week)
            if pct is None or abs(pct) < args.min_move:
                continue
            pool.append((s, pct, last))

        print(f"Report generated: "
              f"{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f"NEXT WEEK RECOMMENDATION - the week after {pool_day} "
              f"(the pool week {pool_week[0]}-W{pool_week[1]:02d}, "
              f"the 2026 strategy report's five rules)")
        if idx_moves:
            parts = '  '.join(f"{s} {p:+.1f}%" for s, p in idx_moves.items())
            print(f"the completed week: {parts} -> the regime {regime} "
                  f"(persists only 43% of the weeks - the direction is "
                  f"NOT forecast, see below)")
        print(f"the explosion zone (>= {args.min_move:g}% last week): "
              f"{len(pool)} asset(s)\n")

        # the references for the vehicle identification
        refs = {}
        for s in ('SOXX', 'SPY'):
            if s in closes:
                refs[s] = closes[s]

        # the fuel sources: the next trading day after the anchor, from
        # the UNFILTERED bars (with --date the future bars exist beyond
        # the cutoff; live the anchor is the newest bar, so None - the
        # journal's latest row is the call)
        next_days = sorted({int(t) for ts in raw_ts.values()
                            for t in ts if t > anchor_ts})
        first_day = (datetime.fromtimestamp(next_days[0]).strftime('%Y-%m-%d')
                     if next_days else None)

        candidates = []
        for s, pct, last in pool:
            vehicle, v_score = 'plain', 3
            if 'SOXX' in refs:
                sl, r = slope_vs(refs['SOXX'][0], refs['SOXX'][1],
                                 *closes[s], anchor_ts)
                if sl is not None:
                    vehicle, v_score = classify_vehicle(s, sl, r, None, None)
                    if vehicle == 'plain' and 'SPY' in refs:
                        sl2, r2 = slope_vs(refs['SPY'][0], refs['SPY'][1],
                                           *closes[s], anchor_ts)
                        if sl2 is not None:
                            vehicle, v_score = classify_vehicle(s, None, None,
                                                               sl2, r2)
            elif 'SPY' in refs:
                sl2, r2 = slope_vs(refs['SPY'][0], refs['SPY'][1],
                                   *closes[s], anchor_ts)
                if sl2 is not None:
                    vehicle, v_score = classify_vehicle(s, None, None, sl2, r2)
            cluster, c_score = cluster_of(s, vehicle)
            pv, prob, src, date_f = latest_fuel(conn, s, first_day)
            e_score = min(abs(pct), 40.0) / 4.0
            f_score = (prob * 10.0) if prob is not None else 0.0
            total = v_score + e_score + f_score + c_score
            candidates.append({
                'symbol': s, 'name': get_display_name(conn, s) or s,
                'pct': pct, 'close': last, 'vehicle': vehicle,
                'v_score': v_score, 'e_score': e_score, 'f_score': f_score,
                'c_score': c_score, 'total': total, 'cluster': cluster,
                'pred_vol': pv, 'prob': prob, 'fuel_src': src,
                'fuel_date': date_f})

        if not candidates:
            print(f"No asset moved >= {args.min_move:g}% in the completed "
                  f"week - the pool is empty.")
            print("(the honest note: 21/48 of the 2026 winners came from "
                  "quiet prior weeks; lower --min-move to widen the pool)")
            return

        candidates.sort(key=lambda x: (-x['total'], x['symbol']))
        rows = candidates[:max(1, args.top)]

        # the table
        hdr = (f"{'RANK':<5}{'ASSET':<22}{'LAST WK':>9}  {'VEHICLE':<36}"
               f"{'FUEL (vol / p_high) [w/j]':<27}{'SCORE':>6}")
        print(hdr)
        for i, cd in enumerate(rows, 1):
            src_mark = ('w' if cd['fuel_src'] == 'the as-of walk'
                        else 'j') if cd['fuel_src'] else ''
            fuel = (f"{cd['pred_vol']:.1f}% / {cd['prob']:.2f} [{src_mark}]"
                    if cd['prob'] is not None else
                    (f"{cd['pred_vol']:.1f}% / - [{src_mark}]"
                     if cd['pred_vol'] is not None else "no data"))
            color = GREEN if cd['pct'] > 0 else RED
            pct_s = colored(f"{cd['pct']:+8.1f}%", color, use_color)
            score_s = colored(f"{cd['total']:>5.1f}", GREEN if i == 1 else None,
                              use_color, bold=(i == 1))
            print(f"{i:<5}{cd['name']:<22}{pct_s}  {cd['vehicle']:<36}"
                  f"{fuel:<27}{score_s}")
        print("\n(the score = the vehicle 0-10 + the explosion 0-10 + the "
              "fuel 0-10 + the cluster 0-5; the components below)")

        # THE recommendation
        best = rows[0]
        print()
        print(colored(f"THE RECOMMENDATION FOR THE NEXT WEEK: {best['name']}",
                      GREEN, use_color, bold=True))
        print(f"  {best['name']} ({best['symbol']}) moved {best['pct']:+.1f}% "
              f"in the completed week - the explosion zone - and its vehicle "
              f"is a {best['vehicle']}.")
        pts = [f"the vehicle score {best['v_score']}/10 (Rule 1: the 3x "
               f"leveraged products won 22/48 weeks of 2026, the semis/AI "
               f"complex 31/48)"]
        pts.append(f"the explosion score {best['e_score']:.1f}/10 (Rule 2: "
                    f"26/48 winners came off a >=10% prior week)")
        if best['prob'] is not None:
            pts.append(f"the fuel {best['pred_vol']:.1f}% predicted daily "
                       f"volatility at p_high {best['prob']:.2f} "
                       f"({best['fuel_src']}, for {best['fuel_date']}) - "
                       f"(Rule 3: the winners' weeks ran a median 7.2x "
                       f"their predicted daily vol)")
        else:
            pts.append("NO fuel data stored for it - run "
                       "volatility_prediction.py first (Rule 3)")
        pts.append(f"the cluster {best['cluster']} (Rule 5: the winners "
                   f"repeat - 22 distinct assets over 48 weeks)")
        for p in pts:
            print(f"  - {p}")
        # both trade setups with the calibrated stop
        entry = best['close']
        sigma = best['pred_vol']
        print(f"\n  BOTH SIDES, each with its stop at {STOP_TIMES:g}x the "
              f"predicted daily volatility (the volatility_stop.py "
              f"calibration: 2x let 85% of the 2026 winners run):")
        if sigma:
            long_stop = entry * (1 - STOP_TIMES * sigma / 100.0)
            short_stop = entry * (1 + STOP_TIMES * sigma / 100.0)
            print(f"    LONG  entry {entry:.2f}  stop {long_stop:.2f} "
                  f"({STOP_TIMES * sigma:.1f}% below)  "
                  f"the risk {STOP_TIMES * sigma:.1f}%/unit")
            print(f"    SHORT entry {entry:.2f}  stop {short_stop:.2f} "
                  f"({STOP_TIMES * sigma:.1f}% above)  "
                  f"the risk {STOP_TIMES * sigma:.1f}%/unit")
            print(f"    the position that makes the stop survivable: at 1% "
                  f"account risk, {(1.0 / (STOP_TIMES * sigma)):.2f}x the "
                  f"account (no leverage)")
        else:
            print("    (no predicted volatility stored - run "
                  "volatility_stop.py with the realized fallback)")
        print(f"\n  THE DIRECTION, honestly: from this exact setup the 2026 "
              f"winners split 13 momentum continuations and 13 snapback "
              f"reversals, and the regime label persisted only 43% of the "
              f"weeks - the side is decided live (the week's first days), "
              f"not forecast; the explosion {best['pct']:+.1f}% is the fuel "
              f"for either.")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
