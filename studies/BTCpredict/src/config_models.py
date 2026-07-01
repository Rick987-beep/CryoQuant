"""Pydantic models for studies/BTCpredict/config.yaml."""
from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HorizonId(StrEnum):
    H1 = "T+1d"
    H5 = "T+5d"
    H21 = "T+10-21d"


class AssetId(StrEnum):
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"


class ModelHeadId(StrEnum):
    DIRECTIONAL = "directional"
    DISTRIBUTIONAL = "distributional"
    REALIZED_VOL = "realized_vol"
    LOG_RETURN_BENCH = "log_return_bench"


class OptionStructure(StrEnum):
    NAKED = "naked"
    CREDIT_SPREAD = "credit_spread"
    STRANGLE = "strangle"


# Expected horizon_bars per KICKOFF / SPEC (T+10-21d allows 10–21).
_HORIZON_BARS: dict[HorizonId, int | tuple[int, int]] = {
    HorizonId.H1: 1,
    HorizonId.H5: 5,
    HorizonId.H21: (10, 21),
}


class HorizonSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: HorizonId
    horizon_bars: int = Field(ge=1)
    dte_targets: list[int] = Field(min_length=1)

    @field_validator("dte_targets")
    @classmethod
    def _positive_dte(cls, v: list[int]) -> list[int]:
        if any(d <= 0 for d in v):
            raise ValueError("dte_targets must be positive integers")
        return v

    @model_validator(mode="after")
    def _horizon_bars_match_id(self) -> Self:
        expected = _HORIZON_BARS[self.id]
        if isinstance(expected, int):
            if self.horizon_bars != expected:
                raise ValueError(
                    f"horizon {self.id.value} requires horizon_bars={expected}, "
                    f"got {self.horizon_bars}"
                )
        else:
            lo, hi = expected
            if not lo <= self.horizon_bars <= hi:
                raise ValueError(
                    f"horizon {self.id.value} requires horizon_bars in [{lo}, {hi}], "
                    f"got {self.horizon_bars}"
                )
        return self


class SplitManifest(BaseModel):
    """Written by Phase 0; immutable thereafter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holdout_start: date
    dev_end: date
    dev_start: date
    bar_cadence: str = "1d"
    notes: str = ""

    @model_validator(mode="after")
    def _dates_ordered(self) -> Self:
        if self.dev_start >= self.holdout_start:
            raise ValueError("dev_start must be strictly before holdout_start")
        if self.dev_end != self.holdout_start - timedelta(days=1):
            raise ValueError("dev_end must equal holdout_start - 1 day")
        if self.dev_start >= self.dev_end:
            raise ValueError("dev_start must be before dev_end")
        return self


class SplitsInput(BaseModel):
    """YAML-facing split fields (dev_end computed at load time)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    holdout_start: date
    dev_start: date
    bar_cadence: str = "1d"
    notes: str = ""


class WalkForwardSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    train_window_bars: int = Field(ge=1)
    test_window_bars: int = Field(ge=1)
    step_bars: int = Field(ge=1)
    embargo_bars: int = Field(ge=0)


class RiskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cvar_alpha: float = Field(gt=0, lt=1)
    max_cvar_loss_pct: float = Field(gt=0, le=1)
    deflated_sharpe_min: float = 0.0
    pbo_max: float = Field(gt=0, le=1)


class OptionBookSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: str = "deribit"
    underlyings: list[AssetId] = Field(default_factory=lambda: [AssetId.BTC, AssetId.ETH])
    target_deltas: list[float] = Field(default_factory=lambda: [0.10, 0.15, 0.20])
    wing_delta_offsets: list[float] = Field(default_factory=lambda: [0.05, 0.10])
    structures: list[OptionStructure] = Field(
        default_factory=lambda: [OptionStructure.STRANGLE, OptionStructure.CREDIT_SPREAD]
    )
    default_structure: OptionStructure = OptionStructure.CREDIT_SPREAD
    tilt_threshold: float = Field(gt=0, lt=1)
    min_physical_edge: float = Field(ge=0)

    @model_validator(mode="after")
    def _default_in_structures(self) -> Self:
        if self.default_structure not in self.structures:
            raise ValueError("default_structure must appear in structures")
        return self


class LabelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction_threshold_pct: float = Field(gt=0)
    use_vol_scaled_threshold: bool = True
    vol_scale_k: float = Field(gt=0, default=1.0)
    exceedance_deltas: list[float] = Field(min_length=1)
    exceedance_quantile_lookback: int = Field(ge=20, default=252)
    realized_vol_window: int = Field(ge=1)
    vrp_enabled: bool = True


class LGBMParams(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    n_estimators: int = Field(ge=1)
    max_depth: int = Field(ge=1)
    num_leaves: int = Field(ge=2)
    min_child_samples: int = Field(ge=1)
    learning_rate: float = Field(gt=0)
    subsample: float = Field(gt=0, le=1)
    colsample_bytree: float = Field(gt=0, le=1)
    reg_alpha: float = Field(ge=0)
    reg_lambda: float = Field(ge=0)


class Phase4Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    register_signed_off: bool = False
    register_date: date | None = None
    training_register: str = "training.yaml"
    vol_baseline: str = "har_rv"
    hpo_enabled: bool = False
    lgbm_classifier: LGBMParams
    lgbm_regressor: LGBMParams
    lgbm_quantile: LGBMParams


class StudyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    study_id: str
    random_seed: int
    feature_budget_max: int = Field(ge=1)
    data_sources_reviewed: bool = False
    data_sources_review_date: date | None = None
    phase1_complete: bool = False
    phase1_complete_date: date | None = None
    phase2_catalog_reviewed: bool = False
    phase2_catalog_review_date: date | None = None
    phase2_complete: bool = False
    phase2_complete_date: date | None = None
    phase3_complete: bool = False
    phase3_complete_date: date | None = None
    phase4_complete: bool = False
    phase4_complete_date: date | None = None
    phase4_5_complete: bool = False
    phase4_5_complete_date: date | None = None
    phase5_complete: bool = False
    phase5_complete_date: date | None = None
    phase6_complete: bool = False
    phase6_complete_date: date | None = None
    phase7_complete: bool = False
    phase7_complete_date: date | None = None
    splits: SplitManifest
    horizons: list[HorizonSpec] = Field(min_length=1)
    walk_forward: WalkForwardSpec
    risk: RiskSpec
    option_book: OptionBookSpec
    label: LabelSpec
    phase4: Phase4Spec | None = None

    @model_validator(mode="after")
    def _phase2_gate(self) -> Self:
        if self.phase2_complete and self.phase2_complete_date is None:
            raise ValueError("phase2_complete_date required when phase2_complete is true")
        if self.phase2_complete and not self.phase2_catalog_reviewed:
            raise ValueError("phase2_catalog_reviewed must be true when phase2_complete is true")
        if self.phase2_complete and not self.phase1_complete:
            raise ValueError("phase1_complete must be true when phase2_complete is true")
        return self

    @model_validator(mode="after")
    def _phase3_gate(self) -> Self:
        if self.phase3_complete and self.phase3_complete_date is None:
            raise ValueError("phase3_complete_date required when phase3_complete is true")
        if self.phase3_complete and not self.phase2_complete:
            raise ValueError("phase2_complete must be true when phase3_complete is true")
        return self

    @model_validator(mode="after")
    def _phase4_gate(self) -> Self:
        if self.phase4_complete and self.phase4_complete_date is None:
            raise ValueError("phase4_complete_date required when phase4_complete is true")
        if self.phase4_complete and not self.phase3_complete:
            raise ValueError("phase3_complete must be true when phase4_complete is true")
        return self

    @model_validator(mode="after")
    def _phase4_5_gate(self) -> Self:
        if self.phase4_5_complete and self.phase4_5_complete_date is None:
            raise ValueError("phase4_5_complete_date required when phase4_5_complete is true")
        if self.phase4_5_complete and not self.phase4_complete:
            raise ValueError("phase4_complete must be true when phase4_5_complete is true")
        return self

    @model_validator(mode="after")
    def _phase5_gate(self) -> Self:
        if self.phase5_complete and self.phase5_complete_date is None:
            raise ValueError("phase5_complete_date required when phase5_complete is true")
        if self.phase5_complete and not self.phase4_5_complete:
            raise ValueError("phase4_5_complete must be true when phase5_complete is true")
        return self


    @model_validator(mode="after")
    def _phase6_gate(self) -> Self:
        if self.phase6_complete and self.phase6_complete_date is None:
            raise ValueError("phase6_complete_date required when phase6_complete is true")
        if self.phase6_complete and not self.phase5_complete:
            raise ValueError("phase5_complete must be true when phase6_complete is true")
        return self

    @model_validator(mode="after")
    def _phase7_gate(self) -> Self:
        if self.phase7_complete and self.phase7_complete_date is None:
            raise ValueError("phase7_complete_date required when phase7_complete is true")
        if self.phase7_complete and not self.phase6_complete:
            raise ValueError("phase6_complete must be true when phase7_complete is true")
        return self

    @model_validator(mode="after")
    def _splits_vs_today(self) -> Self:
        today = date.today()
        if self.splits.holdout_start >= today:
            raise ValueError(
                f"holdout_start ({self.splits.holdout_start}) must be before today ({today})"
            )
        return self

    @model_validator(mode="after")
    def _data_sources_gate(self) -> Self:
        if self.data_sources_reviewed and self.data_sources_review_date is None:
            raise ValueError("data_sources_review_date required when data_sources_reviewed is true")
        return self

    @model_validator(mode="after")
    def _phase1_gate(self) -> Self:
        if self.phase1_complete and self.phase1_complete_date is None:
            raise ValueError("phase1_complete_date required when phase1_complete is true")
        if self.phase1_complete and not self.data_sources_reviewed:
            raise ValueError("data_sources_reviewed must be true when phase1_complete is true")
        return self

    @model_validator(mode="after")
    def _phase2_catalog_gate(self) -> Self:
        if self.phase2_catalog_reviewed and self.phase2_catalog_review_date is None:
            raise ValueError("phase2_catalog_review_date required when phase2_catalog_reviewed is true")
        if self.phase2_catalog_reviewed and not self.phase1_complete:
            raise ValueError("phase1_complete must be true when phase2_catalog_reviewed is true")
        return self


class _StudyConfigRaw(BaseModel):
    """Parse YAML before computing SplitManifest.dev_end."""

    model_config = ConfigDict(extra="forbid")

    study_id: str
    random_seed: int
    feature_budget_max: int = 100
    data_sources_reviewed: bool = False
    data_sources_review_date: date | None = None
    phase1_complete: bool = False
    phase1_complete_date: date | None = None
    phase2_catalog_reviewed: bool = False
    phase2_catalog_review_date: date | None = None
    phase2_complete: bool = False
    phase2_complete_date: date | None = None
    phase3_complete: bool = False
    phase3_complete_date: date | None = None
    phase4_complete: bool = False
    phase4_complete_date: date | None = None
    phase4_5_complete: bool = False
    phase4_5_complete_date: date | None = None
    phase5_complete: bool = False
    phase5_complete_date: date | None = None
    phase6_complete: bool = False
    phase6_complete_date: date | None = None
    phase7_complete: bool = False
    phase7_complete_date: date | None = None
    splits: SplitsInput
    horizons: list[HorizonSpec]
    walk_forward: WalkForwardSpec
    risk: RiskSpec
    option_book: OptionBookSpec
    label: LabelSpec
    phase4: Phase4Spec | None = None


def build_split_manifest(splits: SplitsInput) -> SplitManifest:
    dev_end = splits.holdout_start - timedelta(days=1)
    return SplitManifest(
        holdout_start=splits.holdout_start,
        dev_end=dev_end,
        dev_start=splits.dev_start,
        bar_cadence=splits.bar_cadence,
        notes=splits.notes,
    )


def load_study_config(path: Path | None = None) -> StudyConfig:
    """Load config.yaml and return a validated StudyConfig."""
    if path is None:
        from src.paths import config_path

        path = config_path()

    with path.open(encoding="utf-8") as f:
        raw_dict = yaml.safe_load(f)

    raw = _StudyConfigRaw.model_validate(raw_dict)
    manifest = build_split_manifest(raw.splits)
    return StudyConfig(
        study_id=raw.study_id,
        random_seed=raw.random_seed,
        feature_budget_max=raw.feature_budget_max,
        data_sources_reviewed=raw.data_sources_reviewed,
        data_sources_review_date=raw.data_sources_review_date,
        phase1_complete=raw.phase1_complete,
        phase1_complete_date=raw.phase1_complete_date,
        phase2_catalog_reviewed=raw.phase2_catalog_reviewed,
        phase2_catalog_review_date=raw.phase2_catalog_review_date,
        phase2_complete=raw.phase2_complete,
        phase2_complete_date=raw.phase2_complete_date,
        phase3_complete=raw.phase3_complete,
        phase3_complete_date=raw.phase3_complete_date,
        phase4_complete=raw.phase4_complete,
        phase4_complete_date=raw.phase4_complete_date,
        phase4_5_complete=raw.phase4_5_complete,
        phase4_5_complete_date=raw.phase4_5_complete_date,
        phase5_complete=raw.phase5_complete,
        phase5_complete_date=raw.phase5_complete_date,
        phase6_complete=raw.phase6_complete,
        phase6_complete_date=raw.phase6_complete_date,
        phase7_complete=raw.phase7_complete,
        phase7_complete_date=raw.phase7_complete_date,
        splits=manifest,
        horizons=raw.horizons,
        walk_forward=raw.walk_forward,
        risk=raw.risk,
        option_book=raw.option_book,
        label=raw.label,
        phase4=raw.phase4,
    )


def write_splits_json(cfg: StudyConfig, out_path: Path) -> Path:
    """Serialize SplitManifest to JSON (idempotent content for same config)."""
    import json

    payload = cfg.splits.model_dump(mode="json")
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path
