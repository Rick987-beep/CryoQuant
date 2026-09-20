#!/usr/bin/env python3
"""Ingest Cboe VX front-month into macro_store + print vs cash-VIX sanity.

Uses the shared CryoQuant macro ingest path (also available as ``cboe:VX_FRONT``
in any study ``universe.yaml``). Disk-cached under ``macro/cboe/_raw/vx/`` —
re-runs are fast unless ``--force``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from cryoquant.data import macro_store
from cryoquant.data.ingest import run_ingest
from cryoquant.data.sources.cboe import fetch_vix

from src.paths import ANALYSIS_ROOT, load_config, reports_dir
from src.vix_data import ingest_start, parse_window

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-download CDN CSVs (default: use disk cache)",
    )
    args = ap.parse_args()

    cfg = load_config()
    start = ingest_start(cfg)
    _, end = parse_window(cfg)

    # Standard universe ingest — writes cboe/VX_FRONT* for all studies
    result = run_ingest(
        ANALYSIS_ROOT / "universe.yaml",
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        force=args.force,
        macro_only=True,
        symbols=["cboe:VX_FRONT"],
    )
    if result.failed:
        log.error("Ingest failed: %s", result.errors)
        return result.exit_code()

    front = macro_store.load_frame("cboe", "VX_FRONT", start, end)
    vix = fetch_vix(start, end)
    cmp = front[["settle", "futures", "contract_expiration"]].join(
        vix["close"].rename("vix_close"), how="inner"
    )
    cmp["basis"] = cmp["settle"] - cmp["vix_close"]
    cmp["basis_pct"] = cmp["basis"] / cmp["vix_close"]

    last10 = cmp.tail(10).copy()
    print("\n=== Last 10 sessions: VX front settle vs cash VIX ===")
    show = last10.copy()
    for c in ("settle", "vix_close"):
        show[c] = show[c].map(lambda x: f"{x:.2f}")
    show["basis"] = show["basis"].map(lambda x: f"{x:+.2f}")
    show["basis_pct"] = show["basis_pct"].map(lambda x: f"{100 * x:+.1f}%")
    show.index = show.index.date
    print(
        show[
            ["futures", "contract_expiration", "settle", "vix_close", "basis", "basis_pct"]
        ].to_string()
    )

    b = cmp["basis"].dropna()
    print("\n=== Sanity (overlap) ===")
    print(f"VX bars:          {len(front)}  [{front.index.min().date()} → {front.index.max().date()}]")
    print(f"overlap:          {len(cmp)}")
    print(f"basis mean:       {b.mean():+.3f} pts")
    print(f"basis median:     {b.median():+.3f} pts")
    print(f"|basis| mean:     {b.abs().mean():.3f} pts")
    print(f"share |basis|>0.05:{100 * (b.abs() > 0.05).mean():.1f}%")
    print(f"share settle==vix:{(cmp['settle'] == cmp['vix_close']).mean() * 100:.1f}%")

    # Continuity: monthly rolls should not skip contract months often
    rolls = front.loc[
        front["contract_expiration"].ne(front["contract_expiration"].shift()),
        ["futures", "contract_expiration", "settle"],
    ]
    print(f"\nrolls in sample:  {len(rolls)}")
    gaps = []
    exps = sorted({r for r in front["contract_expiration"].unique()})
    for a, b_ in zip(exps, exps[1:]):
        # expect ~1 month between consecutive front expirations
        from datetime import date as _d

        da, db = _d.fromisoformat(a), _d.fromisoformat(b_)
        if (db - da).days > 45:
            gaps.append((a, b_, (db - da).days))
    print(f"expiration gaps >45d: {len(gaps)}" + (f"  e.g. {gaps[:3]}" if gaps else "  (clean)"))

    out = reports_dir() / "vx_front_sanity.csv"
    cmp.to_csv(out)
    log.info("Wrote %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
