"""CLI: run a full bake-off from a YAML candidate registry.

Examples:
    python -m pineforge.bakeoff --registry registry.yaml
    python -m pineforge.bakeoff --registry registry.yaml --comparison-id phase7_v1
    python -m pineforge.bakeoff --registry registry.yaml --quiet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import agent_api
from .registry import load_registry
from .schemas import Comparison


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="registry.yaml")
    p.add_argument("--comparison-id", default=None,
                   help="optional explicit id; default = bakeoff_<utc-stamp>")
    p.add_argument("--quiet", action="store_true",
                   help="emit Comparison JSON to stdout, suppress human summary")
    p.add_argument("--no-html", action="store_true",
                   help="skip per-run report.html and overview.html")
    args = p.parse_args(argv)

    baseline_run_id, specs = load_registry(args.registry)
    if not specs:
        raise SystemExit("registry has no enabled candidates")

    # Run each spec individually so we control write_html per-run.
    results = [
        agent_api.run_candidate(s, write_html=not args.no_html)
        for s in specs
    ]
    # Then collate via bakeoff (which would re-run, but caching makes it free).
    comp = agent_api.bakeoff(
        specs,
        baseline_run_id=baseline_run_id,
        comparison_id=args.comparison_id,
        persist=True,
    )

    if args.quiet:
        sys.stdout.write(comp.model_dump_json())
        sys.stdout.write("\n")
        return 0

    print(f"comparison_id: {comp.comparison_id}", file=sys.stderr)
    if baseline_run_id:
        print(f"baseline:       {baseline_run_id}", file=sys.stderr)
    print(f"winner:         {comp.winner_run_id}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"{'rank':>4}  {'candidate':<28} {'WRS':>8} {'Sharpe':>8} "
          f"{'CAGR':>8} {'maxDD':>8}  {'n_ep':>5} {'win%':>6} {'R':>5} {'E%/ep':>7} {'t':>6} {'sig':>3}  {'cmplx':>5}", file=sys.stderr)

    def _f(x, fmt=".3f"):
        return "  n/a" if x is None else format(x, fmt)

    def _ep_f(ep, attr, fmt=".3f"):
        if ep is None:
            return "  n/a"
        v = getattr(ep, attr)
        return "  n/a" if v is None else format(v, fmt)

    for r in comp.ranked:
        h = r.headline
        ep = r.episode_stats
        sig_sym = ("\u2605" if ep.sig else "?") if ep is not None else "n/a"
        c = r.complexity.n_primitives + r.complexity.n_feeds + r.complexity.n_params
        print(
            f"{r.rank:>4}  {r.candidate:<28} "
            f"{_f(h.worst_regime_sharpe):>8} "
            f"{_f(h.sharpe):>8} "
            f"{_f(h.cagr, '.2%'):>8} "
            f"{_f(h.max_drawdown, '.2%'):>8}  "
            f"{ep.n_ep if ep else 'n/a':>5} "
            f"{_ep_f(ep, 'win_rate', '.1%'):>6} "
            f"{_ep_f(ep, 'payoff_ratio', '.2f'):>5} "
            f"{_ep_f(ep, 'expectancy', '.2%'):>7} "
            f"{_ep_f(ep, 'edge_tstat', '.2f'):>6} "
            f"{sig_sym:>3}  "
            f"{c:>5}",
            file=sys.stderr,
        )
    print("", file=sys.stderr)
    if comp.decision_log:
        print("decision_log:", file=sys.stderr)
        for line in comp.decision_log:
            print(f"  - {line}", file=sys.stderr)

    print(f"\nartifacts: pineforge/comparisons/{comp.comparison_id}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
