"""P0#13, #15 — pricing_profile + robust hotdeal_score.

db-FINAL §2-4. label은 전역 5단계 고정, profile 가중치만 조정 가능.
산식은 skewed 분포 대응을 위해 band_floor와 분위수 분모 clamp를 사용한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class ScoreLabel(str, Enum):
    """전역 5단계 라벨 — 카테고리별 임계 분기 금지(§S-2.2)."""

    OVERPRICED = "비쌈"        # 0–29
    NORMAL = "평범"             # 30–49
    DECENT = "살만함"          # 50–69
    HOTDEAL = "핫딜"            # 70–89
    LEGENDARY = "역대급"        # 90–100


# 임계는 전역 고정. profile별로 흔들지 않는다 (§S-2.2).
LABEL_THRESHOLDS: tuple[tuple[int, ScoreLabel], ...] = (
    (90, ScoreLabel.LEGENDARY),
    (70, ScoreLabel.HOTDEAL),
    (50, ScoreLabel.DECENT),
    (30, ScoreLabel.NORMAL),
    (0, ScoreLabel.OVERPRICED),
)


def label_for(score: int) -> ScoreLabel:
    for threshold, label in LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return ScoreLabel.OVERPRICED


class PricingProfile(BaseModel):
    """카테고리에 붙는 가중치 프로파일."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    weight_market_quantile: float = Field(ge=0.0, le=1.0)
    weight_wholesale: float = Field(ge=0.0, le=1.0)
    weight_event: float = Field(ge=0.0, le=1.0)
    weight_sale_cycle: float = Field(ge=0.0, le=1.0, default=0.0)
    sample_min_required: int = Field(ge=1, default=5)
    band_floor_pct: float = Field(ge=0.0, le=1.0, default=0.05)
    version_label: str = "v1"
    updated_by: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PricingProfileChangeLog(BaseModel):
    """A/B는 P2지만 변경 이력은 P0부터 보존 (§S-3 Q3)."""

    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    profile_id: str
    before_json: dict
    after_json: dict
    changed_by: str
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note: str = ""


# §S-3 Q3 — 시드 5개. weight는 카테고리 변동성 사전 지식 기반.
DEFAULT_PROFILES: dict[str, PricingProfile] = {
    "fresh": PricingProfile(
        id="fresh",
        name="신선식품",
        description="채소/과일/정육/수산 — wholesale anchor 비중↑, 표본 적어 sample penalty 강함.",
        weight_market_quantile=0.5,
        weight_wholesale=0.4,
        weight_event=0.1,
        sample_min_required=5,
        band_floor_pct=0.05,
        version_label="fresh-v1",
    ),
    "processed": PricingProfile(
        id="processed",
        name="가공식품",
        description="공산 식료품 — market_quantile 비중↑, 도매가 신호 약함.",
        weight_market_quantile=0.7,
        weight_wholesale=0.2,
        weight_event=0.1,
        sample_min_required=10,
        band_floor_pct=0.04,
        version_label="processed-v1",
    ),
    "household": PricingProfile(
        id="household",
        name="생필품",
        description="휴지/세제/생필품 — 카드/멤버십 조건부 가격이 흔함.",
        weight_market_quantile=0.65,
        weight_wholesale=0.2,
        weight_event=0.15,
        sample_min_required=10,
        band_floor_pct=0.04,
        version_label="household-v1",
    ),
    "imported": PricingProfile(
        id="imported",
        name="수입가공",
        description="환율/관세 변동으로 wholesale weight 보수적.",
        weight_market_quantile=0.6,
        weight_wholesale=0.25,
        weight_event=0.15,
        sample_min_required=8,
        band_floor_pct=0.05,
        version_label="imported-v1",
    ),
    "etc": PricingProfile(
        id="etc",
        name="기타",
        description="분류 미확정 기본값. 후순위 분류 후 교체.",
        weight_market_quantile=0.7,
        weight_wholesale=0.15,
        weight_event=0.15,
        sample_min_required=10,
        band_floor_pct=0.05,
        version_label="etc-v1",
    ),
}


class HotdealScoreInputs(BaseModel):
    """산식 입력. (§2-4 robust 산식 그대로)"""

    model_config = ConfigDict(extra="forbid")

    current_price: float = Field(gt=0)
    p10: float = Field(gt=0)
    p50: float = Field(gt=0)
    sample_n: int = Field(ge=0)
    wholesale_anchor: Optional[float] = None
    wholesale_is_stale: bool = False
    conversion_factor: float = Field(default=1.0, gt=0)
    effective_price_type: str = "base"   # base|sale|coupon|membership|card|bundle
    has_event: bool = False


class HotdealScore(BaseModel):
    """산식 출력. label/confidence/profile_version chip을 함께 노출(§2-4)."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=100)
    label: ScoreLabel
    score_confidence: float = Field(ge=0.0, le=1.0)
    profile_version: str
    reasons: list[dict] = Field(default_factory=list)


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _sample_confidence(n: int) -> float:
    # 곱 페널티. 표본이 적을수록 score를 적극적으로 끌어내린다(§2-4).
    if n < 5:
        return 0.3
    if n < 15:
        return 0.6
    if n < 50:
        return 0.85
    return 1.0


def _condition_penalty(eff_type: str) -> float:
    # 조건부 가격은 일반 사용자에게 즉시 적용 안 됨 → 감점.
    return {
        "base": 1.0,
        "sale": 0.95,
        "coupon": 0.7,
        "membership": 0.7,
        "card": 0.7,
        "bundle": 0.6,
    }.get(eff_type, 0.9)


def compute_hotdeal_score(
    inputs: HotdealScoreInputs,
    profile: PricingProfile,
) -> HotdealScore:
    """robust 산식. (§2-4)

    band_floor로 분모 0 방지, p_position_robust는 0~1.2까지 허용해
    역대급(P10 아래) 케이스에 보너스를 남긴다.
    """
    p50, p10 = inputs.p50, inputs.p10
    band_floor = max(p50 * profile.band_floor_pct, 100.0)
    denom = max(p50 - p10, band_floor)
    p_position_robust = _clamp((p50 - inputs.current_price) / denom, 0.0, 1.2)

    if inputs.wholesale_anchor is not None and not inputs.wholesale_is_stale:
        anchor = inputs.wholesale_anchor * inputs.conversion_factor
        # anchor * 1.15 = 정상 소매 마진 가정선. 그 아래로 내려가면 도매 대비 핫.
        w_denom = max(anchor * 0.15, 1.0)
        w_against = _clamp((anchor * 1.15 - inputs.current_price) / w_denom, 0.0, 1.0)
    else:
        w_against = 0.5   # 도매 끊김 → 중립 (§2-5 fallback, 기능 OFF 아님)

    sample_conf = _sample_confidence(inputs.sample_n)
    cond_pen = _condition_penalty(inputs.effective_price_type)
    event_bonus = 0.1 if inputs.has_event else 0.0

    raw = (
        profile.weight_market_quantile * p_position_robust
        + profile.weight_wholesale * w_against
        + profile.weight_event * event_bonus
    )
    raw *= sample_conf * cond_pen
    final = round(_clamp(raw, 0.0, 1.0) * 100)

    # score_confidence: 표본·도매 신선도·산식 입력 완전성의 곱.
    conf = sample_conf
    if inputs.wholesale_anchor is None or inputs.wholesale_is_stale:
        conf *= 0.8
    if inputs.effective_price_type != "base":
        conf *= 0.9
    score_confidence = round(_clamp(conf, 0.0, 1.0), 3)

    reasons = [
        {"key": "vs_p50", "label": f"P50 대비 {round((p50 - inputs.current_price) / p50 * 100)}%",
         "delta": round(p_position_robust, 3)},
        {"key": "vs_wholesale",
         "label": "도매가 끊김" if inputs.wholesale_is_stale or inputs.wholesale_anchor is None
                 else f"도매가 대비 {round((1 - inputs.current_price / (inputs.wholesale_anchor * inputs.conversion_factor)) * 100)}%",
         "delta": round(w_against, 3)},
        {"key": "sample", "label": f"표본 n={inputs.sample_n}", "delta": round(sample_conf, 3)},
        {"key": "condition", "label": f"{inputs.effective_price_type}",
         "delta": round(cond_pen, 3)},
    ]
    if event_bonus > 0:
        reasons.append({"key": "event", "label": "이벤트 보너스", "delta": event_bonus})

    return HotdealScore(
        score=final,
        label=label_for(final),
        score_confidence=score_confidence,
        profile_version=profile.version_label,
        reasons=reasons,
    )
