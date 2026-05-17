"""User-configurable constants for the adversarial compare tool.

Edit only this file to adjust alert thresholds and mart volume expectations
without touching analysis logic.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# D3: Mart absolute-volume expectations (final public DB rows per mart)
# ---------------------------------------------------------------------------
MIN_ROWS_PER_MART: dict[str, int] = {
    "emart": 200,
    "homeplus": 150,
    "lottemart": 100,
    "costco": 80,
    "coupang": 50,
}

# Pipeline attrition: if final_count < crawler_count * this ratio → alert
PIPELINE_ATTRITION_RATIO: float = 0.5

# ---------------------------------------------------------------------------
# D1: Category distribution thresholds
# ---------------------------------------------------------------------------
# A single category occupying this fraction of a mart's total triggers imbalance alert
CATEGORY_IMBALANCE_THRESHOLD: float = 0.60

# A category with >= this many items but zero L1-sibling categories triggers starvation alert
CATEGORY_STARVATION_MIN_COUNT: int = 100

# ---------------------------------------------------------------------------
# D2: AI confidence thresholds
# ---------------------------------------------------------------------------
# p25 below this value → low_confidence_tail_alert
CONFIDENCE_LOW_P25_THRESHOLD: float = 0.7

# 0.0–0.5 bin ratio above this value → low_confidence_tail_alert
CONFIDENCE_LOW_BIN_THRESHOLD: float = 0.05  # 5 %

# ---------------------------------------------------------------------------
# D4: Semantic spot-check
# ---------------------------------------------------------------------------
SPOTCHECK_SAMPLE_SIZE: int = 30
SPOTCHECK_PASS_RATE_THRESHOLD: float = 0.80  # 80 %

# keyword list → expected category prefix (first matching rule wins)
# Extend or edit freely; order matters for ambiguous titles
KEYWORD_CATEGORY_RULES: list[tuple[list[str], str]] = [
    (["쌀", "잡곡", "현미", "찹쌀", "흑미", "오트밀", "귀리", "보리"], "grain"),
    (["우유", "치즈", "버터", "요거트", "요구르트", "크림치즈", "유제품", "생크림"], "dairy"),
    (["삼겹살", "한우", "닭고기", "닭가슴살", "돼지고기", "소고기", "양고기", "오리고기", "육류", "스테이크"], "meat"),
    (["오이", "토마토", "양파", "당근", "배추", "대파", "감자", "고추", "마늘", "브로콜리", "상추", "시금치"], "vegetable"),
    (["사과", "배", "포도", "수박", "딸기", "귤", "레몬", "복숭아", "망고", "바나나", "키위", "오렌지"], "fruit"),
    (["라면", "국수", "스파게티", "파스타", "냉면", "소면", "우동"], "noodle"),
    (["참치", "고등어", "연어", "새우", "오징어", "게", "조개", "갈치", "해산물", "낙지"], "seafood"),
    (["샴푸", "린스", "바디워시", "세제", "비누", "치약", "면도기", "화장품", "로션", "스킨"], "personal_care"),
    (["기저귀", "분유", "이유식", "물티슈유아", "유아용", "베이비"], "baby"),
    (["맥주", "소주", "와인", "막걸리", "위스키", "양주", "보드카", "주류", "전통주"], "alcohol"),
    (["과자", "쿠키", "초콜릿", "사탕", "젤리", "스낵", "팝콘", "비스킷"], "snack"),
    (["커피", "녹차", "홍차", "주스", "음료수", "탄산수", "이온음료", "에너지드링크"], "beverage"),
    (["세탁세제", "주방세제", "청소용품", "살균제", "방향제", "섬유유연제"], "household"),
    (["화장지", "키친타올", "물티슈", "종이컵", "비닐봉지", "랩"], "paper"),
    (["식빵", "빵", "베이커리", "케이크", "크로아상", "도넛", "바게트"], "bakery"),
    (["참기름", "식용유", "올리브유", "들기름", "포도씨유", "코코넛오일"], "oil"),
    (["간장", "된장", "고추장", "소스", "드레싱", "케첩", "마요네즈", "양념"], "condiment"),
    (["냉동", "즉석밥", "간편식", "레토르트", "도시락", "편의식"], "convenience"),
    (["두부", "콩나물", "순두부", "유부", "청국장"], "soy"),
    (["아이스크림", "빙과", "아이스바", "콘아이스", "하드"], "ice_cream"),
]
