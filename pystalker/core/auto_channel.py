"""
PyStalker - Automatic channel calculation

Computes an "Automatic channel" from the last 12 complete months of data
(excluding the current partial month), drawn as a normal channel drawing.

Candidate channels (in order):
  1. The "year start" pivot: among the confirmed swing points in the first
     quarter of the window, the one furthest from the window's midrange
     (a high -> descending channel, a low -> ascending channel). Anchoring
     here makes the channel cover the whole year.
  2. The window's yearly extremes - the highest high and the lowest low of
     the last year ("the last top point"): the one that occurred later is
     tried first (a low -> ascending, a high -> descending). This anchors
     the channel on the year's real low/high.
  3. Every other confirmed swing point, most recent first.

For each candidate:
  - Base line from the anchor to the cleanest supporting point in the next
    candles (fewest violations where another low/high touches or pierces the
    line; longest span wins ties; supports at least a confirmed-swing
    distance away are preferred).
  - The parallel line goes through the highest high (ascending) / lowest low
    (descending) of the window from the anchor, so nothing crosses it.
  - Validation: the channel is invalid if any bar AFTER the analysis window
    (the current month) CLOSES beyond either channel line ("the price broke
    the channel").

The first candidate that survives validation is drawn. If EVERY candidate of
the standard window is broken (e.g. a strongly trending market whose recent
closes went beyond every channel), the calculation is retried once with the
window INCLUDING the current month - the channel then reflects the newest
prices, while the current month's closes still act as the break validation.
If nothing survives, None is returned (the caller shows a message and draws
nothing). The result is never recalculated: once drawn it is a normal,
static drawing.
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict


def _month_shift(year: int, month: int, delta: int):
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def _analysis_window(df: pd.DataFrame, include_current: bool = False) -> np.ndarray:
    """Global bar positions of the analysis window.

    The window covers the last 12 complete months, excluding the current
    (possibly partial) month. With include_current=True the window runs from
    the start of the month 11 months before the current one up to the last
    bar, so it covers 12 months plus the current (partial) month - used as a
    retry when every standard-window candidate is broken. If the data does
    not reach back that far, the window starts at the first available bar.
    """
    idx = df.index
    last = idx[-1]
    tz = getattr(idx, 'tz', None)
    if include_current:
        start_year, start_month = _month_shift(last.year, last.month, -11)
        start_limit = pd.Timestamp(year=start_year, month=start_month, day=1)
        # tz-aware indexes (some data sources) cannot be compared with naive
        # timestamps: localize the window limits to the index timezone
        if tz is not None:
            start_limit = start_limit.tz_localize(tz)
        start_pos = idx.searchsorted(start_limit, side='left')
        return np.arange(start_pos, len(idx))

    end_year, end_month = _month_shift(last.year, last.month, -1)
    end_limit = pd.Timestamp(year=end_year, month=end_month, day=1) + pd.offsets.MonthEnd(0)
    start_year, start_month = _month_shift(end_year, end_month, -11)
    start_limit = pd.Timestamp(year=start_year, month=start_month, day=1)
    if tz is not None:
        end_limit = end_limit.tz_localize(tz)
        start_limit = start_limit.tz_localize(tz)

    end_pos = idx.searchsorted(end_limit, side='right')
    if end_pos < 2:
        end_pos = len(idx)  # data only inside the current month: use everything
    start_pos = idx.searchsorted(start_limit, side='left')
    return np.arange(start_pos, end_pos)


def _find_pivots(df: pd.DataFrame, window: np.ndarray, k: int):
    """Confirmed swing tops/bottoms inside the window.

    A bar is a pivot when its High (Low) is the extreme of the surrounding
    +/- k bars. The RIGHT side of the neighborhood must lie inside the window
    (the current month never creates window pivots); the LEFT side may extend
    before the window start into older data. On equal values the first bar of
    a plateau is the pivot. Returns lists of window-relative positions.
    """
    n = len(window)
    highs, lows = [], []
    if n <= k:
        return highs, lows
    g_high = df['High'].values
    g_low = df['Low'].values
    for j in range(n - k):
        g = window[j]
        lo = max(0, g - k)
        hi = g + k + 1  # right side inside the window: window[j] + k <= window[-1]
        seg = g_high[lo:hi]
        if g_high[g] == seg.max() and int(seg.argmax()) + lo == g:
            highs.append(j)
        seg = g_low[lo:hi]
        if g_low[g] == seg.min() and int(seg.argmin()) + lo == g:
            lows.append(j)
    return highs, lows


def _pick_second_anchor(i0, n, y0, values, kind, eps, min_span):
    """Pick the cleanest supporting anchor for the base line in the next candles.

    Every later bar is a candidate (its Low/High is the support price).
    Score per candidate (lower is cleaner):
      * another low/high piercing the line between the anchors: 2
      * touching the line between the anchors: 1
      * piercings after the second anchor (tests/touches after are
        confirmation and allowed): 1
    The cleanest candidate wins; ties prefer the longest span. Candidates at
    least `min_span` bars away are preferred; nearer candidates are only
    used if nothing else exists.
    """
    if i0 >= n - 1:
        return None
    best = None
    best_far = None
    for ic in range(i0 + 1, n):
        yc = values[ic]
        # the base line must respect the channel direction: rising support
        # (ascending) / falling resistance (descending)
        if kind == 'asc' and yc <= y0:
            continue
        if kind == 'desc' and yc >= y0:
            continue
        slope = (yc - y0) / (ic - i0)
        between = np.arange(i0 + 1, ic)
        if len(between):
            line_b = y0 + slope * (between - i0)
            seg = values[between]
            touch = int(np.count_nonzero(np.abs(seg - line_b) <= eps))
            if kind == 'asc':
                pierce = int(np.count_nonzero(seg < line_b - eps))
            else:
                pierce = int(np.count_nonzero(seg > line_b + eps))
        else:
            touch = pierce = 0
        post = np.arange(ic + 1, n)
        if len(post):
            line_p = y0 + slope * (post - i0)
            if kind == 'asc':
                pierce_post = int(np.count_nonzero(values[post] < line_p - eps))
            else:
                pierce_post = int(np.count_nonzero(values[post] > line_p + eps))
        else:
            pierce_post = 0
        score = 2 * pierce + touch + pierce_post
        key = (score, -(ic - i0))
        if best is None or key < best[0]:
            best = (key, ic, score)
        if ic - i0 >= min_span and (best_far is None or key < best_far[0]):
            best_far = (key, ic, score)
    if best_far is not None:
        return best_far[1], best_far[2]
    return best[1], best[2]


def _build_candidate(df, window, kind, i0, pivot_bars):
    """Build a channel from an anchor; returns (points, score) or None."""
    n = len(window)
    g_high = df['High'].values[window].astype(float)
    g_low = df['Low'].values[window].astype(float)
    eps = max(float(g_high.max() - g_low.min()) * 1e-6, 1e-9)
    values, extrema = (g_low, g_high) if kind == 'asc' else (g_high, g_low)
    y0 = values[i0]
    picked = _pick_second_anchor(i0, n, y0, values, kind, eps, pivot_bars)
    if picked is None:
        return None
    ic, score = picked
    slope = (values[ic] - y0) / (ic - i0)
    pos = np.arange(i0, n)
    line_vals = y0 + slope * (pos - i0)
    if kind == 'asc':
        height = float((g_high[pos] - line_vals).max())
        if height <= 0:
            return None
    else:
        height = float((g_low[pos] - line_vals).min())
        if height >= 0:
            return None
    points = [
        (int(window[i0]), float(y0)),
        (int(window[ic]), float(values[ic])),
        (0.0, float(height)),
    ]
    return points, score


def _is_broken(df, window, kind, points, post_start=None, eps_scale=1e-9):
    """True if any bar AFTER the analysis range closes beyond either line.

    The checked bars start at post_start (default: the first bar after the
    window) and run to the last bar of the data.
    """
    i0, ic = points[0][0], points[1][0]
    y0, yc = points[0][1], points[1][1]
    height = points[2][1]
    slope = (yc - y0) / (ic - i0)
    if post_start is None:
        post_start = window[-1] + 1
    post = np.arange(post_start, len(df))
    if len(post) == 0:
        return False
    if 'Close' not in df.columns:
        return False
    closes = df['Close'].values[post].astype(float)
    rng = float(np.nanmax(df['High'].values[window])) - float(np.nanmin(df['Low'].values[window]))
    eps = max(rng * eps_scale, 1e-9)
    for p, close in zip(post, closes):
        base = y0 + slope * (p - i0)
        other = base + height
        upper, lower = (other, base) if kind == 'asc' else (base, other)
        if close < lower - eps or close > upper + eps:
            return True
    return False


def _find_with_window(df, window, pivot_bars, post_start=None):
    """Build and validate candidates over one analysis window.

    Returns the channel dict (see find_automatic_channel) or None when every
    candidate is broken or unbuildable. post_start overrides the first bar
    used for the break validation (default: the first bar after the window).
    """
    g_high = df['High'].values[window].astype(float)
    g_low = df['Low'].values[window].astype(float)
    n = len(window)
    if n < 2:
        return None

    hi_piv, lo_piv = _find_pivots(df, window, pivot_bars)
    midrange = (float(g_high.max()) + float(g_low.min())) / 2.0

    # candidate 1: the year-start pivot (most extreme confirmed swing of the
    # first quarter of the window)
    start_pivot = None
    start_best_dev = None
    quarter = max(1, n // 4)
    for j in hi_piv:
        dev = g_high[j] - midrange
        if j < quarter and (start_best_dev is None or dev > start_best_dev):
            start_best_dev, start_pivot = dev, (j, 'desc')
    for j in lo_piv:
        dev = midrange - g_low[j]
        if j < quarter and (start_best_dev is None or dev > start_best_dev):
            start_best_dev, start_pivot = dev, (j, 'asc')

    # candidates 2: the yearly extremes ("the last top point"): the later one
    # first; the yearly low anchors an ascending channel, the yearly high a
    # descending one
    imax, imin = int(np.argmax(g_high)), int(np.argmin(g_low))
    if imax >= imin:
        extremes = [(imin, 'asc'), (imax, 'desc')]
    else:
        extremes = [(imax, 'desc'), (imin, 'asc')]

    # candidate 3: every other confirmed swing point, most recent first
    others = [(j, 'desc') for j in hi_piv] + [(j, 'asc') for j in lo_piv]
    others.sort(key=lambda c: -c[0])

    candidates = []
    for c in ([start_pivot] if start_pivot else []) + extremes + others:
        if c not in candidates:
            candidates.append(c)

    extremes_set = set(extremes)

    for i0, kind in candidates:
        built = _build_candidate(df, window, kind, i0, pivot_bars)
        if built is None:
            continue
        points, score = built
        if _is_broken(df, window, kind, points, post_start=post_start):
            continue
        if start_pivot and (i0, kind) == start_pivot:
            candidate_kind = 'start'
        elif (i0, kind) in extremes_set:
            candidate_kind = 'extreme'
        else:
            candidate_kind = 'pivot'
        return {
            'type': 'asc_channel' if kind == 'asc' else 'desc_channel',
            'points': points,
            'window': (df.index[window[0]], df.index[window[-1]]),
            'score': int(score),
            'candidate': candidate_kind,
            'pivot_bars': pivot_bars,
        }
    return None


def find_automatic_channel(df: pd.DataFrame, pivot_bars: int = 10) -> Optional[Dict]:
    """Compute the Automatic channel for the displayed data.

    First pass: the window is the last 12 complete months, excluding the
    current (partial) month. If every candidate in that window is broken by
    the current price (a close beyond either channel line), the calculation
    is retried once with the window INCLUDING the current month - so the
    channel reflects the newest prices - while the current month's closes
    still act as the break validation. If nothing survives, None is returned.

    Returns a dict with:
      type        'asc_channel' or 'desc_channel'
      points      [(bar, y), (bar, y), (0, height)] in global bar coordinates
      window      (start_date, end_date) analysed
      score       cleanliness of the base line (0 = no violations)
      candidate   'start' (year-start pivot), 'extreme' (yearly low/high
                  anchor) or 'pivot' (other swing point)
      extended    True when the retry including the current month was used
    """
    if df is None or len(df) < 2 or 'High' not in df.columns or 'Low' not in df.columns:
        return None

    window = _analysis_window(df)
    if len(window) < 2:
        window = np.arange(len(df))
    result = _find_with_window(df, window, pivot_bars)
    if result is not None:
        result['extended'] = False
        return result

    # every standard-window candidate is broken: retry once with the window
    # including the current month; the current month's closes are still the
    # break validation (they start right after the standard window ends)
    extended = _analysis_window(df, include_current=True)
    if len(extended) < 2:
        extended = np.arange(len(df))
    post_start = window[-1] + 1 if window[-1] + 1 <= len(df) - 1 else None
    result = _find_with_window(df, extended, pivot_bars, post_start=post_start)
    if result is not None:
        result['extended'] = True
        return result
    return None