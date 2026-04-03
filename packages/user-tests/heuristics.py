"""
닐슨 10대 사용성 휴리스틱 평가 — WalletSavior (지갑 지키미)

Jakob Nielsen의 10가지 사용성 휴리스틱을 기반으로
각 항목을 1~5점 척도로 평가하고, 구체적 발견 사항과 개선 권고를 포함합니다.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import IntEnum


class Severity(IntEnum):
    """발견 사항 심각도"""
    COSMETIC = 1    # 외관 문제
    MINOR = 2       # 사소한 문제
    MAJOR = 3       # 주요 문제
    CRITICAL = 4    # 치명적 문제


@dataclass
class Finding:
    """개별 발견 사항"""
    description: str
    page: str
    severity: Severity
    recommendation: str
    screenshot_ref: Optional[str] = None

    def validate(self) -> bool:
        return bool(self.description and self.page and self.recommendation)


@dataclass
class HeuristicItem:
    """개별 휴리스틱 평가 항목"""
    id: str
    name: str
    name_ko: str
    description: str
    score: int  # 1-5
    findings: List[Finding] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def validate(self) -> bool:
        if not (1 <= self.score <= 5):
            return False
        if not self.id or not self.name or not self.name_ko:
            return False
        if not self.description:
            return False
        return True

    @property
    def critical_findings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity >= Severity.MAJOR]


@dataclass
class HeuristicEvaluation:
    """전체 휴리스틱 평가"""
    evaluator: str
    target: str
    items: List[HeuristicItem]
    overall_notes: str = ""

    def validate(self) -> bool:
        if not self.evaluator or not self.target:
            return False
        if len(self.items) != 10:
            return False
        return all(item.validate() for item in self.items)

    @property
    def average_score(self) -> float:
        if not self.items:
            return 0.0
        return sum(i.score for i in self.items) / len(self.items)

    @property
    def all_findings(self) -> List[Finding]:
        result = []
        for item in self.items:
            result.extend(item.findings)
        return result

    @property
    def critical_findings(self) -> List[Finding]:
        return [f for f in self.all_findings if f.severity >= Severity.MAJOR]

    def get_item_by_id(self, heuristic_id: str) -> Optional[HeuristicItem]:
        for item in self.items:
            if item.id == heuristic_id:
                return item
        return None

    def to_dict(self) -> Dict:
        return {
            "evaluator": self.evaluator,
            "target": self.target,
            "average_score": round(self.average_score, 2),
            "items": [
                {
                    "id": i.id,
                    "name": i.name,
                    "name_ko": i.name_ko,
                    "score": i.score,
                    "findings_count": len(i.findings),
                    "critical_count": len(i.critical_findings),
                    "recommendations": i.recommendations,
                }
                for i in self.items
            ],
            "total_findings": len(self.all_findings),
            "critical_findings": len(self.critical_findings),
        }


# ─── WalletSavior 휴리스틱 평가 ──────────────────────────────

def create_walletsavior_evaluation() -> HeuristicEvaluation:
    """WalletSavior에 대한 휴리스틱 평가 생성"""
    return HeuristicEvaluation(
        evaluator="UX 평가 프레임워크",
        target="WalletSavior (지갑 지키미)",
        items=[
            HeuristicItem(
                id="H1",
                name="Visibility of System Status",
                name_ko="시스템 상태의 가시성",
                description="시스템이 적절한 피드백을 통해 사용자에게 현재 상태를 알려주는가",
                score=4,
                findings=[
                    Finding(
                        description="핫딜 무한 스크롤 시 로딩 인디케이터가 표시됨",
                        page="Hotdeal",
                        severity=Severity.COSMETIC,
                        recommendation="스켈레톤 UI로 로딩 표시 개선",
                    ),
                    Finding(
                        description="검색 결과 카운트가 표시되어 현재 상태 파악 가능",
                        page="Price",
                        severity=Severity.COSMETIC,
                        recommendation="필터 적용 시에도 결과 수 표시 유지",
                    ),
                ],
                recommendations=[
                    "모든 비동기 작업에 로딩 상태 표시",
                    "데이터 갱신 시간 표시 (마지막 업데이트 시간)",
                    "크롤러 관리 대시보드에 실시간 진행률 표시",
                ],
            ),
            HeuristicItem(
                id="H2",
                name="Match Between System and Real World",
                name_ko="시스템과 현실 세계의 일치",
                description="시스템이 사용자의 언어와 익숙한 개념을 사용하는가",
                score=5,
                findings=[
                    Finding(
                        description="가격 표시가 ₩ 형식으로 한국 소비자에게 친숙함",
                        page="Price",
                        severity=Severity.COSMETIC,
                        recommendation="천 단위 구분자(,) 일관 적용 확인",
                    ),
                    Finding(
                        description="'고인물 모드' 등 한국 인터넷 문화 용어 사용으로 친근감 제공",
                        page="Price",
                        severity=Severity.COSMETIC,
                        recommendation="처음 사용자를 위한 용어 툴팁 추가",
                    ),
                ],
                recommendations=[
                    "모든 메뉴와 레이블을 한국어로 표시",
                    "'고인물 모드' 등 인터넷 용어에 설명 툴팁 추가",
                    "마트 이름을 실제 브랜드명으로 표시",
                ],
            ),
            HeuristicItem(
                id="H3",
                name="User Control and Freedom",
                name_ko="사용자 제어와 자유",
                description="사용자가 실수를 쉽게 되돌리고, 원치 않는 상태에서 벗어날 수 있는가",
                score=3,
                findings=[
                    Finding(
                        description="커뮤니티 글 작성 중 뒤로가기 시 작성 내용 유실 가능",
                        page="Community",
                        severity=Severity.MAJOR,
                        recommendation="자동 저장 또는 이탈 확인 다이얼로그 추가",
                    ),
                    Finding(
                        description="필터 초기화 버튼이 명확하지 않음",
                        page="Hotdeal",
                        severity=Severity.MINOR,
                        recommendation="'필터 초기화' 버튼을 눈에 띄게 배치",
                    ),
                ],
                recommendations=[
                    "뒤로가기 네비게이션 일관성 확보",
                    "폼 작성 중 이탈 시 확인 다이얼로그 표시",
                    "실행 취소(Undo) 기능 제공 (투표, 북마크 등)",
                    "검색/필터 초기화 버튼 명확히 표시",
                ],
            ),
            HeuristicItem(
                id="H4",
                name="Consistency and Standards",
                name_ko="일관성과 표준",
                description="동일한 단어, 상황, 행동이 같은 의미를 갖는가",
                score=4,
                findings=[
                    Finding(
                        description="버튼 스타일과 색상이 페이지 간 일관성 유지",
                        page="Home",
                        severity=Severity.COSMETIC,
                        recommendation="디자인 시스템 문서화 강화",
                    ),
                    Finding(
                        description="카드 레이아웃이 핫딜, 마트, 커뮤니티에서 일관됨",
                        page="Hotdeal",
                        severity=Severity.COSMETIC,
                        recommendation="카드 컴포넌트 재사용 확대",
                    ),
                ],
                recommendations=[
                    "공통 컴포넌트 라이브러리 활용 극대화",
                    "아이콘 세트 통일",
                    "에러 메시지 포맷 표준화",
                ],
            ),
            HeuristicItem(
                id="H5",
                name="Error Prevention",
                name_ko="오류 예방",
                description="오류가 발생하기 어렵도록 시스템이 설계되었는가",
                score=3,
                findings=[
                    Finding(
                        description="검색 자동완성으로 오타 방지 지원",
                        page="Price",
                        severity=Severity.COSMETIC,
                        recommendation="최근 검색어, 인기 검색어 표시 추가",
                    ),
                    Finding(
                        description="커뮤니티 글 삭제 시 확인 절차 필요",
                        page="Community",
                        severity=Severity.MAJOR,
                        recommendation="삭제 전 확인 다이얼로그 필수 적용",
                    ),
                ],
                recommendations=[
                    "파괴적 행동(삭제, 초기화)에 확인 다이얼로그 적용",
                    "필수 입력 필드 시각적 표시 (별표 등)",
                    "입력 유효성 실시간 검증",
                    "관리자 페이지 위험 작업에 2단계 확인 적용",
                ],
            ),
            HeuristicItem(
                id="H6",
                name="Recognition Rather Than Recall",
                name_ko="기억보다 인식",
                description="사용자가 정보를 기억하지 않고도 인식할 수 있도록 설계되었는가",
                score=4,
                findings=[
                    Finding(
                        description="카테고리 아이콘과 텍스트 병행으로 인식 용이",
                        page="Home",
                        severity=Severity.COSMETIC,
                        recommendation="아이콘 크기 및 명확성 개선",
                    ),
                    Finding(
                        description="가격대 뱃지로 가격 범위 직관적 표시",
                        page="Hotdeal",
                        severity=Severity.COSMETIC,
                        recommendation="뱃지 색상 의미를 범례로 제공",
                    ),
                ],
                recommendations=[
                    "브레드크럼 네비게이션 추가",
                    "최근 검색어 표시",
                    "카테고리별 시각적 구분 강화",
                    "마트 로고 이미지 활용",
                ],
            ),
            HeuristicItem(
                id="H7",
                name="Flexibility and Efficiency of Use",
                name_ko="유연성과 효율성",
                description="초보자와 전문가 모두에게 효율적인가",
                score=4,
                findings=[
                    Finding(
                        description="고인물 모드로 파워 유저 전용 기능 제공",
                        page="Price",
                        severity=Severity.COSMETIC,
                        recommendation="고인물 모드 진입 경로 다양화 (단축키 등)",
                    ),
                    Finding(
                        description="기본 모드는 초보자도 쉽게 사용 가능한 UI",
                        page="Home",
                        severity=Severity.COSMETIC,
                        recommendation="개인화 설정 저장 기능 추가",
                    ),
                ],
                recommendations=[
                    "키보드 단축키 지원 (데스크톱)",
                    "자주 찾는 상품 즐겨찾기 기능",
                    "개인화된 대시보드 설정 지원",
                    "고인물 모드 세부 설정 옵션 제공",
                ],
            ),
            HeuristicItem(
                id="H8",
                name="Aesthetic and Minimalist Design",
                name_ko="심미적이고 미니멀한 디자인",
                description="불필요한 정보 없이 깔끔하고 집중된 디자인인가",
                score=4,
                findings=[
                    Finding(
                        description="홈 페이지 레이아웃이 깔끔하고 핵심 정보 중심",
                        page="Home",
                        severity=Severity.COSMETIC,
                        recommendation="섹션 간 시각적 구분 강화",
                    ),
                    Finding(
                        description="정보 밀도가 적절하여 모바일에서도 가독성 확보",
                        page="Hotdeal",
                        severity=Severity.COSMETIC,
                        recommendation="고인물 모드에서 정보 과밀 주의",
                    ),
                ],
                recommendations=[
                    "정보 계층 구조 명확히 (제목 > 핵심 > 부가)",
                    "여백(white space) 적절히 활용",
                    "컬러 팔레트 3-4색 제한 유지",
                    "고인물 모드에서도 핵심 정보 우선 표시",
                ],
            ),
            HeuristicItem(
                id="H9",
                name="Help Users Recognize, Diagnose, and Recover from Errors",
                name_ko="오류 인식, 진단, 복구 지원",
                description="오류 메시지가 명확하고, 해결 방법을 제시하는가",
                score=3,
                findings=[
                    Finding(
                        description="네트워크 오류 시 사용자 친화적 메시지 필요",
                        page="Home",
                        severity=Severity.MAJOR,
                        recommendation="한국어 오류 메시지 + 재시도 버튼 제공",
                    ),
                    Finding(
                        description="검색 결과 없음 시 대안 제안 부재",
                        page="Price",
                        severity=Severity.MINOR,
                        recommendation="'이런 검색어는 어떠세요?' 제안 추가",
                    ),
                ],
                recommendations=[
                    "모든 오류 메시지를 한국어로 표시",
                    "오류 발생 시 구체적 해결 방법 안내",
                    "검색 결과 없을 때 대안 검색어 제안",
                    "네트워크 오류 시 자동 재시도 + 수동 재시도 버튼",
                ],
            ),
            HeuristicItem(
                id="H10",
                name="Help and Documentation",
                name_ko="도움말과 문서",
                description="필요 시 적절한 도움말과 가이드를 제공하는가",
                score=3,
                findings=[
                    Finding(
                        description="고인물 모드 기능에 대한 설명 부족",
                        page="Price",
                        severity=Severity.MINOR,
                        recommendation="고인물 모드 온보딩 가이드 추가",
                    ),
                    Finding(
                        description="첫 방문 사용자를 위한 투어 기능 부재",
                        page="Home",
                        severity=Severity.MINOR,
                        recommendation="첫 방문 시 주요 기능 안내 투어 추가",
                    ),
                ],
                recommendations=[
                    "첫 방문 사용자 온보딩 투어 추가",
                    "각 기능에 물음표(?) 아이콘으로 도움말 툴팁",
                    "FAQ 페이지 구축",
                    "고인물 모드 상세 가이드 제공",
                ],
            ),
        ],
        overall_notes="전반적으로 사용자 중심 설계가 잘 되어 있으나, 오류 처리와 도움말 영역에서 개선이 필요합니다. "
                      "고인물 모드는 파워 유저에게 큰 가치를 제공하지만, 처음 접하는 사용자를 위한 안내가 보강되어야 합니다.",
    )
