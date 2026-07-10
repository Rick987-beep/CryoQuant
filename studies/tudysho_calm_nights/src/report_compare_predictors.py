"""Side-by-side HTML report: US morning vs London+US predictors."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _e(v: Any) -> str:
    return html.escape(str(v))


def _fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def render_compare_report(rows: list[dict], out_path: Path) -> Path:
    by_var = {r["variant"]: r for r in rows}
    us = by_var.get("us_morning", {})
    lon = by_var.get("london_us", {})
    p0_us = us.get("phase0", {})
    p0_lon = lon.get("phase0", {})
    p3_us = us.get("phase3", {})
    p3_lon = lon.get("phase3", {})

    def winner(us_val, lon_val, higher_better=True):
        if us_val is None or lon_val is None:
            return "—"
        if higher_better:
            return "London+US" if lon_val > us_val else ("US morning" if us_val > lon_val else "Tie")
        return "London+US" if lon_val < us_val else ("US morning" if us_val < lon_val else "Tie")

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Predictor comparison — US morning vs London+US</title>
  <style>
    body {{ font-family: Georgia, serif; line-height: 1.6; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
    h1 {{ font-family: system-ui, sans-serif; color: #1e4d7b; font-size: 1.6rem; }}
    h2 {{ font-family: system-ui, sans-serif; color: #1e4d7b; font-size: 1.15rem; margin-top: 2rem; }}
    table {{ width: 100%; border-collapse: collapse; font-family: system-ui, sans-serif; font-size: 0.9rem; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; }}
    th {{ background: #f0f4f8; }}
    .verdict {{ background: #f0f4f8; border-left: 4px solid #1e4d7b; padding: 1rem 1.25rem; margin: 1.5rem 0; }}
    p {{ margin: 0 0 1rem; }}
  </style>
</head>
<body>
  <h1>Predictor comparison</h1>
  <p><strong>US morning</strong> (09:30–12:00 NYC) vs <strong>London+US</strong> (07:00 UTC–12:00 NYC).
  Same hold window, same 12:00–16:00 NYC entry slide, same 245-day analysis window.</p>

  <h2>Study A — Binary lift (Phase 0)</h2>
  <table>
    <tr><th>Metric</th><th>US morning</th><th>London+US</th><th>Stronger</th></tr>
    <tr><td>Predictor label</td><td>{_e(p0_us.get('predictor_label',''))}</td><td>{_e(p0_lon.get('predictor_label',''))}</td><td>—</td></tr>
    <tr><td>Primary lift</td><td>{_fmt(p0_us.get('primary_lift'))}</td><td>{_fmt(p0_lon.get('primary_lift'))}</td><td>{winner(p0_us.get('primary_lift'), p0_lon.get('primary_lift'))}</td></tr>
    <tr><td>Lift gate passed</td><td>{_e(p0_us.get('primary_lift_passed'))}</td><td>{_e(p0_lon.get('primary_lift_passed'))}</td><td>—</td></tr>
    <tr><td>Quiet days (tertile)</td><td>{_e(p0_us.get('n_predictor_quiet'))}</td><td>{_e(p0_lon.get('n_predictor_quiet'))}</td><td>—</td></tr>
    <tr><td>False-calm rate %</td><td>{_fmt(p0_us.get('false_calm_rate_pct'), 1)}</td><td>{_fmt(p0_lon.get('false_calm_rate_pct'), 1)}</td><td>{winner(p0_us.get('false_calm_rate_pct'), p0_lon.get('false_calm_rate_pct'), higher_better=False)}</td></tr>
    <tr><td>Contract reduction %</td><td>{_fmt(p0_us.get('contract_reduction_pct'), 1)}</td><td>{_fmt(p0_lon.get('contract_reduction_pct'), 1)}</td><td>{winner(p0_us.get('contract_reduction_pct'), p0_lon.get('contract_reduction_pct'))}</td></tr>
    <tr><td>All Phase 0 gates</td><td>{_e(p0_us.get('phase0_all_gates_passed'))}</td><td>{_e(p0_lon.get('phase0_all_gates_passed'))}</td><td>—</td></tr>
  </table>

  <h2>Study B — Continuous index (Phase 3)</h2>
  <table>
    <tr><th>Metric</th><th>US morning</th><th>London+US</th><th>Stronger</th></tr>
    <tr><td>Spearman MCI → HCI</td><td>{_fmt(p3_us.get('spearman_mci_hci'))}</td><td>{_fmt(p3_lon.get('spearman_mci_hci'))}</td><td>{winner(p3_us.get('spearman_mci_hci'), p3_lon.get('spearman_mci_hci'))}</td></tr>
    <tr><td>OOS Spearman (walk-forward)</td><td>{_fmt(p3_us.get('oos_spearman_pred'))}</td><td>{_fmt(p3_lon.get('oos_spearman_pred'))}</td><td>{winner(p3_us.get('oos_spearman_pred'), p3_lon.get('oos_spearman_pred'))}</td></tr>
    <tr><td>OOS MAE (HCI)</td><td>{_fmt(p3_us.get('oos_mae'))}</td><td>{_fmt(p3_lon.get('oos_mae'))}</td><td>{winner(p3_us.get('oos_mae'), p3_lon.get('oos_mae'), higher_better=False)}</td></tr>
    <tr><td>Permutation p</td><td>{_fmt(p3_us.get('permutation_p'), 4)}</td><td>{_fmt(p3_lon.get('permutation_p'), 4)}</td><td>—</td></tr>
    <tr><td>Phase 3 gates passed</td><td>{_e(p3_us.get('gates_passed'))}</td><td>{_e(p3_lon.get('gates_passed'))}</td><td>—</td></tr>
  </table>

  <div class="verdict">
    <strong>How to read this:</strong> Prefer the predictor with higher lift and Spearman (Study A and B),
    and lower false-calm rate if safety is tied. If London+US wins on prediction but not on safety,
    use it only for entry <em>timing</em> with conservative strikes. Full narrative reports:
    <code>reports/us_morning/</code> and <code>reports/london_us/</code> (re-run Study A/B HTML per variant as needed).
  </div>

  <p>Artifacts: <code>reports/us_morning/</code>, <code>reports/london_us/</code>,
  <code>data/us_morning/</code>, <code>data/london_us/</code></p>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path
