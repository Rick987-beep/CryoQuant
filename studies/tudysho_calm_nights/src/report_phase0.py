"""Phase 0 HTML report."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any


def _esc(val: Any) -> str:
    return html.escape(str(val))


def render_phase0_report(
    contingency: dict[str, Any],
    counterfactual_summary: dict[str, Any],
    *,
    out_path: Path,
) -> Path:
    """Write session_extrusion_report.html."""
    spearman = contingency.get("spearman", {})
    lifts = contingency.get("lifts", {})
    false_calm = contingency.get("false_calm", {})
    primary = contingency.get("primary_gate", {})

    spearman_rows = ""
    for key, vals in spearman.items():
        spearman_rows += (
            f"<tr><td>{_esc(key)}</td>"
            f"<td>{_esc(vals.get('rho', ''))}</td>"
            f"<td>{_esc(vals.get('p_value', ''))}</td>"
            f"<td>{_esc(vals.get('n', ''))}</td></tr>\n"
        )

    lift_rows = ""
    for col, vals in lifts.items():
        ci = vals.get("bootstrap_ci", {})
        lift_rows += (
            f"<tr><td>{_esc(col)}</td>"
            f"<td>{_esc(vals.get('lift', ''))}</td>"
            f"<td>{_esc(vals.get('fisher_p', ''))}</td>"
            f"<td>{_esc(vals.get('passed', ''))}</td>"
            f"<td>{_esc(ci.get('lift_lower', ''))} – {_esc(ci.get('lift_upper', ''))}</td></tr>\n"
        )

    oct_tail = ""
    for ev in false_calm.get("events", []):
        if "2025-10" in str(ev.get("entry_date", "")):
            oct_tail = (
                f"<p><strong>Oct-2025 tail day:</strong> "
                f"{_esc(ev)}</p>"
            )
            break

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Tudysho calm nights — Phase 0</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 960px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
    th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
    th {{ background: #f4f4f4; }}
    .pass {{ color: #0a0; }}
    .fail {{ color: #c00; }}
    h2 {{ margin-top: 2rem; }}
  </style>
</head>
<body>
  <h1>Phase 0 — Session extrusion</h1>
  <p>Slot A (Mon–Thu): quiet US morning → quiet overnight hold hypothesis.</p>

  <h2>Summary</h2>
  <ul>
    <li>Days: {_esc(contingency.get('n_days', ''))}</li>
    <li>Morning quiet (tertile): {_esc(contingency.get('n_morning_quiet', ''))}</li>
    <li>Primary lift gate: <span class="{'pass' if primary.get('passed') else 'fail'}">
      {_esc(primary.get('passed', False))}</span>
      (lift={_esc(primary.get('lift', ''))}, p={_esc(primary.get('fisher_p', ''))})</li>
    <li>False calm rate: {_esc(false_calm.get('rate_pct', ''))}% 
      (pass &lt; {_esc(false_calm.get('threshold_pct', ''))}%: 
      <span class="{'pass' if false_calm.get('passed') else 'fail'}">
      {_esc(false_calm.get('passed', False))}</span>)</li>
    <li>Contract reduction (agg vs base): {_esc(counterfactual_summary.get('contract_reduction_pct', ''))}%
      (pass ≥40%: <span class="{'pass' if counterfactual_summary.get('contract_reduction_passed') else 'fail'}">
      {_esc(counterfactual_summary.get('contract_reduction_passed', False))}</span>)</li>
    <li>Extrusion safe (aggressive): {_esc(counterfactual_summary.get('extrusion_safe_pct_aggressive', ''))}%
      (pass ≥97%: <span class="{'pass' if counterfactual_summary.get('extrusion_safe_passed') else 'fail'}">
      {_esc(counterfactual_summary.get('extrusion_safe_passed', False))}</span>)</li>
  </ul>
  <p><em>{_esc(counterfactual_summary.get('chain_snapshot_note', ''))}</em></p>

  {oct_tail}

  <h2>Spearman correlations</h2>
  <table>
    <tr><th>Pair</th><th>ρ</th><th>p</th><th>n</th></tr>
    {spearman_rows}
  </table>

  <h2>Contingency lift</h2>
  <table>
    <tr><th>Hold window</th><th>Lift</th><th>Fisher p</th><th>Pass</th><th>Bootstrap 95% CI</th></tr>
    {lift_rows}
  </table>

  <h2>Counterfactual contracts</h2>
  <ul>
    <li>Median contracts aggressive: {_esc(counterfactual_summary.get('median_contracts_aggressive', ''))}</li>
    <li>Median contracts base: {_esc(counterfactual_summary.get('median_contracts_base', ''))}</li>
    <li>Grid cells resolved: {_esc(counterfactual_summary.get('n_cells', ''))}</li>
  </ul>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    return out_path
