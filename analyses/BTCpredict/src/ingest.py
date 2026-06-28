"""BTCpredict Phase 1 ingest router — dispatches universe.yaml list sections."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from cryocore.instruments import Symbol, get_instrument
from cryoquant.data.ingest import ingest_ohlcv, ingest_macro

log = logging.getLogger(__name__)


@dataclass
class SeriesRecord:
    id: str
    section: str
    key: str
    status: str  # ok | skipped | failed
    row_count: int = 0
    ts_min: str | None = None
    ts_max: str | None = None
    notes: str = ""


@dataclass
class IngestManifest:
    study_id: str
    ingested_at: str
    universe_version: int
    series: list[SeriesRecord] = field(default_factory=list)
    ok: int = 0
    skipped: int = 0
    failed: int = 0

    def add(self, rec: SeriesRecord) -> None:
        self.series.append(rec)
        if rec.status == "ok":
            self.ok += 1
        elif rec.status == "skipped":
            self.skipped += 1
        else:
            self.failed += 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def load_universe(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_start(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _record_range(idx, *, rec: SeriesRecord) -> None:
    if len(idx) == 0:
        return
    rec.row_count = len(idx)
    rec.ts_min = str(idx.min().date())
    rec.ts_max = str(idx.max().date())


def run_btcpredict_ingest(
    universe_path: Path | str,
    *,
    end: datetime | None = None,
    force: bool = False,
    dry_run: bool = False,
    smoke: bool = False,
    skip_optional: bool = False,
    study_id: str = "btcpredict_v1",
) -> IngestManifest:
    """Ingest all sections from BTCpredict universe.yaml."""
    universe = load_universe(universe_path)
    end_dt = end or datetime.now(timezone.utc)
    manifest = IngestManifest(
        study_id=study_id,
        ingested_at=datetime.now(timezone.utc).isoformat(),
        universe_version=int(universe.get("version", 1)),
    )

    smoke_start: datetime | None = None
    if smoke:
        end_dt = datetime.now(timezone.utc)
        smoke_start = (end_dt - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        log.info("Smoke mode: limiting window to last 30 days")

    for item in universe.get("ohlcv") or []:
        _ingest_ohlcv_item(item, end_dt, smoke_start=smoke_start,
                           force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("perp") or []:
        _ingest_perp_item(item, end_dt, smoke_start=smoke_start,
                          force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("macro") or []:
        _ingest_macro_item(item, end_dt, smoke_start=smoke_start,
                           force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("macro_events") or []:
        _ingest_fomc_item(item, end_dt, smoke_start=smoke_start,
                          force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("crypto_alt") or []:
        _ingest_crypto_alt_item(item, end_dt, smoke_start=smoke_start,
                                force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("network") or []:
        _ingest_network_item(item, end_dt, smoke_start=smoke_start,
                             force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("options") or []:
        _ingest_options_item(item, end_dt, smoke_start=smoke_start,
                             force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("institutional") or []:
        if skip_optional:
            manifest.add(SeriesRecord(item["id"], "institutional", item.get("series", ""), "skipped",
                                      notes="skip_optional"))
            continue
        _ingest_institutional_item(item, end_dt, smoke_start=smoke_start,
                                   force=force, dry_run=dry_run, manifest=manifest)

    for item in universe.get("cross_asset") or []:
        manifest.add(SeriesRecord(
            item["id"], "cross_asset", item.get("derived", ""), "skipped",
            notes="derived in Phase 2 — no ingest",
        ))

    log.info(
        "Ingest complete: %d ok, %d skipped, %d failed",
        manifest.ok, manifest.skipped, manifest.failed,
    )
    return manifest


def write_manifest(manifest: IngestManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def _ingest_ohlcv_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    rec = SeriesRecord(item["id"], "ohlcv", f"{item['venue']}:{item['ticker']}@{item['tf']}", "failed")
    start = _parse_start(item["start"])
    if smoke_start:
        start = max(start, smoke_start)
    sym_str = f"{item['venue']}:{item['ticker']}"
    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
        else:
            ok = ingest_ohlcv(sym_str, item["tf"], start, end_dt, force=force, dry_run=False)
            rec.status = "ok" if ok else "failed"
            if ok:
                from cryoquant.data import loader as ldr
                df = ldr.load(Symbol.parse(sym_str), item["tf"], start, end_dt)
                _record_range(df.index, rec=rec)
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)
        log.error("OHLCV %s failed: %s", item["id"], exc)


def _ingest_perp_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    from cryoquant.data import macro_store
    from cryoquant.data.sources import binance_perp

    series = item["series"]
    sym = Symbol(item["venue"], item["ticker"])
    key = f"{item['ticker']}_{series}"
    rec = SeriesRecord(item["id"], "perp", key, "failed")
    start = _parse_start(item["start"])
    if smoke_start:
        start = max(start, smoke_start)

    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
            manifest.add(rec)
            return

        if series == "funding":
            raw = binance_perp.fetch_funding(sym, start, end_dt)
            daily = binance_perp.funding_to_daily(raw)
            macro_store.write_series("binance_perp", f"{item['ticker']}_funding", daily, force=force)
            _record_range(daily.index, rec=rec)
            rec.status = "ok"
        elif series == "open_interest":
            from cryoquant.data.sources import xoomar_oi

            oi_start = max(start.date(), date(2021, 1, 1))
            raw = xoomar_oi.fetch_open_interest_daily(item["ticker"], oi_start, end_dt.date())
            if raw.empty:
                rec.status = "ok"
                rec.notes = "empty — Xoomar has no rows in range"
            else:
                s = raw["open_interest"]
                macro_store.write_series("xoomar", f"{item['ticker']}_open_interest", s, force=force)
                if "open_interest_usd" in raw.columns:
                    macro_store.write_series(
                        "xoomar", f"{item['ticker']}_open_interest_usd", raw["open_interest_usd"], force=force
                    )
                if "long_short_ratio" in raw.columns and raw["long_short_ratio"].notna().any():
                    macro_store.write_series(
                        "xoomar", f"{item['ticker']}_long_short_ratio", raw["long_short_ratio"], force=force
                    )
                _record_range(s.index, rec=rec)
                rec.status = "ok"
                if oi_start > start.date():
                    rec.notes = f"Xoomar history from {oi_start}; pre-2021 NaN (use funding B1/B2)"
        else:
            rec.notes = f"unknown perp series {series!r}"
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)
        log.error("Perp %s failed: %s", item["id"], exc)


def _ingest_macro_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    rec = SeriesRecord(item["id"], "macro", f"{item['source']}:{item.get('series_id') or item.get('ticker')}", "failed")
    start = _parse_start(item["start"])
    if smoke_start:
        start = max(start, smoke_start)

    try:
        source = item["source"]
        if source == "yahoo":
            sym_str = f"yahoo:{item['ticker']}"
            tf = item.get("tf", "1d")
            if dry_run:
                rec.status = "ok"
                rec.notes = "dry_run"
            else:
                ok = ingest_ohlcv(sym_str, tf, start, end_dt, force=force, dry_run=False)
                rec.status = "ok" if ok else "failed"
                if ok:
                    from cryoquant.data import loader as ldr
                    df = ldr.load(Symbol.parse(sym_str), tf, start, end_dt)
                    _record_range(df.index, rec=rec)
        elif source == "fred":
            sym_str = f"fred:{item['series_id']}"
            if dry_run:
                rec.status = "ok"
                rec.notes = "dry_run"
            else:
                ok = ingest_macro(sym_str, start, end_dt, force=force, dry_run=False)
                rec.status = "ok" if ok else "failed"
                if ok:
                    from cryoquant.data import macro_store
                    s = macro_store.load_series("fred", item["series_id"], start, end_dt)
                    _record_range(s.index, rec=rec)
        elif source == "cboe":
            if dry_run:
                rec.status = "ok"
                rec.notes = "dry_run"
            else:
                ok = ingest_macro("cboe:VIX", start, end_dt, force=force, dry_run=False)
                rec.status = "ok" if ok else "failed"
                if ok:
                    from cryoquant.data import macro_store
                    s = macro_store.load_series("cboe", "VIX_CLOSE", start, end_dt)
                    _record_range(s.index, rec=rec)
        else:
            rec.notes = f"unknown macro source {source!r}"
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)


def _ingest_fomc_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    from cryoquant.data import macro_store
    from cryoquant.data.sources import fomc_calendar

    rec = SeriesRecord(item["id"], "macro_events", item["series_id"], "failed")
    start = date.fromisoformat(item["start"])
    end_d = end_dt.date()
    if smoke_start:
        start = max(start, smoke_start.date())

    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
        else:
            df = fomc_calendar.fetch_fomc_decision_days(start, end_d)
            macro_store.write_frame("fed_calendar", item["series_id"], df, force=force)
            _record_range(df.index, rec=rec)
            rec.status = "ok"
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)


def _ingest_crypto_alt_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    from cryoquant.data import macro_store

    rec = SeriesRecord(item["id"], "crypto_alt", f"{item['source']}:{item['series_id']}", "failed")
    start = date.fromisoformat(item["start"])
    end_d = end_dt.date()
    if smoke_start:
        start = max(start, smoke_start.date())

    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
        elif item["source"] == "fear_greed":
            from cryoquant.data.sources import fear_greed
            df = fear_greed.fetch_series(start, end_d)
            macro_store.write_series("fear_greed", item["series_id"], df["value"], force=force)
            _record_range(df.index, rec=rec)
            rec.status = "ok"
        elif item["source"] == "defillama":
            from cryoquant.data.sources import defillama
            df = defillama.fetch_stablecoin_supply(start, end_d)
            macro_store.write_series("defillama", item["series_id"], df["value"], force=force)
            _record_range(df.index, rec=rec)
            rec.status = "ok"
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)


def _ingest_network_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    from cryoquant.data import macro_store
    from cryoquant.data.sources import coinmetrics

    metric = item["metric"]
    asset = item["asset"]
    key = f"{asset}_{metric}"
    rec = SeriesRecord(item["id"], "network", key, "failed")
    start = date.fromisoformat(item["start"])
    end_d = end_dt.date()
    if smoke_start:
        start = max(start, smoke_start.date())

    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
        else:
            df = coinmetrics.fetch_asset_metric(asset, metric, start, end_d)
            macro_store.write_frame("coinmetrics", key, df, force=force)
            _record_range(df.index, rec=rec)
            rec.status = "ok"
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)


def _ingest_options_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    from cryoquant.data import macro_store
    from cryoquant.data.sources import deribit_indices, deribit_options

    series = item["series"]
    underlying = item.get("underlying")
    if isinstance(underlying, list):
        u_label = "+".join(underlying)
    else:
        u_label = str(underlying)
    rec = SeriesRecord(item["id"], "options", f"{u_label}_{series}", "failed")
    start = date.fromisoformat(item["start"])
    end_d = end_dt.date()
    if smoke_start:
        start = max(start, smoke_start.date())

    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
            manifest.add(rec)
            return

        if series == "dvol":
            df = deribit_indices.fetch_dvol(underlying, start, end_d)
            macro_store.write_series("deribit", f"{underlying}_DVOL", df["dvol"], force=force)
            _record_range(df.index, rec=rec)
            rec.status = "ok"
        elif series == "chain":
            dates = deribit_options.list_dates()
            in_range = [d for d in dates if d >= start]
            rec.row_count = len(in_range)
            rec.status = "ok"
            if in_range:
                rec.ts_min = str(min(in_range))
                rec.ts_max = str(max(in_range))
            else:
                rec.notes = "no local chain parquets in range — forward ingest (C5) will populate"
        elif series == "chain_forward":
            saved = _forward_deribit_chain(underlying if isinstance(underlying, list) else [underlying], end_d)
            rec.status = "ok"
            rec.row_count = saved
            rec.notes = f"forward snapshots saved: {saved}"
        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)


def _forward_deribit_chain(underlyings: list[str], d: date) -> int:
    """Save today's Deribit book summary snapshot to CRYOBACKTESTER_DATA_DIR."""
    import requests

    from cryoquant import config

    out_dir = config.CRYOBACKTESTER_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    sess = requests.Session()

    for currency in underlyings:
        r = sess.get(
            "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
            params={"currency": currency, "kind": "option"},
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json().get("result") or []
        if not rows:
            continue
        import pandas as pd
        df = pd.DataFrame(rows)
        path = out_dir / f"options_{currency}_{d.isoformat()}.parquet"
        df.to_parquet(path)
        saved += 1
        log.info("Saved forward chain %s (%d rows)", path.name, len(df))

    # Also write unified options_YYYY-MM-DD if BTC
    if "BTC" in underlyings:
        r = sess.get(
            "https://www.deribit.com/api/v2/public/get_book_summary_by_currency",
            params={"currency": "BTC", "kind": "option"},
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json().get("result") or []
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows)
            path = out_dir / f"options_{d.isoformat()}.parquet"
            df.to_parquet(path)
            log.info("Saved unified chain %s (%d rows)", path.name, len(df))

    return saved


def _ingest_institutional_item(
    item: dict,
    end_dt: datetime,
    *,
    smoke_start: datetime | None,
    force: bool,
    dry_run: bool,
    manifest: IngestManifest,
) -> None:
    from cryoquant.data import macro_store
    from cryoquant.data.sources import farside_etf, strategy_treasury

    source = item.get("source", "farside")
    series = item["series"]
    rec = SeriesRecord(item["id"], "institutional", series, "failed")
    start = date.fromisoformat(item["start"])
    end_d = end_dt.date()
    if smoke_start:
        start = max(start, smoke_start.date())

    try:
        if dry_run:
            rec.status = "ok"
            rec.notes = "dry_run"
            manifest.add(rec)
            return

        if source == "farside":
            if series == "etf_flow_aggregate_us":
                df = farside_etf.fetch_aggregate_flows(start, end_d)
                macro_store.write_frame("farside", "etf_flow_aggregate_us", df, force=force)
                _record_range(df.index, rec=rec)
                rec.status = "ok"
                rec.notes = "Farside Investors full history"
            elif series == "etf_flow_per_ticker":
                tickers = item.get("tickers") or []
                shared_sess = __import__("requests").Session()
                by_ticker = farside_etf.fetch_all_ticker_flows(
                    tickers, start, end_d, session=shared_sess
                )
                ok_count = 0
                for ticker, df in by_ticker.items():
                    if df.empty:
                        continue
                    macro_store.write_frame("farside", f"etf_flow_{ticker}", df, force=force)
                    ok_count += 1
                rec.status = "ok" if ok_count else "failed"
                rec.notes = f"{ok_count}/{len(tickers)} tickers from Farside"
            else:
                rec.notes = f"unknown farside series {series}"
        elif source == "strategy":
            if series == "mstr_btc_purchases":
                df = strategy_treasury.fetch_mstr_purchases(start, end_d)
                macro_store.write_frame("strategy", "mstr_btc_purchases", df, force=force)
                _record_range(df.index, rec=rec)
                rec.status = "ok"
                rec.notes = "Strategy.com official disclosures"
            elif series == "mstr_btc_holdings":
                df = strategy_treasury.fetch_mstr_holdings(start, end_d)
                macro_store.write_frame("strategy", "mstr_btc_holdings", df, force=force)
                _record_range(df.index, rec=rec)
                rec.status = "ok"
                rec.notes = "Strategy.com official disclosures"
            else:
                rec.notes = f"unknown strategy series {series}"
        else:
            rec.status = "skipped"
            rec.notes = f"unsupported institutional source {source!r}"

        manifest.add(rec)
    except Exception as exc:
        rec.notes = str(exc)
        manifest.add(rec)
