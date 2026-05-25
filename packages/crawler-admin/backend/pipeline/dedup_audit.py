"""
마트 크롤러 중복 감사 모듈 — 3축 dedup 검증.

왜 존재하는가:
    마트 크롤러(홈플러스·코스트코 등)는 여러 카테고리/검색어에서 동일 상품을
    중복 수집할 수 있다. 단순 카운트만으로는 실제 유니크 상품 수를 알 수 없다.
    이 모듈은 3축으로 중복을 검사하여 "진짜" 유니크 카운트를 보고한다.

3 axes (중복 판정 기준):
    1. source_record_key  — 크롤러가 부여한 불변 source 키 (가장 신뢰)
    2. detail_url         — 상품 상세 URL (정규화 후 비교)
    3. (name, sale_price) — 상품명 + 판매가 조합 (키 없는 경우 폴백)

어디서 쓰이나:
    - 수집 후 파이프라인 감사 단계
    - CI/live validation 산출물 생성
    - plugin.yaml minimum_rows 재산정 보조

의존: 외부 라이브러리 없음 (순수 Python)
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _extract_fields(record: Any) -> tuple[str, str, str, str]:
    """record(dict 또는 DiscountItem)에서 dedup 3축 필드를 추출한다."""
    if isinstance(record, dict):
        attrs = record.get("attributes") or {}
        source_key = str(attrs.get("source_record_key") or "").strip()
        detail_url = str(
            attrs.get("source_url") or record.get("detail_url") or ""
        ).strip()
        name = str(record.get("name") or "").strip()
        sale_price = str(record.get("sale_price") or "").strip()
    else:
        attrs = getattr(record, "attributes", {}) or {}
        source_key = str(attrs.get("source_record_key") or "").strip()
        detail_url = str(
            attrs.get("source_url") or getattr(record, "detail_url", "") or ""
        ).strip()
        name = str(getattr(record, "name", "") or "").strip()
        sale_price = str(getattr(record, "sale_price", "") or "").strip()
    return source_key, detail_url, name, sale_price


_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "ref", "from", "_ga", "_gid",
})


def _normalize_url(url: str) -> str:
    """URL을 정규화하여 같은 상품 페이지를 통일한다.

    - scheme 통일 (http → https)
    - www 제거
    - trailing slash 제거
    - UTM/추적 파라미터 제거, 나머지 쿼리파라미터는 유지 (상품 ID 포함)
    - 쿼리 파라미터 키 정렬 (순서 차이 무시)
    """
    if not url:
        return ""
    try:
        from urllib.parse import parse_qs, urlencode
        parsed = urlparse(url)
        host = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        filtered = {
            k: v for k, v in params.items()
            if k.lower() not in _TRACKING_PARAMS
        }
        sorted_query = urlencode(sorted(filtered.items()), doseq=True)
        base = f"https://{host}{path}"
        return f"{base}?{sorted_query}" if sorted_query else base
    except Exception:
        return url.strip().lower()


def _normalize_name(name: str) -> str:
    """상품명을 정규화하여 공백/특수문자 차이를 무시한다."""
    if not name:
        return ""
    name = re.sub(r"[^\w가-힣]", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

class MartDedupAuditor:
    """마트 크롤러 중복 감사기.

    사용법::

        auditor = MartDedupAuditor(records)
        report = auditor.audit()
        # report["unique_by_source_key"], report["unique_by_url"], ...
    """

    def __init__(self, records: list[Any]):
        """
        Args:
            records: DiscountItem 목록 또는 model_dump(mode="json") dict 목록.
        """
        self._records = records

    # ------------------------------------------------------------------
    # 3축 dedup 카운터
    # ------------------------------------------------------------------

    def count_by_source_record_key(self) -> dict[str, int]:
        """source_record_key 축 중복 카운트.

        Returns:
            {"total": N, "unique": U, "duplicate": D,
             "records_without_key": W}
        """
        seen: set[str] = set()
        duplicates = 0
        no_key = 0
        for rec in self._records:
            src_key, _, _, _ = _extract_fields(rec)
            if not src_key:
                no_key += 1
                continue
            if src_key in seen:
                duplicates += 1
            else:
                seen.add(src_key)
        unique = len(seen)
        return {
            "total": len(self._records),
            "unique": unique,
            "duplicate": duplicates,
            "records_without_key": no_key,
        }

    def count_by_detail_url(self) -> dict[str, int]:
        """detail_url(정규화) 축 중복 카운트.

        Returns:
            {"total": N, "unique": U, "duplicate": D,
             "records_without_url": W}
        """
        seen: set[str] = set()
        duplicates = 0
        no_url = 0
        for rec in self._records:
            _, detail_url, _, _ = _extract_fields(rec)
            norm = _normalize_url(detail_url)
            if not norm:
                no_url += 1
                continue
            if norm in seen:
                duplicates += 1
            else:
                seen.add(norm)
        unique = len(seen)
        return {
            "total": len(self._records),
            "unique": unique,
            "duplicate": duplicates,
            "records_without_url": no_url,
        }

    def count_by_name_price(self) -> dict[str, int]:
        """(name, sale_price) 조합 축 중복 카운트.

        Returns:
            {"total": N, "unique": U, "duplicate": D}
        """
        seen: set[tuple[str, str]] = set()
        duplicates = 0
        for rec in self._records:
            _, _, name, sale_price = _extract_fields(rec)
            norm_name = _normalize_name(name)
            key = (norm_name, sale_price)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
        unique = len(seen)
        return {
            "total": len(self._records),
            "unique": unique,
            "duplicate": duplicates,
        }

    # ------------------------------------------------------------------
    # 통합 감사 보고서
    # ------------------------------------------------------------------

    def audit(self) -> dict[str, Any]:
        """3축 dedup 감사 결과를 반환한다.

        Returns:
            dict with keys:
              - total_records
              - by_source_record_key: {total, unique, duplicate, records_without_key}
              - by_detail_url:        {total, unique, duplicate, records_without_url}
              - by_name_price:        {total, unique, duplicate}
              - conservative_unique:  가장 엄격한 축 기준 unique 수
              - liberal_unique:       가장 느슨한 축 기준 unique 수
              - verdict:              "clean" | "has_duplicates" | "suspicious"
              - minimum_rows_recommendation: 측정 기반 권고값 (±20% 하한)
        """
        by_key = self.count_by_source_record_key()
        by_url = self.count_by_detail_url()
        by_np = self.count_by_name_price()

        # source_record_key가 없는 레코드가 많으면 URL/name-price 우선
        key_coverage = (
            (len(self._records) - by_key["records_without_key"]) / len(self._records)
            if self._records
            else 0.0
        )
        if key_coverage >= 0.9:
            primary_unique = by_key["unique"]
        elif by_url["records_without_url"] == 0 or (
            len(self._records) - by_url["records_without_url"]
        ) / max(len(self._records), 1) >= 0.9:
            primary_unique = by_url["unique"]
        else:
            primary_unique = by_np["unique"]

        # conservative = 가장 작은 unique (가장 많은 중복 가정)
        conservative_unique = min(
            v["unique"] for v in [by_key, by_url, by_np]
            if v["unique"] > 0
        ) if self._records else 0

        # liberal = 가장 큰 unique
        liberal_unique = max(
            by_key["unique"], by_url["unique"], by_np["unique"]
        )

        total_dup = (
            by_key["duplicate"] + by_url["duplicate"] + by_np["duplicate"]
        )
        if total_dup == 0:
            verdict = "clean"
        elif any(
            v["duplicate"] > len(self._records) * 0.05
            for v in [by_key, by_url, by_np]
        ):
            verdict = "suspicious"
        else:
            verdict = "has_duplicates"

        # minimum_rows = primary_unique × 0.80 (±20% 하한)
        recommended_minimum = max(1, int(primary_unique * 0.80)) if primary_unique else 0

        return {
            "total_records": len(self._records),
            "by_source_record_key": by_key,
            "by_detail_url": by_url,
            "by_name_price": by_np,
            "key_coverage_ratio": round(key_coverage, 4),
            "conservative_unique": conservative_unique,
            "liberal_unique": liberal_unique,
            "primary_unique": primary_unique,
            "verdict": verdict,
            "minimum_rows_recommendation": recommended_minimum,
            "audit_policy": (
                "minimum_rows = primary_unique × 0.80 (측정 기반 ±20% 하한). "
                "cap 기반 하드코딩 금지."
            ),
        }


def audit_mart_records(records: list[Any]) -> dict[str, Any]:
    """편의 함수: records 리스트에 대해 MartDedupAuditor.audit()을 실행한다."""
    return MartDedupAuditor(records).audit()


def recommend_minimum_rows(
    measured_avg: float,
    safety_factor: float = 0.80,
) -> int:
    """측정된 평균 수집량 기반 minimum_rows 권고값을 계산한다.

    Args:
        measured_avg: 실제 수집 평균 (복수 run 평균 권장).
        safety_factor: 하한 비율 (기본 0.80 = 20% 여유).

    Returns:
        권고 minimum_rows 값.
    """
    if measured_avg <= 0:
        return 0
    return max(1, int(measured_avg * safety_factor))
