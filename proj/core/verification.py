"""
커뮤니티 자동 검증 로직 — 바이럴 필터 + 허위 가격 감지.

유저 제보 가격을 DB 평균과 비교하여 신뢰도 판정.
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class VerifyStatus(str, Enum):
    VERIFIED = "verified"         # 정상 — 평균 범위 내
    GREAT_DEAL = "great_deal"     # 진짜 핫딜 — 평균보다 크게 저렴 (합리적 범위)
    SUSPICIOUS_LOW = "sus_low"    # 허위 의심 — 너무 싸서 의심
    SUSPICIOUS_HIGH = "sus_high"  # 바이럴 의심 — 평균보다 비쌈
    UNMATCHED = "unmatched"       # 매칭 실패 — DB에 해당 품목 없음


class VerifyResult(BaseModel):
    """검증 결과."""
    status: VerifyStatus
    label: str                # "✅ 검증됨 — 평균 대비 -23%"
    emoji: str
    price_vs_avg_pct: float   # -23.0 (%)
    avg_price: float
    user_price: float
    warning_msg: str = ""
    can_post: bool = True     # False면 등록 차단


def verify_community_price(
    user_price: float,
    avg_price: float,
    product_name: str = "",
) -> VerifyResult:
    """
    유저 제보 가격 검증.

    규칙:
    1. avg의 20% 미만 → 허위 의심 (등록 경고)
    2. avg의 20~70% → 진짜 핫딜 
    3. avg의 70~120% → 정상 범위
    4. avg의 120% 초과 → 바이럴 의심
    """
    if avg_price <= 0:
        return VerifyResult(
            status=VerifyStatus.UNMATCHED,
            label="품목 매칭 필요",
            emoji="❓",
            price_vs_avg_pct=0,
            avg_price=0,
            user_price=user_price,
            warning_msg=f"'{product_name}' 품목을 DB에서 찾을 수 없습니다.",
        )

    ratio = user_price / avg_price
    pct = round((ratio - 1) * 100, 1)

    # 너무 싸면: 허위 의심
    if ratio < 0.20:
        return VerifyResult(
            status=VerifyStatus.SUSPICIOUS_LOW,
            label=f"⚠️ 허위 가격 의심 — 평균 대비 {pct}%",
            emoji="⚠️",
            price_vs_avg_pct=pct,
            avg_price=avg_price,
            user_price=user_price,
            warning_msg=f"입력 가격 {user_price:,.0f}원이 평균({avg_price:,.0f}원)의 {ratio*100:.0f}%입니다. 실제 결제 금액이 맞는지 확인해주세요.",
            can_post=False,
        )

    # 크게 저렴하지만 합리적 범위: 진짜 핫딜
    if ratio < 0.70:
        return VerifyResult(
            status=VerifyStatus.GREAT_DEAL,
            label=f"🔥 진짜 핫딜! — 평균 대비 {pct}%",
            emoji="🔥",
            price_vs_avg_pct=pct,
            avg_price=avg_price,
            user_price=user_price,
        )

    # 정상 범위
    if ratio <= 1.20:
        return VerifyResult(
            status=VerifyStatus.VERIFIED,
            label=f"✅ 검증됨 — 평균 대비 {pct}%",
            emoji="✅",
            price_vs_avg_pct=pct,
            avg_price=avg_price,
            user_price=user_price,
        )

    # 비쌈: 바이럴 의심
    return VerifyResult(
        status=VerifyStatus.SUSPICIOUS_HIGH,
        label=f"🚨 바이럴 의심 — 평균 대비 +{pct}%",
        emoji="🚨",
        price_vs_avg_pct=pct,
        avg_price=avg_price,
        user_price=user_price,
        warning_msg=f"입력 가격 {user_price:,.0f}원이 평균({avg_price:,.0f}원)보다 {pct}% 비쌉니다. 광고성 게시물은 제한됩니다.",
        can_post=True,  # 경고만, 차단은 안 함
    )
