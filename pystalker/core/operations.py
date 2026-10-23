"""
PyStalker - Operations core

The shared logic of the trading journal (Trading > Operations):

* the gain math (used by the in-application list and by the standalone
  operations_list.py CLI tool, so both always show the same numbers),
* read-only database accessors for the CLI (a plain sqlite3 connection,
  the channel_scanner precedent: no writes, no migrations, safe on the
  live database while the application runs).

An operation is 'planned' while it is still only a project that may or may
not start: its gains are not real yet, so the listings show them plain,
without the green/red colors. The closed state is the explicit "open" flag
(the exit price can exist as a reference while the operation still runs).
"""
import sqlite3
from datetime import datetime
from typing import Optional


def leverage_value(text):
    """The numeric leverage, or None for 'Combined' or other free text."""
    try:
        value = float(str(text).strip())
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def move_percent(side, entry_price, price):
    """Directional percent move of the operation: + when winning.

    Long: (price - entry) / entry. Short: (entry - price) / entry.
    """
    if not entry_price or not price:
        return None
    if side == 'Short':
        return (entry_price - price) / entry_price * 100
    return (price - entry_price) / entry_price * 100


def fmt_price(value):
    """Plain price text without trailing zeros or scientific notation."""
    s = f"{value:.8f}".rstrip('0').rstrip('.')
    return s or '0'


def fmt_gain(gain):
    """The gain cell text ('+' signed percent, '-' when there is none) - used
    by GAIN %, NET GAIN % and FINAL GAIN %."""
    return f"{gain:+.2f}%" if gain is not None else '-'


def operation_group(op) -> str:
    """The mutually exclusive group of an operation for the listings:
    'planned' (still only a project, whatever its open/closed state),
    'open' (running and not planned) or 'closed' (done and not planned)."""
    if op.get('planned'):
        return 'planned'
    if bool(op.get('open', 1)):
        return 'open'
    return 'closed'


def operation_metrics(op, current_price=None):
    """The listed metrics of an operation: (gain, net_gain, final_gain).

    gain: the leveraged directional move - entry -> current price while the
    operation is open, entry -> exit price once it is closed (the raw price
    move when the leverage is not a number, e.g. 'Combined').

    net_gain: the same directional move without the leverage (the 1x gain,
    the NET GAIN % of the listings).

    final_gain: the FINAL GAIN % - the leveraged gain entry -> exit price
    whenever there is one (the actual result once closed, the projection at
    the reference exit price while open; identical to gain for closed
    operations); None when there is no exit price.
    """
    closed = not bool(op.get('open', 1))
    side = op.get('side') or 'Long'
    entry_price = op.get('entry_price')
    exit_price = op.get('exit_price')
    lev = leverage_value(op.get('leverage'))

    net_gain = move_percent(side, entry_price, exit_price if closed else current_price)
    gain = net_gain * lev if (net_gain is not None and lev) else net_gain

    final_gain = None
    if exit_price is not None:
        raw_at_exit = move_percent(side, entry_price, exit_price)
        if raw_at_exit is not None:
            final_gain = raw_at_exit * lev if lev else raw_at_exit
    return gain, net_gain, final_gain


# -- read-only database access (a plain sqlite3 connection) ----------------

def get_assets(conn) -> list:
    """All asset symbols in the database (the `symbols` table)."""
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols")
    return [r[0] for r in cur.fetchall()]


def get_display_name(conn, symbol: str) -> Optional[str]:
    """The personalized display name of a symbol, None when it has none."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT value FROM "{symbol}_settings" WHERE key = ?', ('display_name',))
        row = cur.fetchone()
        return row[0] if row and row[0] else None
    except sqlite3.OperationalError:
        return None


def resolve_asset(conn, name: str) -> Optional[str]:
    """The official symbol for a typed asset name (case-insensitive):
    an exact match against the database symbols or their display names;
    None when the name is unknown."""
    text = (name or '').strip()
    if not text:
        return None
    symbols = get_assets(conn)
    for symbol in symbols:
        if symbol.lower() == text.lower():
            return symbol
    for symbol in symbols:
        if (get_display_name(conn, symbol) or '').lower() == text.lower():
            return symbol
    return None


def last_close(conn, symbol: str) -> Optional[float]:
    """The last close of the asset's stored daily bars (None without data)."""
    try:
        cur = conn.cursor()
        cur.execute(f'SELECT close FROM "{symbol}_bars" ORDER BY timestamp DESC LIMIT 1')
        row = cur.fetchone()
        return float(row[0]) if row else None
    except sqlite3.OperationalError:
        return None


def load_operations(conn) -> list:
    """All trading operations as dicts, oldest entry first
    (any column set: the dict keys follow the table's columns)."""
    cur = conn.cursor()
    cur.execute('SELECT * FROM operations ORDER BY entry_date')
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def list_operations(conn, asset=None, group=None, paper=None) -> dict:
    """The operations listing (the Trading > Operations list) for the CLI.

    Filters (None = keep everything):
      asset    keep only this asset's operations (case-insensitive substring
               against the stored name, the official symbol and the display name)
      group    'open' (running, not planned), 'planned' (all the planned
               operations) or 'closed' (done, not planned) - the mutually
               exclusive groups of the listings
      paper    True: only paper trading / False: only real money

    Returns {'generated': local datetime, 'rows': [...], 'total': N} where
    total counts the operations before the filters and each row is a dict:
      entry_date, asset (the text to display: the personalized name when the
      asset is in the database), symbol (the resolved official symbol, or None),
      paper, planned, side, entry_price, volume, leverage (text), lev (numeric),
      current_price, gain, net_gain, final_gain, exit_date, exit_price, open,
      group (the row's group: 'open' / 'planned' / 'closed')
    plus the group counts of the listed rows (n_open + n_planned + n_closed
    = len(rows)): n_open, n_closed, n_planned.
    Rows are sorted newest entry first (like the application's list).
    """
    operations = load_operations(conn)
    rows = []
    for op in operations:
        stored = op.get('asset') or ''
        symbol = resolve_asset(conn, stored)
        if symbol is not None:
            asset_text = get_display_name(conn, symbol) or symbol
        else:
            asset_text = stored
        if asset is not None:
            needle = asset.strip().lower()
            haystacks = (stored, symbol or '', asset_text,
                         get_display_name(conn, symbol) or '' if symbol else '')
            if not any(needle in h.lower() for h in haystacks):
                continue
        op_group = operation_group(op)
        if group is not None and op_group != group:
            continue
        if paper is not None and bool(op.get('paper')) != bool(paper):
            continue

        current_price = last_close(conn, symbol) if symbol is not None else None
        gain, net_gain, final_gain = operation_metrics(op, current_price)
        rows.append({
            'entry_date': op.get('entry_date') or '',
            'asset': asset_text,
            'symbol': symbol,
            'paper': bool(op.get('paper')),
            'planned': bool(op.get('planned')),
            'side': op.get('side') or 'Long',
            'entry_price': op.get('entry_price'),
            'volume': op.get('volume'),
            'leverage': str(op.get('leverage') or '').strip(),
            'lev': leverage_value(op.get('leverage')),
            'current_price': current_price,
            'gain': gain,
            'net_gain': net_gain,
            'final_gain': final_gain,
            'exit_date': op.get('exit_date') or '',
            'exit_price': op.get('exit_price'),
            'open': bool(op.get('open', 1)),
            'group': op_group,
        })
    rows.sort(key=lambda r: r['entry_date'], reverse=True)

    return {
        'generated': datetime.now().astimezone(),
        'rows': rows,
        'total': len(operations),
        'n_open': sum(1 for r in rows if r['group'] == 'open'),
        'n_closed': sum(1 for r in rows if r['group'] == 'closed'),
        'n_planned': sum(1 for r in rows if r['group'] == 'planned'),
    }