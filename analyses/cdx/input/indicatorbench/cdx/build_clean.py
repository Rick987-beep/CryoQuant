"""
build_clean.py
Produces cdx_na_ig_clean.csv — the canonical working file for CDX NA IG analysis.

Columns
-------
date        : YYYY-MM-DD, sorted ascending
cdx_na_ig   : spread in basis points (float)
pct_chg     : daily % change  (NaN for first row)
log_ret     : log return       (NaN for first row)
gap_days    : calendar days since previous observation (NaN for first row)
              >3 = non-standard gap (holiday cluster, data cut-off, etc.)
"""
import pandas as pd
import numpy as np

SRC = "cdx_na_ig.csv"
DST = "cdx_na_ig_clean.csv"

df = (
    pd.read_csv(SRC, parse_dates=["date"])
    .sort_values("date")
    .drop(columns=["year"])
    .reset_index(drop=True)
)

df["pct_chg"]  = df["cdx_na_ig"].pct_change() * 100
df["log_ret"]  = np.log(df["cdx_na_ig"] / df["cdx_na_ig"].shift(1))
df["gap_days"] = df["date"].diff().dt.days

# round to keep file compact
df["cdx_na_ig"] = df["cdx_na_ig"].round(4)
df["pct_chg"]   = df["pct_chg"].round(4)
df["log_ret"]   = df["log_ret"].round(6)
df["gap_days"]  = df["gap_days"].astype("Int64")   # nullable int, NaN for row 0

df.to_csv(DST, index=False)

print(f"Written: {DST}  ({len(df):,} rows)")
print(df.dtypes)
print()
print(df.head(5).to_string())
print("...")
print(df.tail(5).to_string())
print()
non_std = df[df["gap_days"] > 4]
print(f"Non-standard gaps (>4 days): {len(non_std)}")
if len(non_std):
    print(non_std[["date","cdx_na_ig","gap_days"]].to_string())
