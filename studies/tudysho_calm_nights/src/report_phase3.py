"""Phase 3 HTML report — continuous calm index and entry schedule."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _esc(v: Any) -> str:
    return html.escape(str(v))


def render_phase3_report(result: dict[str, Any], daily: Any, out_path: Path) -> Path:
    pred = result.get("predictor", {})
    oos = result.get("walk_forward_oos", {})
    perm = result.get("permutation_test", {})
    mono = result.get("entry_monotonicity", {})
    cal = result.get("calibration", [])

    cal_rows = ""
    for row in cal:
        cal_rows += (
            f"<tr><td>{_esc(row.get('mci_mean', ''))}</td>"
            f"<td>{_esc(row.get('hci_mean', ''))}</td>"
            f"<td>{_esc(row.get('n', ''))}</td></tr>\n"
        )

    fold_rows = ""
    for f in oos.get("folds", []):
        fold_rows += (
            f"<tr><td>{_esc(f.get('test_start', ''))} – {_esc(f.get('test_end', ''))}</td>"
            f"<td>{_esc(f.get('mae', ''))}</td>"
            f"<td>{_esc(f.get('spearman_pred_hci', ''))}</td></tr>\n"
        )

    sample = daily.dropna(subset=["morning_calm_index", "entry_time_nyc"]).head(8)
    sample_rows = ""
    for _, r in sample.iterrows():
        sample_rows += (
            f"<tr><td>{_esc(r['entry_date'])}</td>"
            f"<td>{_esc(round(r['morning_calm_index'], 3))}</td>"
            f"<td>{_esc(r['entry_time_nyc'])}</td>"
            f"<td>{_esc(int(r.get('minutes_earlier_than_base', 0)))}</td></tr>\n"
        )

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Phase 3 — Continuous calm index</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 960px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
    th {{ background: #f4f4f4; }}
    .pass {{ color: #0a0; }} .fail {{ color: #c00; }}
  </style>
</head>
<body>
  <h1>Phase 3 — Continuous calm index &amp; entry schedule</h1>
  <p>Morning Calm Index (MCI) and Hold Calm Index (HCI) on [0, 1]. Higher = calmer.
     Entry time slides from 16:00 NYC (active) toward 12:00 NYC (calm).</p>

  <h2>Verification summary</h2>
  <ul>
    <li>Gates passed: <span class="{'pass' if result.get('gates_passed') else 'fail'}">
      {_esc(result.get('gates_passed'))}</span></li>
    <li>Spearman MCI→HCI: {_esc(pred.get('spearman_rho', ''))} (p={_esc(pred.get('spearman_p', ''))})</li>
    <li>Permutation p: {_esc(perm.get('p_value', ''))}</li>
    <li>OOS mean Spearman (pred→HCI): {_esc(oos.get('mean_oos_spearman_pred', ''))}</li>
    <li>OOS mean MAE: {_esc(oos.get('mean_oos_mae', ''))}</li>
    <li>Entry monotone (higher MCI → earlier): {_esc(mono.get('entry_monotone_decreasing', ''))}</li>
    <li>MCI vs hold range ρ: {_esc(mono.get('spearman_mci_vs_hold_range', ''))}</li>
  </ul>

  <h2>Calibration (MCI decile → mean HCI)</h2>
  <table>
    <tr><th>MCI mean</th><th>HCI mean</th><th>n</th></tr>
    {cal_rows}
  </table>

  <h2>Walk-forward folds</h2>
  <table>
    <tr><th>Test window</th><th>MAE</th><th>ρ(pred, HCI)</th></tr>
    {fold_rows}
  </table>

  <h2>Sample entry schedule</h2>
  <table>
    <tr><th>Date</th><th>MCI</th><th>Entry NYC</th><th>Min earlier than 16:00</th></tr>
    {sample_rows}
  </table>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path
