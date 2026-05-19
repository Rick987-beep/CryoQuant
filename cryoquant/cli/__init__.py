"""CryoQuant CLI entry point.

Usage::

    python -m cryoquant.cli catalog list
    python -m cryoquant.cli catalog register --source binance_spot --venue binance.spot \\
        --ticker BTCUSDT --tf 1h --path /path/to/dir
"""
from __future__ import annotations

import argparse
import sys


def _cmd_catalog_list(args: argparse.Namespace) -> int:
    from cryoquant.data.catalog import list_datasets
    df = list_datasets()
    if df.empty:
        print("No datasets registered.")
        return 0
    # Compact display
    display_cols = ["source", "venue", "ticker", "tf", "row_count", "ts_min", "ts_max", "last_refresh"]
    cols = [c for c in display_cols if c in df.columns]
    print(df[cols].to_string(index=False))
    return 0


def _cmd_catalog_refresh(args: argparse.Namespace) -> int:
    print("catalog refresh: not yet implemented (use loader.load to trigger auto-refresh)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cryoquant.cli",
        description="CryoQuant command-line interface",
    )
    subparsers = parser.add_subparsers(dest="command")

    # catalog sub-command
    cat_parser = subparsers.add_parser("catalog", help="Dataset catalog operations")
    cat_sub = cat_parser.add_subparsers(dest="subcommand")
    cat_sub.add_parser("list", help="List all registered datasets")
    cat_sub.add_parser("refresh", help="Refresh catalog metadata from disk")

    args = parser.parse_args(argv)

    if args.command == "catalog":
        if args.subcommand == "list":
            return _cmd_catalog_list(args)
        if args.subcommand == "refresh":
            return _cmd_catalog_refresh(args)
        cat_parser.print_help()
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
