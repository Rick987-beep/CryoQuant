"""CDX NA IG stress paper — regime volatility & Granger significance charts."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from scripts.chart_utils import set_style, PALETTE, ax_clean
import matplotlib.pyplot as plt

OUT = ROOT / "assets"
OUT.mkdir(parents=True, exist_ok=True)

set_style()

# --- Panel 1: regime sigma ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

regimes = ['Low-Stress', 'Moderate-Stress', 'High-Stress']
sigma = [2.22, 2.99, 7.61]
share = [63.1, 29.4, 7.5]
colors = [PALETTE['green'], PALETTE['tan'], PALETTE['red']]

ax = axes[0]
bars = ax.bar(regimes, sigma, color=colors, width=0.55, zorder=3)
for b, v in zip(bars, sigma):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.2, f'{v:.2f}%', ha='center', va='bottom', fontsize=9, fontweight='600')
ax.set_ylabel('σ of 3-day CDX % change')
ax.set_title('Velocity Volatility by Regime')
ax_clean(ax)

ax = axes[1]
bars = ax.bar(regimes, share, color=colors, width=0.55, zorder=3)
for b, v in zip(bars, share):
    ax.text(b.get_x() + b.get_width() / 2, v + 1.2, f'{v:.1f}%', ha='center', va='bottom', fontsize=9, fontweight='600')
ax.set_ylabel('Share of sample days')
ax.set_title('Regime Frequency (2011–2026)')
ax_clean(ax)

fig.suptitle('CDX NA IG: Model-Defined Stress Regimes', fontsize=13, fontweight='bold', y=1.02)
fig.tight_layout()
fig.savefig(OUT / 'cdx_regimes.png', dpi=150, bbox_inches='tight', facecolor=PALETTE['bg'])
plt.close()

# --- Panel 2: Granger F-stats 3-day % spec ---
fig, ax = plt.subplots(figsize=(12, 5.5))
x = range(len(regimes))
w = 0.35
cdx_f = [2.13, 5.19, 4.99]
ndq_f = [142.4, 96.9, 11.7]

b1 = ax.bar([i - w/2 for i in x], cdx_f, w, label='CDX → NASDAQ', color=PALETTE['navy'], zorder=3)
b2 = ax.bar([i + w/2 for i in x], ndq_f, w, label='NASDAQ → CDX', color=PALETTE['blue_grey'], zorder=3)
ax.axhline(3.0, color=PALETTE['red'], ls='--', lw=0.9, alpha=0.7, label='Approx. 5% sig. (F≈3)')
ax.set_xticks(list(x))
ax.set_xticklabels(regimes)
ax.set_ylabel('Granger F-statistic')
ax.set_title('Regime-Conditional Granger Causality (3-day % change spec)')
ax.legend(loc='upper right', frameon=False)
ax_clean(ax)
fig.tight_layout()
fig.savefig(OUT / 'cdx_granger_regimes.png', dpi=150, bbox_inches='tight', facecolor=PALETTE['bg'])
plt.close()

# --- Panel 3: event study scatter ---
events = [
    ('2012 EU', 31, -10.5), ('2015 China', 24, -12.9), ('2016 Oil', 41, -16.5),
    ('2018 Q4', 37, -18.2), ('2020 COVID', 203, -30.1), ('2022 Ukraine', 29, -12.7),
    ('2022 Rates', 17, -17.9), ('2023 SVB', 24, -8.0), ('2024 Yen', 26, -13.1),
    ('2025 Tariff', 46, -17.7), ('2026 ME', 36, -12.8),
]
cdx_pct = [e[1] for e in events]
dd = [e[2] for e in events]

fig, ax = plt.subplots(figsize=(12, 5.5))
ax.scatter(cdx_pct, dd, s=90, color=PALETTE['red'], edgecolors=PALETTE['navy'], linewidths=0.8, zorder=3)
for name, x, y in events:
    offset = (8, 4) if name != '2020 COVID' else (12, -8)
    ax.annotate(name, (x, y), textcoords='offset points', xytext=offset, fontsize=8, color=PALETTE['grey'])
# trend line (visual only)
import numpy as np
z = np.polyfit(cdx_pct, dd, 1)
xs = np.linspace(min(cdx_pct), max(cdx_pct), 50)
ax.plot(xs, np.poly1d(z)(xs), color=PALETTE['navy'], lw=1.2, alpha=0.6, ls='--')
ax.set_xlabel('CDX peak move (% 3-day velocity proxy)')
ax.set_ylabel('NASDAQ peak→trough drawdown (%)')
ax.set_title('CDX Move Magnitude vs Equity Drawdown Depth (11 events, paper r = −0.85)')
ax_clean(ax)
fig.tight_layout()
fig.savefig(OUT / 'cdx_drawdown_scatter.png', dpi=150, bbox_inches='tight', facecolor=PALETTE['bg'])
plt.close()

# --- Panel 4: tightening signal returns ---
fig, ax = plt.subplots(figsize=(12, 5.5))
labels = ['Single\n(61 obs)', 'Confirmed\n(359 obs)', 'OOS Confirmed\n(61 obs, 2023–26)']
means = [0.72, 2.43, 5.01]
hit = [64, 75, 85]
colors_bar = [PALETTE['blue_grey'], PALETTE['green'], PALETTE['brown']]
bars = ax.bar(labels, means, color=colors_bar, width=0.5, zorder=3)
for b, m, h in zip(bars, means, hit):
    ax.text(b.get_x() + b.get_width() / 2, m + 0.12, f'+{m:.2f}%', ha='center', va='bottom', fontsize=9, fontweight='600')
    ax.text(b.get_x() + b.get_width() / 2, 0.15, f'P(up)={h}%', ha='center', va='bottom', fontsize=7.5, color='#999')
ax.set_ylabel('Mean NASDAQ return, 20 trading days after signal')
ax.set_title('Confirmed CDX Tightening → Forward NASDAQ Recovery')
ax_clean(ax)
fig.tight_layout()
fig.savefig(OUT / 'cdx_recovery_signal.png', dpi=150, bbox_inches='tight', facecolor=PALETTE['bg'])
plt.close()

print('Charts written to', OUT)
