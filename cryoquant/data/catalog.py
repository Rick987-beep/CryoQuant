"""DuckDB-backed data catalog.

Tracks every dataset that has been fetched and stored under STORE_ROOT.
The catalog file lives at config.CATALOG_DB.

Schema::

    datasets(
        source TEXT, venue TEXT, ticker TEXT, tf TEXT,
        path TEXT, row_count BIGINT,
        ts_min TIMESTAMP, ts_max TIMESTAMP,
        schema_hash TEXT, last_refresh TIMESTAMP,
        PRIMARY KEY (source, venue, ticker, tf)
    )

Public interface::

    register(source, symbol, tf, path, row_count, ts_min, ts_max, schema_hash)
    lookup(symbol, tf)      -> dict | None
    list_datasets()         -> pd.DataFrame
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from cryocore.instruments import Symbol
from cryoquant import config

log = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS datasets (
    source        TEXT NOT NULL,
    venue         TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    tf            TEXT,
    path          TEXT NOT NULL,
    row_count     BIGINT,
    ts_min        TIMESTAMPTZ,
    ts_max        TIMESTAMPTZ,
    schema_hash   TEXT,
    last_refresh  TIMESTAMPTZ,
    PRIMARY KEY (source, venue, ticker, tf)
);
"""

_UPSERT_SQL = """
INSERT INTO datasets (source, venue, ticker, tf, path, row_count, ts_min, ts_max, schema_hash, last_refresh)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (source, venue, ticker, tf) DO UPDATE SET
    path         = excluded.path,
    row_count    = excluded.row_count,
    ts_min       = excluded.ts_min,
    ts_max       = excluded.ts_max,
    schema_hash  = excluded.schema_hash,
    last_refresh = excluded.last_refresh
;
"""


def _conn(db_path: Path | None = None):
    import duckdb
    path = db_path or config.CATALOG_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(_CREATE_SQL)
    return con


def register(
    source: str,
    symbol: Symbol,
    tf: str,
    path: Path,
    row_count: int,
    ts_min: datetime,
    ts_max: datetime,
    schema_hash: str = "",
    *,
    db_path: Path | None = None,
) -> None:
    """Insert or update a dataset entry in the catalog."""
    con = _conn(db_path)
    now = datetime.now(timezone.utc)
    con.execute(
        _UPSERT_SQL,
        [source, symbol.venue, symbol.ticker, tf, str(path),
         row_count, ts_min, ts_max, schema_hash, now],
    )
    con.close()
    log.debug("Catalog registered: %s/%s/%s (%d rows)", source, symbol, tf, row_count)


def lookup(
    symbol: Symbol,
    tf: str,
    source: str | None = None,
    *,
    db_path: Path | None = None,
) -> dict | None:
    """Return the most recent catalog entry for (symbol, tf) or None."""
    con = _conn(db_path)
    where = "WHERE venue = ? AND ticker = ? AND tf = ?"
    params: list = [symbol.venue, symbol.ticker, tf]
    if source:
        where += " AND source = ?"
        params.append(source)
    rows = con.execute(
        f"SELECT * FROM datasets {where} ORDER BY last_refresh DESC LIMIT 1",
        params,
    ).fetchall()
    cols = [d[0] for d in con.description]
    con.close()
    if not rows:
        return None
    return dict(zip(cols, rows[0]))


def list_datasets(*, db_path: Path | None = None) -> pd.DataFrame:
    """Return all catalog entries as a DataFrame."""
    con = _conn(db_path)
    df = con.execute("SELECT * FROM datasets ORDER BY source, venue, ticker, tf").df()
    con.close()
    return df


def dataframe_schema_hash(df: pd.DataFrame) -> str:
    """Stable hash of a DataFrame's column names and dtypes."""
    schema = str(sorted(zip(df.columns.tolist(), [str(d) for d in df.dtypes])))
    return hashlib.sha1(schema.encode()).hexdigest()[:12]
