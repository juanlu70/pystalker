#!/usr/bin/env python3
"""
pionex_assets.py - List all Pionex assets

Prints every Pionex product (the spot pairs like BTC_USDT - including their
tokenized assets like AAPLX_USDT - and the perpetual futures like
BTC_USDT_PERP), fetched live from the public Pionex API, with the exact
symbol you can type in the pystalker Download flow.

By default only enabled products are shown; use --all to include the
disabled ones, --search to filter, and --type to keep only spot pairs or
perpetuals.

The product list comes from the same PionexProvider the application uses
(pystalker/core/providers.py), so the symbols seen here are always the
ones the application will download.

Usage:
  python pionex_assets.py
  python pionex_assets.py --search BTC
  python pionex_assets.py --type spot
  python pionex_assets.py --type perp
  python pionex_assets.py --all
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pystalker.core.providers import PionexProvider

TYPE_CHOICES = ('all', 'spot', 'perp')


def _is_enabled(product: dict) -> bool:
    """Spot products carry an `enable` flag; perpetuals a trading status."""
    if 'enable' in product:
        return bool(product['enable'])
    return product.get('status') == 'TRADING'


def build_parser(parser):
    """This tool's flags, shared by the standalone program and pystalker_cli.py."""
    parser.add_argument('--search', default=None,
                        help="keep only products matching this text (symbol, base or quote)")
    parser.add_argument('--type', choices=TYPE_CHOICES, default='all',
                        help="spot: only spot pairs | perp: only perpetual futures | all (default)")
    parser.add_argument('--all', action='store_true',
                        help="include disabled products (a STATUS column is added)")


def run(args):
    try:
        products = PionexProvider().get_symbols()
    except Exception as e:
        print(f"Could not get the Pionex product list: {e}")
        sys.exit(1)

    if not products:
        print("Pionex returned an empty product list")
        sys.exit(1)

    rows = []
    for p in products:
        symbol = p.get('symbol') or ''
        ptype = p.get('type') or ''
        base = p.get('baseCurrency') or ''
        quote = p.get('quoteCurrency') or ''
        name = p.get('name') or ''
        # spot products carry an `enable` flag; perpetuals a trading status
        enabled = bool(p['enable']) if 'enable' in p else p.get('status') == 'TRADING'
        if not args.all and not enabled:
            continue
        if args.type == 'spot' and ptype != 'SPOT':
            continue
        if args.type == 'perp' and ptype != 'PERP':
            continue
        if args.search:
            text = args.search.strip().lower()
            if not any(text in value.lower() for value in (symbol, base, quote, name)):
                continue
        rows.append((symbol, ptype, base, quote, name, 'Enabled' if enabled else 'Disabled'))
    rows.sort(key=lambda r: (0 if r[1] == 'SPOT' else 1, r[0]))

    print(f"Report generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    scope = f"matching \"{args.search}\" " if args.search else ""
    print(f"Pionex products {scope}- {len(rows)} shown "
          f"({sum(1 for p in products if _is_enabled(p))} enabled, {len(products)} total)\n")

    if not rows:
        print("No product matches the filters")
        return

    sym_w = max(max(len(r[0]) for r in rows), len('SYMBOL'))
    type_w = 4
    base_w = max(max(len(r[2]) for r in rows), len('BASE'))
    quote_w = max(max(len(r[3]) for r in rows), len('QUOTE'))
    name_w = max(max(len(r[4]) for r in rows), len('NAME'))
    header = (f"{'SYMBOL':<{sym_w}}  {'TYPE':<{type_w}}  "
              f"{'BASE':<{base_w}}  {'QUOTE':<{quote_w}}  {'NAME':<{name_w}}")
    if args.all:
        header += f"  {'STATUS':<9}"
    print(header)
    for symbol, ptype, base, quote, name, status in rows:
        line = (f"{symbol:<{sym_w}}  {ptype:<{type_w}}  "
                f"{base:<{base_w}}  {quote:<{quote_w}}  {name:<{name_w}}")
        if args.all:
            line += f"  {status:<9}"
        print(line)

    spot_count = sum(1 for r in rows if r[1] == 'SPOT')
    perp_count = sum(1 for r in rows if r[1] == 'PERP')
    print(f"\n{len(rows)} product(s): {spot_count} spot, {perp_count} perpetual")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List all Pionex assets (symbols usable in pystalker)")
    build_parser(parser)
    run(parser.parse_args(argv))


if __name__ == '__main__':
    main()