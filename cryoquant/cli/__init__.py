"""CryoQuant CLI entry point.

Primary commands: ``catalog`` and ``models``.  ``backtest`` and ``signals`` remain as
compatibility stubs that print guidance (library-first); they may be wired up later.

Usage::

    python -m cryoquant.cli catalog list
    python -m cryoquant.cli models list
    python -m cryoquant.cli backtest spot --signal <id>   # stub → library hint
    python -m cryoquant.cli signals publish <id> --out <path>  # stub
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


def _cmd_models_list(args: argparse.Namespace) -> int:
    from cryoquant.models.registry import list_models
    df = list_models()
    if df.empty:
        print("No models registered.")
        return 0
    display_cols = ["model_id", "class", "feature_set_id", "feature_set_version",
                    "labeler", "train_start", "train_end", "artifact_path", "created_at"]
    cols = [c for c in display_cols if c in df.columns]
    print(df[cols].to_string(index=False))
    return 0


def _cmd_models_inspect(args: argparse.Namespace) -> int:
    from cryoquant.models.registry import get_model
    row = get_model(args.model_id)
    if row is None:
        print(f"Model not found: {args.model_id}")
        return 1
    import json
    for key, val in row.items():
        # Pretty-print JSON blobs
        if key.endswith("_json") and val:
            try:
                val = json.dumps(json.loads(val), indent=2)
            except Exception:
                pass
        print(f"{key:25s}: {val}")
    return 0


def _cmd_backtest_spot(args: argparse.Namespace) -> int:
    """Compatibility stub — directs users to the library API."""
    print(
        f"backtest spot: signal_id={args.signal_id!r}  "
        f"start={args.start!r}  end={args.end!r}\n"
        "Use cryoquant.backtest.simulate() directly to run a spot simulation.\n"
        "See docs/how_to_use.md §9."
    )
    return 0


def _cmd_backtest_options(args: argparse.Namespace) -> int:
    """Compatibility stub — directs users to the library API."""
    print(
        f"backtest options: signal_id={args.signal_id!r}  "
        f"dte={args.dte}  delta={args.delta}\n"
        "Use cryoquant.backtest.evaluate() directly to evaluate option P&L.\n"
        "See docs/how_to_use.md §10."
    )
    return 0


def _cmd_backtest_cryobt(args: argparse.Namespace) -> int:
    """Compatibility stub — directs users to the library API."""
    print(
        f"backtest cryobt: signal_id={args.signal_id!r}  "
        f"start={args.start!r}  end={args.end!r}\n"
        "Use cryoquant.backtest.CryoBTAdapter directly to run via CryoBacktester.\n"
        "See docs/how_to_use.md §9."
    )
    return 0


def _cmd_signals_publish(args: argparse.Namespace) -> int:
    """Compatibility stub — directs users to the library API."""
    print(
        f"signals publish: signal_id={args.signal_id!r}  out={args.out!r}\n"
        "Use emit_history() from cryoquant.signals.publishers directly.\n"
        "See docs/how_to_use.md §11."
    )
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

    # models sub-command
    mdl_parser = subparsers.add_parser("models", help="Model registry operations")
    mdl_sub = mdl_parser.add_subparsers(dest="subcommand")
    mdl_sub.add_parser("list", help="List all registered models")
    inspect_parser = mdl_sub.add_parser("inspect", help="Inspect a model by id")
    inspect_parser.add_argument("model_id", help="Model ID to inspect")

    # signals sub-command (compatibility stub)
    sig_parser = subparsers.add_parser("signals", help="Signal publication (stub)")
    sig_sub = sig_parser.add_subparsers(dest="subcommand")
    pub_parser = sig_sub.add_parser("publish", help="Emit signal history to a file (stub)")
    pub_parser.add_argument("signal_id", help="Signal ID to publish")
    pub_parser.add_argument("--out", required=True, help="Output path (.parquet)")

    # backtest sub-command (compatibility stubs)
    bt_parser = subparsers.add_parser("backtest", help="Backtest operations (stubs)")
    bt_sub = bt_parser.add_subparsers(dest="subcommand")

    bt_spot = bt_sub.add_parser("spot", help="Run a vectorised spot P&L simulation (stub)")
    bt_spot.add_argument("--signal", dest="signal_id", required=True, help="Signal ID")
    bt_spot.add_argument("--start", default=None, help="Start date (ISO)")
    bt_spot.add_argument("--end", default=None, help="End date (ISO)")

    bt_opt = bt_sub.add_parser("options", help="Evaluate option chain P&L (stub)")
    bt_opt.add_argument("--signal", dest="signal_id", required=True, help="Signal ID")
    bt_opt.add_argument("--dte", type=int, default=1)
    bt_opt.add_argument("--delta", type=float, default=0.25)
    bt_opt.add_argument("--start", default=None)
    bt_opt.add_argument("--end", default=None)

    bt_cbt = bt_sub.add_parser("cryobt", help="Run via CryoBacktester bridge (stub)")
    bt_cbt.add_argument("--signal", dest="signal_id", required=True, help="Signal ID")
    bt_cbt.add_argument("--start", default=None)
    bt_cbt.add_argument("--end", default=None)

    args = parser.parse_args(argv)

    if args.command == "catalog":
        if args.subcommand == "list":
            return _cmd_catalog_list(args)
        if args.subcommand == "refresh":
            return _cmd_catalog_refresh(args)
        cat_parser.print_help()
        return 1

    if args.command == "models":
        if args.subcommand == "list":
            return _cmd_models_list(args)
        if args.subcommand == "inspect":
            return _cmd_models_inspect(args)
        mdl_parser.print_help()
        return 1

    if args.command == "backtest":
        if args.subcommand == "spot":
            return _cmd_backtest_spot(args)
        if args.subcommand == "options":
            return _cmd_backtest_options(args)
        if args.subcommand == "cryobt":
            return _cmd_backtest_cryobt(args)
        bt_parser.print_help()
        return 1

    if args.command == "signals":
        if args.subcommand == "publish":
            return _cmd_signals_publish(args)
        sig_parser.print_help()
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
