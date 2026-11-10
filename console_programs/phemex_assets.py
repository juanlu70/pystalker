#!/usr/bin/env python3
"""
phemex_assets.py - List the Phemex assets

Prints the Phemex products fetched live from the public Phemex API, with the
exact symbol you can type in the pystalker Download flow.

By default it shows the perp futures and the tokenized assets, skipping the
normal crypto spot pairs: the crypto perp futures (BTCUSDT, BTCUSD...), the
TradFi perp futures on tokenized stocks/indices/commodities (TSLAUSDT,
AAPLUSDT, NAS100USDT, XAUUSDT - gold...) and the spot tokenized assets (the
Ondo tokenized stocks/ETFs like sTSLAONUSDT, and the xStocks series like
sSPCXXUSDT - SpaceX). Use --type crypto for the normal crypto spot pairs,
--type all for everything, --search to filter by name (e.g. "Tesla", "gold",
"BTC"), --quote to filter by quote currency, and --all to include the
delisted products.

The product list and the asset categories come from the same PhemexProvider
the application uses (pystalker/core/providers.py), so the symbols seen
here are always the ones the application will download.

Usage:
  python phemex_assets.py                      # perp futures + tokenized assets
  python phemex_assets.py --search Tesla
  python phemex_assets.py --type tokenized
  python phemex_assets.py --type crypto
  python phemex_assets.py --type all
  python phemex_assets.py --all
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.providers import PhemexProvider, PHEMEX_CATEGORY_LABELS

TYPE_CHOICES = ('perp', 'tradfi', 'tokenized', 'crypto', 'all')
DEFAULT_TYPES = ('perp', 'tradfi', 'tokenized')

CATEGORY_LABELS = PHEMEX_CATEGORY_LABELS
CATEGORY_ORDER = {'perp': 0, 'tradfi': 1, 'tokenized': 2, 'crypto': 3}
CATEGORY_TITLES = {'perp': 'crypto perp futures',
                   'tradfi': 'perp futures on tokenized assets (stocks, indices, commodities)',
                   'tokenized': 'tokenized assets (spot)',
                   'crypto': 'normal crypto spot pairs',
                   'all': 'all products'}


def build_parser(parser):
    """This tool's flags, shared by the standalone program and pystalker_cli.py."""
    parser.add_argument('--search', default=None,
                        help="keep only products matching this text (symbol, description or asset name)")
    parser.add_argument('--type', choices=TYPE_CHOICES, default=None,
                        help="perp: only crypto perp futures | tradfi: only perps on tokenized "
                             "stocks/indices/commodities | tokenized: only spot tokenized assets | "
                             "crypto: only normal crypto spot pairs | all: everything "
                             "(default: perps + tokenized assets)")
    parser.add_argument('--quote', default=None,
                        help="keep only products quoted in this currency (e.g. USDT)")
    parser.add_argument('--all', action='store_true',
                        help="include delisted products (a STATUS column is added)")


def run(args):
    provider = PhemexProvider()
    try:
        products = provider.get_products()
    except Exception as e:
        print(f"Could not get the Phemex product list: {e}")
        sys.exit(1)

    if not products:
        print("Phemex returned an empty product list")
        sys.exit(1)

    if args.type:
        categories = set(TYPE_CHOICES[:-1]) if args.type == 'all' else {args.type}
    else:
        categories = set(DEFAULT_TYPES)

    total = len(products)
    rows = []
    for p in products:
        symbol = p.get('symbol') or ''
        display = p.get('displaySymbol') or ''
        quote = p.get('quoteCurrency') or ''
        status = p.get('status') or ''
        category = provider.classify_product(p)
        name = provider.get_product_name(p)
        if not args.all and status != 'Listed':
            continue
        if category not in categories:
            continue
        if args.quote and quote.upper() != args.quote.upper():
            continue
        if args.search:
            text = args.search.strip().lower()
            if not any(text in s.lower() for s in (symbol, display, name)):
                continue
        rows.append((symbol, category, display, name, quote, status))

    rows.sort(key=lambda r: (CATEGORY_ORDER[r[1]], r[0]))

    listed = sum(1 for p in products if p.get('status') == 'Listed')
    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    title = CATEGORY_TITLES[args.type] if args.type else "perp futures and tokenized assets"
    scope = f"matching \"{args.search}\" " if args.search else ""
    print(f"Phemex {title} {scope}- {len(rows)} shown "
          f"({listed} listed products, {total} including delisted)\n")

    if not rows:
        print("No product matches the filters")
        return

    sym_w = max(max(len(r[0]) for r in rows), len('SYMBOL'))
    cat_w = max(max(len(CATEGORY_LABELS[r[1]]) for r in rows), len('CATEGORY'))
    desc_w = max(max(len(r[2]) for r in rows), len('DESCRIPTION'))
    name_w = max(max(len(r[3]) for r in rows), len('NAME'))
    quote_w = max(max(len(r[4]) for r in rows), len('QUOTE'))
    header = (f"{'SYMBOL':<{sym_w}}  {'CATEGORY':<{cat_w}}  {'DESCRIPTION':<{desc_w}}  "
              f"{'NAME':<{name_w}}  {'QUOTE':<{quote_w}}")
    if args.all:
        header += f"  {'STATUS':<9}"
    print(header)
    for symbol, category, display, name, quote, status in rows:
        line = (f"{symbol:<{sym_w}}  {CATEGORY_LABELS[category]:<{cat_w}}  "
                f"{display:<{desc_w}}  {name:<{name_w}}  {quote:<{quote_w}}")
        if args.all:
            line += f"  {status:<9}"
        print(line)

    counts = {}
    for _, category, _, _, _, _ in rows:
        counts[CATEGORY_LABELS[category]] = counts.get(CATEGORY_LABELS[category], 0) + 1
    breakdown = ", ".join(f"{n} {c.lower()}" for c, n in counts.items())
    print(f"\n{len(rows)} product(s): {breakdown}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List the Phemex assets (symbols usable in pystalker)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()