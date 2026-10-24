"""
PyStalker - Automatic channel calculation

Computes an "Automatic channel" from the last 12 complete months of data
(excluding the current partial month), drawn as a normal channel drawing.

Candidate channels (in order):
  1. The window's yearly extremes - the highest high and the lowest low of
     the last year ("the last top point"): the one that occurred later is
     tried first (a low -> ascending channel, a high -> descending
     channel). This anchors the channel on the year's absolute minimum /
     maximum, so the channel STARTS on the real extreme.
  2. The "year start" pivot: among the confirmed swing points in the first
     quarter of the window, the one furthest from the window's midrange
     (a high -> descending channel, a low -> ascending channel).
  3. Every other confirmed swing point, most recent first.

For each candidate:
  - Base line from the anchor through supporting points in the next
    candles, ranked by cleanliness (fewest violations where another
    low/high touches or pierces the line; longest span wins ties;
    supports at least a confirmed-swing distance away are preferred).
  - The channel BEGINS at the anchor - the drawing starts its lines there,
    so the containment covers the bars from the anchor on: the base line
    may be touched by later lows/highs but never pierced, and the parallel
    line goes through the window's extreme from the anchor, so nothing
    crosses it. A candidate without an un pierced support is rejected.
  - Validation: the channel is invalid if any bar AFTER the analysis window
    (the current month) CLOSES beyond either channel line ("the price broke
    the channel").

The yearly extremes are tried on BOTH windows before any other candidate -
the channel must START on the year's absolute minimum/maximum, and when
the standard window's extreme channel is broken by the current price, the
extended window (which includes the current month) is the one whose extreme
channel still contains the newest prices. Then the remaining candidates are
tried, standard window first and then the extended retry. If not even that
admits a clean channel (some markets - an accelerating trend - pierce every
base line), the BEST-EFFORT channel is
drawn as a last resort, walking the candidates in their priority order:
the first whose base line is pierced by at most 15% of the window's price
range and that the current price has not broken (its pierce fraction is
returned in 'best_effort'; 0.0 for a clean
channel). Only when no best-effort channel exists either, None is returned
(the caller shows a message and draws nothing). The result is never
recalculated: once drawn it is a normal, static drawing.
"""
import numpy as np
import pandas as pd
from typing import Optional, Dict

# a best-effort channel (drawn when no containing channel exists at all)
# may leak at most this fraction of the window's price range; anything
# worse is not a channel and nothing is drawn
BEST_EFFORT_LEAK_CAP = 0.15


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


def _rank_second_anchors(i0, n, y0, values, kind, eps, min_span):
    """The second-anchor candidates for the base line, ranked by cleanliness.

    Every later bar is a candidate (its Low/High is the support price).
    Score per candidate (lower is cleaner):
      * another low/high piercing the line between the anchors: 2
      * touching the line between the anchors: 1
      * piercings after the second anchor (tests/touches after are
        confirmation and allowed): 1
    Candidates at least `min_span` bars away come first (nearer ones are
    only used when nothing else exists); ties prefer the longest span.
    """
    ranked = []
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
        ranked.append(((score, -(ic - i0)), ic, score))
    far = [r for r in ranked if -r[0][1] >= min_span]
    near = [r for r in ranked if -r[0][1] < min_span]
    far.sort(key=lambda r: r[0])
    near.sort(key=lambda r: r[0])
    return far + near


def _build_candidate(df, window, kind, i0, pivot_bars):
    """Build a channel from an anchor; returns (points, score, leak) or None.

    The channel BEGINS at the anchor - the drawing starts its lines there -
    so the containment covers the bars from the anchor onward: the parallel
    line goes through the extreme of the window from the anchor (it
    contains every bar by construction) and the base line may be touched by
    later lows/highs but never pierced. The supports are tried in
    cleanliness order, and the first one whose base line is not pierced
    from the anchor on is returned with leak 0. When every support is
    pierced, the one with the SMALLEST pierce is returned instead - the
    best-effort channel - with its leak as a fraction of the window's
    price range; the caller decides whether a best-effort channel is
    acceptable (some markets - e.g. an accelerating trend - admit no clean
    straight channel at all).
    """
    n = len(window)
    g_high = df['High'].values[window].astype(float)
    g_low = df['Low'].values[window].astype(float)
    rng = float(g_high.max() - g_low.min())
    eps = max(rng * 1e-6, 1e-9)
    # the visual containment tolerance as a FRACTION of the window's price
    # range: base-line pokes up to 1% of it are indistinguishable from
    # line touches
    contain_frac = 0.01
    values, extrema = (g_low, g_high) if kind == 'asc' else (g_high, g_low)
    y0 = values[i0]

    pos_all = np.arange(n)
    lows_all, highs_all = g_low[pos_all], g_high[pos_all]
    best_effort = None        # (leak, points, score)
    for _, ic, score in _rank_second_anchors(i0, n, y0, values, kind, eps, pivot_bars):
        slope = (values[ic] - y0) / (ic - i0)
        line_all = y0 + slope * (pos_all - i0)
        if kind == 'asc':
            # the upper line goes through the highest high from the anchor
            height = float((highs_all[i0:] - line_all[i0:]).max())
            if height <= 0:
                continue
            # the rising base line: later lows may touch it, never pierce it
            leak = float((line_all[i0:] - lows_all[i0:]).max()) / rng
        else:
            # the lower line goes through the lowest low from the anchor
            height = float((lows_all[i0:] - line_all[i0:]).min())
            if height >= 0:
                continue
            # the falling top line: later highs may touch it, never pierce it
            leak = float((highs_all[i0:] - line_all[i0:]).max()) / rng
        points = [
            (int(window[i0]), float(y0)),
            (int(window[ic]), float(values[ic])),
            (0.0, float(height)),
        ]
        if leak <= contain_frac:
            return points, score, 0.0          # base line not pierced
        if best_effort is None or leak < best_effort[0]:
            best_effort = (leak, points, score)
    if best_effort is not None:
        return best_effort[1], best_effort[2], best_effort[0]
    return None


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


def _find_with_window(df, window, pivot_bars, post_start=None, best_effort=False,
                      extremes_only=False):
    """Build and validate candidates over one analysis window.

    Returns the channel dict (see find_automatic_channel) or None. The
    strict pass only accepts channels whose base line is not pierced from
    the anchor on; with best_effort=True, when no strict candidate survives
    the best-effort channels (base-line pierces up to
    BEST_EFFORT_LEAK_CAP) are tried in candidate priority order, still
    subject to the current-price break validation. With extremes_only=True
    only the yearly extremes are tried (the later one first).
    post_start overrides the first bar used for the break validation
    (default: the first bar after the window).
    """
    g_high = df['High'].values[window].astype(float)
    g_low = df['Low'].values[window].astype(float)
    n = len(window)
    if n < 2:
        return None

    hi_piv, lo_piv = _find_pivots(df, window, pivot_bars)
    midrange = (float(g_high.max()) + float(g_low.min())) / 2.0

    # candidate 1: the yearly extremes ("the last top point"): the later one
    # first; the yearly low anchors an ascending channel, the yearly high a
    # descending one
    imax, imin = int(np.argmax(g_high)), int(np.argmin(g_low))
    if imax >= imin:
        extremes = [(imin, 'asc'), (imax, 'desc')]
    else:
        extremes = [(imax, 'desc'), (imin, 'asc')]

    # candidate 2: the year-start pivot (most extreme confirmed swing of the
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

    # candidate 3: every other confirmed swing point, most recent first
    others = [(j, 'desc') for j in hi_piv] + [(j, 'asc') for j in lo_piv]
    others.sort(key=lambda c: -c[0])

    # the yearly extremes are tried first - the channel must START on the
    # absolute minimum (ascending) or maximum (descending) when possible -
    # then the year-start pivot, then the remaining swing points
    candidates = []
    for c in extremes + ([start_pivot] if start_pivot else []) + others:
        if c not in candidates:
            candidates.append(c)
    if extremes_only:
        candidates = list(extremes)

    extremes_set = set(extremes)

    for i0, kind in candidates:
        built = _build_candidate(df, window, kind, i0, pivot_bars)
        if built is None:
            continue
        points, score, leak = built
        if leak > 0.0:
            continue          # not fully contained
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
            'best_effort': 0.0,
        }

    if not best_effort:
        return None

    # the best-effort fallback: no clean channel exists in this window
    # (every candidate's base line is pierced from its anchor on), so walk
    # the candidates in their priority order - the yearly extremes first,
    # as always - and draw the first one whose pierce is small enough
    # (capped at BEST_EFFORT_LEAK_CAP) and that the current price has not
    # broken
    for i0, kind in candidates:
        built = _build_candidate(df, window, kind, i0, pivot_bars)
        if built is None:
            continue
        points, score, leak = built
        if leak > BEST_EFFORT_LEAK_CAP:
            continue
        if _is_broken(df, window, kind, points, post_start=post_start):
            continue
        return {
            'type': 'asc_channel' if kind == 'asc' else 'desc_channel',
            'points': points,
            'window': (df.index[window[0]], df.index[window[-1]]),
            'score': int(score),
            'candidate': 'pivot',
            'pivot_bars': pivot_bars,
            'best_effort': float(leak),
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
      best_effort 0.0 for a clean, fully containing channel; otherwise the
                  leak fraction of the best-effort fallback (<= 15% of the
                  window's price range)
      extended    True when the retry including the current month was used
    """
    if df is None or len(df) < 2 or 'High' not in df.columns or 'Low' not in df.columns:
        return None

    window = _analysis_window(df)
    if len(window) < 2:
        window = np.arange(len(df))
    extended = _analysis_window(df, include_current=True)
    if len(extended) < 2:
        extended = np.arange(len(df))
    post_start = window[-1] + 1 if window[-1] + 1 <= len(df) - 1 else None

    # the yearly extremes outrank the window preference: a channel must
    # START on the year's absolute minimum/maximum when one exists, so the
    # extremes are tried on BOTH windows before any other candidate - when
    # the extreme channel of the standard window is broken by the current
    # price, the extended window (which includes the current month) is the
    # one whose extreme channel still contains the newest prices
    for w, is_extended, pstart in ((window, False, None),
                                   (extended, True, post_start)):
        result = _find_with_window(df, w, pivot_bars, post_start=pstart,
                                   extremes_only=True)
        if result is not None:
            result['extended'] = is_extended
            return result

    # the remaining candidates (year-start swing, then the other pivots),
    # standard window first, then the extended retry
    for w, is_extended, pstart in ((window, False, None),
                                   (extended, True, post_start)):
        result = _find_with_window(df, w, pivot_bars, post_start=pstart)
        if result is not None:
            result['extended'] = is_extended
            return result

    # no clean channel at all (e.g. an accelerating trend pierces every base
    # line): fall back to the best-effort channel - the first candidate in
    # priority order whose base line is pierced by at most
    # BEST_EFFORT_LEAK_CAP and that the current price has not broken
    for w, is_extended, pstart in ((window, False, None),
                                   (extended, True, post_start)):
        result = _find_with_window(df, w, pivot_bars, post_start=pstart,
                                   best_effort=True)
        if result is not None:
            result['extended'] = is_extended
            return result
    return None