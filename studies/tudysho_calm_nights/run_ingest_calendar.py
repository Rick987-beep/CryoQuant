#!/usr/bin/env python3
"""Ingest scheduled economic + earnings calendar via CryoQuant macro_store."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

STUDY_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDY_DIR))

from cryoquant.data.sources.economic_events import (
    MACRO_STORE_KEYS,
    ingest_scheduled_events,
    load_scheduled_events,
)

from src.paths import load_config, reports_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=None, help="YYYY-MM-DD (default: config data.date_range.start)")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD (default: config data.date_range.end)")
    parser.add_argument("--force", action="store_true", help="Overwrite macro_store partitions")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only; do not write macro_store")
    args = parser.parse_args()

    cfg = load_config()
    dr = cfg["data"]["date_range"]
    start = date.fromisoformat(args.start or dr["start"])
    end = date.fromisoformat(args.end or dr["end"])
    tickers = tuple(cfg.get("event_calendar", {}).get("mag7", [])) or None

    print(f"[ingest] Scheduled events {start} → {end}")
    counts = ingest_scheduled_events(
        start,
        end,
        earnings_tickers=tickers,
        force=args.force,
        dry_run=args.dry_run,
    )
    print(f"[ingest] Row counts: {counts}")

    if args.dry_run:
        return 0

    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    cal = load_scheduled_events(start_dt, end_dt)

    out_dir = reports_dir() / "calendar"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "events.csv"
    cal.reset_index().to_csv(csv_path, index=False)

    summary = {
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "macro_store": {
            source: f"{source}/{series_id}"
            for source, series_id in MACRO_STORE_KEYS.items()
        },
        "n_events": int(len(cal)),
        "by_type": cal.groupby("event_type").size().to_dict() if not cal.empty else {},
        "by_slot": cal.groupby("release_slot").size().to_dict() if not cal.empty else {},
        "study_export_csv": str(csv_path),
    }
    summary_path = out_dir / "events_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"[ingest] Wrote macro_store + {csv_path}")
    if not cal.empty:
        print("[ingest] By type:", summary["by_type"])
        afternoon = cal[cal["release_slot"].isin(["afternoon", "evening"])]
        print(f"[ingest] Afternoon/evening: {len(afternoon)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
