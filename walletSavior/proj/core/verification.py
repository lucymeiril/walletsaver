"""
커뮤니티 가격 검증 — 가짜 핫딜과 바이럴 마케팅을 자동 차단한다.

왜 존재하는가:
    유저 제보 기반 커뮤니티에서는 (1) 관심 끌기용 허위 가격("삼겹살 100원에 샀어요!"),
    (2) 광고성 바이럴("이 마트가 최고!" + 뻥튀기 가격)이 반드시 발생한다.
    DB에 축적된 평균가와 자동 비교하여 비정상 가격을 걸러내야
    다른 유저에게 잘못된 정보가 전파되는 것을 막을 수 있다.
어디서 쓰이는가:
    API의 유저 제보 엔드포인트 → verify_community_price() → 결과에 따라
    등록 허용/경고/차단 결정 → 대시보드에 검증 배지 표시.
"""

from __future__ import annotations
from enum import Enum
from pydantic import BaseModel


class VerifyStatus(str, Enum):
    """
    검증 결과 상태 — 각 임계값의 근거:

    SUSPICIOUS_LOW (< 20%): 평균의 1/5 미만은 물리적으로 불가능한 가격.
        예: 삼겹살 평균 19,000원인데 3,000원 → 오타이거나 허위 제보.
    GREAT_DEAL (20~70%): 대형마트 특가전 수준 — 있을 수 있지만 눈에 띄는 할인.
    VERIFIED (70~120%): 일상적 가격 변동 범위 — 정상.
    SUSPICIOUS_HIGH (> 120%): 바이럴 마케팅이 의심되는 수준 — 경고만 표시, 차단은 안 함.
    """
    VERIFIED = "verified"         # 정상 — 평균 범위 내
    GREAT_DEAL = "great_deal"     # 진짜 핫딜 — 평균보다 크게 저렴 (합리적 범위)
    SUSPICIOUS_LOW = "sus_low"    # 허위 의심 — 너무 싸서 의심 (등록 차단)
    SUSPICIOUS_HIGH = "sus_high"  # 바이럴 의심 — 평균보다 비쌈 (경고만)
    UNMATCHED = "unmatched"       # 매칭 실패 — DB에 해당 품목 없음


class VerifyResult(BaseModel):
    """검증 결과 — API 응답으로 직접 반환되며, can_post=False면 게시 차단."""
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
    유저 제보 가격을 DB 평균과 비교하여 신뢰도를 자동 판정한다.

    왜 자동인가: 관리자가 매건 수동 검증하는 건 스케일이 안 된다.
    임계값(20/70/120%)은 한국 식료품 시장의 할인 패턴에서 도출:
        - 대형마트 최대 할인이 보통 50~60% → 70% 이하는 "핫딜"
        - 20% 미만은 물리적으로 불가능 → "허위"
        - 20%+ 비쌈은 프리미엄 제품이 아닌 한 비정상 → "바이럴 의심"
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

    # 너무 싸면: 허위 의심 — 평균의 20% 미만은 오타이거나 장난
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

    # 크게 저렴하지만 합리적 범위: 대형마트 특가전 수준의 진짜 핫딜
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

    # 비쌈: 광고성 바이럴 의심 — 차단까지는 안 하고 경고만 (프리미엄 제품일 수 있으므로)
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
