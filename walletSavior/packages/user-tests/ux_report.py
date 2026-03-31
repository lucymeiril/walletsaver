"""
UX 피드백 보고서 — WalletSavior (지갑 지키미)

페이지별 UX 점수, 강점/약점, 개선 권고 사항을 종합하여
JSON 및 텍스트 형식의 보고서를 생성합니다.
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import IntEnum


class Priority(IntEnum):
    """개선 우선순위"""
    P0_CRITICAL = 0     # 즉시 수정 필요
    P1_HIGH = 1         # 다음 릴리스에 수정
    P2_MEDIUM = 2       # 계획적으로 개선
    P3_NICE_TO_HAVE = 3  # 여유 시 개선


@dataclass
class Recommendation:
    """개선 권고 사항"""
    id: str
    title: str
    description: str
    priority: Priority
    page: str
    category: str
    effort: str = "중간"  # 낮음, 중간, 높음

    def validate(self) -> bool:
        return bool(self.id and self.title and self.description and self.page and self.category)


@dataclass
class PageAnalysis:
    """페이지별 UX 분석"""
    page: str
    score: int  # 1-10
    strengths: List[str]
    weaknesses: List[str]
    recommendations: List[Recommendation] = field(default_factory=list)

    def validate(self) -> bool:
        if not (1 <= self.score <= 10):
            return False
        if not self.page:
            return False
        if not self.strengths or not self.weaknesses:
            return False
        return True

    def to_dict(self) -> Dict:
        return {
            "page": self.page,
            "score": self.score,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "recommendations": [
                {
                    "id": r.id,
                    "title": r.title,
                    "priority": f"P{r.priority.value}",
                    "category": r.category,
                    "effort": r.effort,
                }
                for r in self.recommendations
            ],
        }


@dataclass
class UXReport:
    """종합 UX 평가 보고서"""
    title: str
    version: str
    evaluator: str
    pages: List[PageAnalysis]
    overall_summary: str = ""

    def validate(self) -> bool:
        if not self.title or not self.version or not self.evaluator:
            return False
        if not self.pages:
            return False
        return all(p.validate() for p in self.pages)

    @property
    def average_score(self) -> float:
        if not self.pages:
            return 0.0
        return round(sum(p.score for p in self.pages) / len(self.pages), 1)

    @property
    def all_recommendations(self) -> List[Recommendation]:
        result = []
        for page in self.pages:
            result.extend(page.recommendations)
        return result

    def get_recommendations_by_priority(self, priority: Priority) -> List[Recommendation]:
        return [r for r in self.all_recommendations if r.priority == priority]

    @property
    def critical_recommendations(self) -> List[Recommendation]:
        return self.get_recommendations_by_priority(Priority.P0_CRITICAL)

    @property
    def high_recommendations(self) -> List[Recommendation]:
        return self.get_recommendations_by_priority(Priority.P1_HIGH)

    def to_json(self, indent: int = 2) -> str:
        """JSON 형식으로 내보내기"""
        data = {
            "title": self.title,
            "version": self.version,
            "evaluator": self.evaluator,
            "average_score": self.average_score,
            "total_recommendations": len(self.all_recommendations),
            "critical_count": len(self.critical_recommendations),
            "high_count": len(self.high_recommendations),
            "pages": [p.to_dict() for p in self.pages],
            "overall_summary": self.overall_summary,
        }
        return json.dumps(data, ensure_ascii=False, indent=indent)

    def to_text(self) -> str:
        """포맷된 텍스트 보고서 생성"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"📊 {self.title}")
        lines.append(f"버전: {self.version} | 평가자: {self.evaluator}")
        lines.append("=" * 60)
        lines.append("")
        lines.append(f"📈 전체 평균 점수: {self.average_score}/10")
        lines.append(f"📋 총 권고 사항: {len(self.all_recommendations)}건")
        lines.append(f"🚨 P0 긴급: {len(self.critical_recommendations)}건")
        lines.append(f"⚠️  P1 높음: {len(self.high_recommendations)}건")
        lines.append("")

        for page in self.pages:
            lines.append("-" * 50)
            lines.append(f"📄 {page.page} (점수: {page.score}/10)")
            lines.append("-" * 50)
            lines.append("  ✅ 강점:")
            for s in page.strengths:
                lines.append(f"    • {s}")
            lines.append("  ❌ 약점:")
            for w in page.weaknesses:
                lines.append(f"    • {w}")
            if page.recommendations:
                lines.append("  💡 권고:")
                for r in page.recommendations:
                    lines.append(f"    [{r.priority.name}] {r.title}")
            lines.append("")

        if self.overall_summary:
            lines.append("=" * 60)
            lines.append("📝 종합 요약")
            lines.append(self.overall_summary)
            lines.append("=" * 60)

        return "\n".join(lines)


# ─── WalletSavior UX 보고서 생성 ─────────────────────────────

def create_walletsavior_ux_report() -> UXReport:
    """WalletSavior 종합 UX 평가 보고서 생성"""
    return UXReport(
        title="WalletSavior (지갑 지키미) UX 평가 보고서",
        version="1.0.0",
        evaluator="UX 평가 프레임워크",
        overall_summary=(
            "WalletSavior는 전반적으로 사용자 중심의 직관적 UI를 제공하고 있습니다. "
            "특히 '고인물 모드'를 통한 초보자/전문가 분리 전략이 돋보입니다. "
            "개선이 필요한 영역은 오류 처리, 접근성, 그리고 모바일 환경에서의 "
            "고급 기능 접근성입니다. P0 항목을 우선 처리하고, "
            "사용자 피드백을 기반으로 지속적으로 개선할 것을 권장합니다."
        ),
        pages=[
            PageAnalysis(
                page="Home (홈)",
                score=8,
                strengths=[
                    "히어로 검색바로 핵심 기능에 즉시 접근 가능",
                    "카테고리 퀵링크로 직관적 탐색 지원",
                    "오늘의 핫딜 섹션이 눈에 잘 띔",
                    "깔끔한 레이아웃으로 정보 과부하 방지",
                ],
                weaknesses=[
                    "첫 방문 사용자를 위한 온보딩 부재",
                    "섹션이 많아 스크롤이 길어질 수 있음",
                    "개인화 추천 기능 미흡",
                ],
                recommendations=[
                    Recommendation(
                        id="HOME-01", title="첫 방문 온보딩 투어 추가",
                        description="처음 방문한 사용자에게 주요 기능을 안내하는 가이드 투어를 제공합니다",
                        priority=Priority.P2_MEDIUM, page="Home",
                        category="온보딩", effort="중간",
                    ),
                    Recommendation(
                        id="HOME-02", title="개인화 추천 섹션 추가",
                        description="사용자의 검색 이력과 관심사 기반 맞춤 핫딜 추천",
                        priority=Priority.P3_NICE_TO_HAVE, page="Home",
                        category="개인화", effort="높음",
                    ),
                ],
            ),
            PageAnalysis(
                page="Hotdeal (핫딜)",
                score=8,
                strengths=[
                    "카테고리/출처 필터로 효율적 탐색",
                    "가격대 뱃지로 가격 범위 직관적 파악",
                    "무한 스크롤로 끊김 없는 탐색",
                    "투표 시스템으로 딜 품질 검증",
                ],
                weaknesses=[
                    "이미 본 딜 표시 기능 부재",
                    "필터 초기화가 직관적이지 않음",
                    "모바일에서 필터 접근 불편",
                ],
                recommendations=[
                    Recommendation(
                        id="HOT-01", title="읽음 표시 기능 추가",
                        description="이미 확인한 딜에 읽음 표시를 하여 새로운 딜을 쉽게 식별",
                        priority=Priority.P2_MEDIUM, page="Hotdeal",
                        category="UX 개선", effort="낮음",
                    ),
                    Recommendation(
                        id="HOT-02", title="모바일 필터 바텀시트 개선",
                        description="모바일에서 필터를 바텀시트 형태로 제공하여 접근성 향상",
                        priority=Priority.P1_HIGH, page="Hotdeal",
                        category="모바일 UX", effort="중간",
                    ),
                ],
            ),
            PageAnalysis(
                page="Price (가격 비교)",
                score=9,
                strengths=[
                    "검색 자동완성으로 빠른 상품 탐색",
                    "마트별 가격 비교 표가 직관적",
                    "고인물 모드로 심층 분석 가능",
                    "가격 추이 차트가 유용",
                ],
                weaknesses=[
                    "360px 모바일에서 가격표 가로 스크롤",
                    "고인물 모드 첫 접근 시 안내 부족",
                    "가격 데이터 갱신 시점 불명확",
                ],
                recommendations=[
                    Recommendation(
                        id="PRC-01", title="모바일 가격표 카드 형식 전환",
                        description="좁은 화면에서 비교 표를 카드 형식으로 전환하여 가로 스크롤 방지",
                        priority=Priority.P1_HIGH, page="Price",
                        category="반응형 디자인", effort="중간",
                    ),
                    Recommendation(
                        id="PRC-02", title="고인물 모드 온보딩 가이드",
                        description="고인물 모드 첫 활성화 시 기능 설명 팝업 표시",
                        priority=Priority.P2_MEDIUM, page="Price",
                        category="온보딩", effort="낮음",
                    ),
                    Recommendation(
                        id="PRC-03", title="데이터 갱신 시간 표시",
                        description="가격 데이터의 마지막 갱신 시간을 명확히 표시",
                        priority=Priority.P1_HIGH, page="Price",
                        category="신뢰성", effort="낮음",
                    ),
                ],
            ),
            PageAnalysis(
                page="Mart (대형마트)",
                score=7,
                strengths=[
                    "마트별 탭으로 직관적 전환",
                    "전단지 뷰어로 실제 세일 정보 확인",
                    "교차 비교로 최적 마트 선택 지원",
                ],
                weaknesses=[
                    "전단지 이미지 로딩 속도 저하 가능",
                    "세일 기간 종료 알림 부재",
                    "마트 위치 기반 정렬 미지원",
                ],
                recommendations=[
                    Recommendation(
                        id="MRT-01", title="전단지 이미지 지연 로딩 적용",
                        description="전단지 이미지에 lazy loading을 적용하여 초기 로딩 속도 개선",
                        priority=Priority.P1_HIGH, page="Mart",
                        category="성능", effort="낮음",
                    ),
                    Recommendation(
                        id="MRT-02", title="세일 종료 임박 알림",
                        description="관심 세일 종료 24시간 전 푸시 알림 제공",
                        priority=Priority.P3_NICE_TO_HAVE, page="Mart",
                        category="알림", effort="높음",
                    ),
                ],
            ),
            PageAnalysis(
                page="Local (내 주변)",
                score=7,
                strengths=[
                    "위치 기반 주유소/식당 정보 제공",
                    "가격순 정렬로 최저가 즉시 확인",
                    "요리 vs 외식 비교가 실용적",
                ],
                weaknesses=[
                    "위치 권한 미허용 시 대안 미흡",
                    "지도 뷰와 리스트 뷰 전환 불편",
                    "실시간 가격 정확도 보장 어려움",
                ],
                recommendations=[
                    Recommendation(
                        id="LOC-01", title="위치 권한 거부 시 수동 입력 개선",
                        description="위치 권한 거부 시 주소/우편번호 입력으로 대체 가능하게 개선",
                        priority=Priority.P0_CRITICAL, page="Local",
                        category="오류 처리", effort="중간",
                    ),
                    Recommendation(
                        id="LOC-02", title="지도/리스트 뷰 토글 개선",
                        description="한 번의 탭으로 지도/리스트 뷰 전환 가능하도록 UI 개선",
                        priority=Priority.P2_MEDIUM, page="Local",
                        category="UX 개선", effort="낮음",
                    ),
                ],
            ),
            PageAnalysis(
                page="Community (커뮤니티)",
                score=7,
                strengths=[
                    "핫딜/자유 게시판 구분으로 콘텐츠 정리",
                    "이미지 첨부 글 작성 지원",
                    "DB 가격 검증 연동으로 신뢰성 확보",
                    "투표 시스템으로 양질의 정보 부각",
                ],
                weaknesses=[
                    "글 작성 중 이탈 시 데이터 유실",
                    "댓글 알림 기능 부재",
                    "스팸/어뷰징 방지 기능 미흡",
                ],
                recommendations=[
                    Recommendation(
                        id="COM-01", title="글 작성 자동 저장",
                        description="글 작성 중 30초마다 자동 저장하여 데이터 유실 방지",
                        priority=Priority.P0_CRITICAL, page="Community",
                        category="데이터 보호", effort="중간",
                    ),
                    Recommendation(
                        id="COM-02", title="댓글 알림 시스템",
                        description="내 글에 댓글이 달리면 알림을 받을 수 있도록 개선",
                        priority=Priority.P2_MEDIUM, page="Community",
                        category="알림", effort="높음",
                    ),
                    Recommendation(
                        id="COM-03", title="스팸 방지 시스템",
                        description="중복 글, 어뷰징 투표를 감지하고 방지하는 시스템 구축",
                        priority=Priority.P1_HIGH, page="Community",
                        category="안전성", effort="높음",
                    ),
                ],
            ),
        ],
    )
