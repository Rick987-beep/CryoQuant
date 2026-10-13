#!/usr/bin/env python3
"""Phase 1 stop: load the active snapshot, QA, probe live sources, print cross-check samples.

Does not run pricing or simulation. Writes ``data/phase1_probe.json``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from src.data.probe import run_live_probes
from src.data.qa import qa_report
from src.data.reference import (
    load_eurex_settles,
    load_eurex_snapshot,
    load_fred_monthly,
    load_stocks_daily,
    load_yields_daily,
)
from src.paths import active_stamp, data_dir, is_reference_run


def _print_table(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ===")
    if not rows:
        print("(empty)")
        return
    keys = list(rows[0].keys())
    widths = {k: max(len(k), *(len(f"{r.get(k)}") for r in rows)) for k in keys}
    print("  ".join(k.ljust(widths[k]) for k in keys))
    for r in rows:
        print("  ".join(f"{r.get(k)}".ljust(widths[k]) for k in keys))


def main() -> int:
    stamp = active_stamp()
    label = "v5 reference" if is_reference_run() else "snapshot"

    yields = load_yields_daily()
    settles = load_eurex_settles()
    stocks = load_stocks_daily()
    fred = load_fred_monthly()
    snap = load_eurex_snapshot(stamp)

    qa = qa_report(yields, settles, stocks, fred)

    print(f"france_sovereign_stress Phase 1 — {label} {stamp}")
    print(f"QA ok={qa['ok']}")
    for t in qa["tables"]:
        flag = "OK" if t["ok"] else "FAIL"
        print(f"  [{flag}] {t['name']}: {t['rows']} rows {t['start']} → {t['end']}"
              + (f" issues={t['issues']}" if t.get("issues") else ""))

    # Cross-check samples from the active snapshot
    y_tail = [
        {
            "date": str(ts.date()),
            "oat10": round(float(r.oat10), 4),
            "bund10": round(float(r.bund10), 4),
            "spread_bp": round(float(r.spread_bp), 2),
        }
        for ts, r in yields.tail(5).iterrows()
    ]
    s_tail = [
        {
            "date": str(ts.date()),
            "FOAT_front": round(float(r.FOAT_front), 2),
            "FOAT_next": round(float(r.FOAT_next), 2),
            "FGBL_front": round(float(r.FGBL_front), 2),
            "FGBL_next": round(float(r.FGBL_next), 2),
        }
        for ts, r in settles.tail(5).iterrows()
    ]
    _print_table(f"{label} yields_daily (last 5)", y_tail)
    _print_table(f"{label} eurex_settles (last 5)", s_tail)

    yq = snap.get("yields", {})
    print(f"\n=== {label} quote (eurex_{stamp}.json) ===")
    print(
        f"  time={yq.get('time')}  oat10={yq.get('oat10')}  bund10={yq.get('bund10')}  "
        f"spread_bp={round((float(yq['oat10']) - float(yq['bund10'])) * 100, 2) if yq.get('oat10') else 'n/a'}"
    )
    print(f"  CAC last close (stocks_daily): {qa['spot_checks']['cac_last']:.2f} "
          f"on {qa['spot_checks']['cac_last_date']}")
    print(
        f"  FRED monthly last FR/DE/IT: "
        f"{float(fred['IRLTLT01FRM156N'].iloc[-1]):.3f} / "
        f"{float(fred['IRLTLT01DEM156N'].iloc[-1]):.3f} / "
        f"{float(fred['IRLTLT01ITM156N'].iloc[-1]):.3f} "
        f"({fred.index[-1].date()})"
    )

    print("\n=== live probes ===")
    live = run_live_probes()
    for name, res in live.items():
        if name == "all_ok":
            continue
        if res.get("ok"):
            extra = ""
            if "last" in res:
                extra = f" last={res['last']}"
            elif "last_close" in res:
                extra = f" last_close={res['last_close']}"
            elif "series" in res:
                extra = " " + ", ".join(
                    f"{k}={v['last']:.3f}@{v['end']}" for k, v in res["series"].items()
                )
            print(f"  [OK]   {name}: rows={res.get('rows', 'n/a')} "
                  f"{res.get('start', '')}→{res.get('end', '')}{extra}")
            if res.get("tail"):
                _print_table(f"live {name} tail", res["tail"])
        else:
            print(f"  [FAIL] {name}: {res.get('error')}")

    out = {
        "stamp": stamp,
        "qa": qa,
        "v5_samples": {
            "yields_daily_tail": y_tail,
            "eurex_settles_tail": s_tail,
            "snapshot_yields": yq,
        },
        "live": live,
    }
    out_path = data_dir() / "phase1_probe.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {out_path}")
    return 0 if qa["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
