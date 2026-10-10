"""Study-local futures / equity specs (not promoted to cryoquant yet)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BondFutureSpec:
    """Eurex fixed-income future (price-quoted, physically delivered)."""

    code: str
    venue: str = "eurex"
    notional_eur: float = 100_000.0
    tick_size: float = 0.01
    tick_eur: float = 10.0  # €10 per 0.01 price point

    @property
    def multiplier(self) -> float:
        """Euro P&L per 1.00 price point (= 100 ticks)."""
        return self.tick_eur / self.tick_size  # 1000


@dataclass(frozen=True)
class IndexFutureSpec:
    """CAC 40 future (FCE) / mini (MFC) — used for sizing notes only in Phase 2."""

    code: str
    venue: str = "euronext"
    eur_per_point: float = 10.0


FOAT = BondFutureSpec("FOAT")
FGBL = BondFutureSpec("FGBL")
FCE = IndexFutureSpec("FCE", eur_per_point=10.0)
MFC = IndexFutureSpec("MFC", eur_per_point=1.0)

BOND_FUTURES = {"FOAT": FOAT, "FGBL": FGBL}
