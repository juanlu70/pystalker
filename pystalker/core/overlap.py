"""
PyStalker - Overlap calculation

The percent change of N assets' closes over the dates they ALL share
(the any-number sibling of the spread's two-asset calculation): each
series starts at 0 - the percent increase or decrease of every close
against the first shared close of its own asset - so the lines are
directly comparable by eye (the user's "compare correlation only by
viewing").

The default line colors: the first two assets keep the spread's blue
and red, the rest cycle a bright palette. The palette cycles when an
overlap has more assets than colors (the colors are changeable in the
chart's context menu anyway).
"""
import pandas as pd

OVERLAP_COLORS = [
    '#00BFFF',   # asset 1: the spread's blue
    '#FF6B6B',   # asset 2: the spread's red
    '#55FF00',   # green
    '#FFD700',   # gold
    '#FF55FF',   # magenta
    '#00FFFF',   # cyan
    '#FF8C00',   # orange
    '#BDAEFF',   # light violet
]


def overlap_colors(n: int) -> list:
    """The default line colors for an overlap of n assets (cycling)."""
    return [OVERLAP_COLORS[i % len(OVERLAP_COLORS)] for i in range(n)]


def carried_colors(new_symbols: list, old_symbols: list, old_colors: list) -> list:
    """The line colors for a CHANGED overlap (the user's choice): an
    asset that stays keeps its current color; a new asset gets the next
    FREE color of the palette (the colors the survivors keep are not
    reused), the palette cycling when it runs out."""
    taken = {}
    for sym, col in zip(old_symbols, old_colors):
        taken[sym] = col
    colors, free = [], [c for c in OVERLAP_COLORS if c not in taken.values()]
    for sym in new_symbols:
        if sym in taken:
            colors.append(taken[sym])
        else:
            if not free:
                free = list(OVERLAP_COLORS)
            colors.append(free.pop(0))
    return colors


def calculate_overlap(dfs: list, start_date: str = None):
    """The 0-based percent change of every asset's closes over the
    dates all of them share, from start_date on (an empty start_date =
    the first shared date, the user's "first data date"): returns
    (index, [series1, series2, ...]) or None when fewer than two assets
    come in, they share no date past the cutoff, or an asset's first
    shared close is zero (its percent change would be undefined)."""
    if not dfs or len(dfs) < 2:
        return None

    merged = None
    for i, df in enumerate(dfs):
        closes = df[['Close']].copy()
        closes.columns = [f'Close{i + 1}']
        merged = closes if merged is None else merged.join(closes,
                                                           how='inner')

    if start_date:
        merged = merged[merged.index >= start_date]

    if merged.empty:
        return None

    bases = merged.iloc[0]
    if any(pd.isna(b) or b == 0 for b in bases.values):
        return None

    series = [(merged[f'Close{i + 1}'] / bases[f'Close{i + 1}'] - 1.0)
              * 100.0 for i in range(len(dfs))]
    return merged.index, series
