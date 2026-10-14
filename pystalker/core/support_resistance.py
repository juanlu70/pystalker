"""
PyStalker - Automatic long-term support & resistance detection

Finds the price levels where the market showed resistance to cross along ALL
the history ("long term" supports and resistances):

1. Confirmed swing highs and lows (pivot points: bar High/Low extreme of the
   surrounding +/- pivot_bars bars on both sides) are collected over the
   whole displayed history - every pivot is a touch of a price level.
2. Touches whose prices lie within tolerance_pct % of each other are
   clustered into one level (level price = average of its touches).
3. Levels with at least min_touches touches count as support/resistance; the
   strongest ones (most touches) are returned, up to max_levels.

A level touched by swing lows is acting as support, by swing highs as
resistance, by both as both.
"""
from typing import Dict, List

import numpy as np
import pandas as pd

from .auto_channel import _find_pivots


def find_support_resistance_levels(df: pd.DataFrame, pivot_bars: int = 10,
                                    tolerance_pct: float = 1.0, min_touches: int = 3,
                                    max_levels: int = 8) -> List[Dict]:
    """Find long-term support/resistance levels across all the data.

    Returns a list of dicts sorted by strength (most touches first):
      {'price': float, 'touches': int, 'kinds': sorted list with
       'support' and/or 'resistance'}
    Empty list when there is not enough data or no level reaches
    min_touches.
    """
    if df is None or len(df) < 2 or 'High' not in df.columns or 'Low' not in df.columns:
        return []

    # best effort: shrink the pivot window for short histories
    k = pivot_bars
    while k > 1 and len(df) < 2 * k + 1:
        k //= 2
    if len(df) < 2 * k + 1:
        return []

    window = np.arange(len(df))
    hi_piv, lo_piv = _find_pivots(df, window, k)
    high = df['High'].values[window].astype(float)
    low = df['Low'].values[window].astype(float)

    # every pivot is a touch: (price, kind)
    touches = [(high[j], 'resistance') for j in hi_piv]
    touches += [(low[j], 'support') for j in lo_piv]
    if len(touches) < min_touches:
        return []

    # cluster touches by price (greedy, anchored to the cluster's running mean)
    touches.sort(key=lambda t: t[0])
    tol_frac = max(tolerance_pct, 1e-9) / 100.0
    clusters = []
    for price, kind in touches:
        if clusters:
            c = clusters[-1]
            mean = c['sum'] / c['n']
            if abs(price - mean) <= tol_frac * abs(mean):
                c['sum'] += price
                c['n'] += 1
                c['kinds'].add(kind)
                continue
        clusters.append({'sum': price, 'n': 1, 'kinds': {kind}})

    levels = []
    for c in clusters:
        if c['n'] >= min_touches:
            levels.append({
                'price': c['sum'] / c['n'],
                'touches': c['n'],
                'kinds': sorted(c['kinds']),
            })
    levels.sort(key=lambda lv: (-lv['touches'], lv['price']))
    return levels[:max_levels]