"""
핫딜 중복 감지 모듈 — 여러 커뮤니티에서 같은 딜이 올라오는 걸 감지.

왜 존재하는가:
    뽐뿌, 클리앙, 퀘이사존, FM코리아 등 여러 커뮤니티에서 동일한 핫딜이
    중복 게시된다. 사용자에게 같은 딜을 여러 번 보여주면 피로도가 높아지고,
    통계 분석 시에도 중복 데이터가 결과를 왜곡한다.

어디서 쓰이나:
    파이프라인에서 모든 핫딜 크롤러 결과를 합친 후 이 모듈로 중복을 제거한다.
    크롤러 → 개별 결과 → 합산 → HotdealDeduplicator → 유니크 결과 → 저장

동작 원리:
    1단계: URL 정규화 → 정확 매칭 (같은 URL이면 확실한 중복)
    2단계: 제목 유사도 (character n-gram Jaccard similarity)
    3단계: 가격 + 제목 키워드 조합 매칭

의존: 외부 라이브러리 없음 (순수 Python)
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode


class HotdealDeduplicator:
    """핫딜 중복 감지 및 제거기."""

    def __init__(self, threshold: float = 0.85):
        """
        Args:
            threshold: 제목 유사도 임계값 (0.0~1.0). 이 값 이상이면 중복으로 판정.
        """
        self.threshold = threshold

    def find_duplicates(self, items: list[dict]) -> list[dict]:
        """중복 그룹을 찾아 반환. 각 아이템에 'duplicate_group' 필드 추가.

        Args:
            items: HotdealPost 딕셔너리 리스트

        Returns:
            duplicate_group 필드가 추가된 아이템 리스트.
            같은 그룹 번호를 가진 아이템들이 중복이다.
        """
        if not items:
            return items

        n = len(items)
        # Union-Find로 중복 그룹 관리
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # 1단계: URL 정규화 후 정확 매칭
        url_index: dict[str, int] = {}
        for i, item in enumerate(items):
            norm_url = self._normalize_url(item.get("url", ""))
            if norm_url in url_index:
                union(i, url_index[norm_url])
            else:
                url_index[norm_url] = i

        # 2단계: 제목 유사도 + 가격 비교
        normalized_titles = [self._normalize_title(item.get("title", "")) for item in items]
        ngrams_cache = [self._char_ngrams(t, 2) for t in normalized_titles]

        for i in range(n):
            for j in range(i + 1, n):
                # 이미 같은 그룹이면 스킵
                if find(i) == find(j):
                    continue

                # 제목 유사도 계산
                sim = self._jaccard_similarity(ngrams_cache[i], ngrams_cache[j])

                if sim >= self.threshold:
                    union(i, j)
                elif sim >= 0.6:
                    # 유사도가 중간이면 가격까지 비교
                    price_i = items[i].get("price")
                    price_j = items[j].get("price")
                    if price_i is not None and price_j is not None and price_i == price_j:
                        union(i, j)

        # 그룹 번호 할당
        group_map: dict[int, int] = {}
        group_counter = 0
        result = []
        for i, item in enumerate(items):
            root = find(i)
            if root not in group_map:
                group_map[root] = group_counter
                group_counter += 1

            item_copy = dict(item)
            item_copy["duplicate_group"] = group_map[root]
            result.append(item_copy)

        return result

    def deduplicate(self, items: list[dict]) -> list[dict]:
        """중복 제거 후 유니크 아이템만 반환.

        우선순위:
        1. crawled_at이 가장 빠른 것 (먼저 올린 것)
        2. 가격 정보가 있는 것
        3. 제목이 더 긴 것 (정보가 많은 것)

        Args:
            items: HotdealPost 딕셔너리 리스트

        Returns:
            중복 제거된 아이템 리스트
        """
        if not items:
            return items

        grouped = self.find_duplicates(items)

        # 그룹별로 최적 아이템 선택
        groups: dict[int, list[dict]] = {}
        for item in grouped:
            gid = item["duplicate_group"]
            groups.setdefault(gid, []).append(item)

        result = []
        for gid, group_items in groups.items():
            best = self._select_best(group_items)
            # duplicate_group 필드 제거 — 최종 결과에는 불필요
            best.pop("duplicate_group", None)
            result.append(best)

        return result

    def _select_best(self, group_items: list[dict]) -> dict:
        """그룹 내 최적 아이템을 선택한다."""

        def score(item: dict) -> tuple:
            has_price = 1 if item.get("price") is not None else 0
            title_len = len(item.get("title", ""))
            crawled = item.get("crawled_at", "")
            return (has_price, title_len, crawled)

        return max(group_items, key=score)

    def _normalize_url(self, url: str) -> str:
        """URL을 정규화하여 같은 페이지를 가리키는 URL을 통일한다."""
        if not url:
            return ""

        parsed = urlparse(url)
        # 스키마 통일 (http → https)
        scheme = "https"
        # www 제거
        host = parsed.netloc.lower().replace("www.", "")
        # 쿼리 파라미터 정렬 (추적 파라미터 제거)
        params = parse_qs(parsed.query)
        # UTM 등 추적 파라미터 제거
        tracking_keys = {"utm_source", "utm_medium", "utm_campaign", "utm_content",
                         "utm_term", "fbclid", "gclid", "ref", "from"}
        filtered = {k: v for k, v in params.items() if k.lower() not in tracking_keys}
        sorted_query = urlencode(filtered, doseq=True) if filtered else ""

        return f"{scheme}://{host}{parsed.path.rstrip('/')}" + \
               (f"?{sorted_query}" if sorted_query else "")

    def _normalize_title(self, title: str) -> str:
        """제목 정규화 — 특수문자/가격/플랫폼 태그 제거."""
        if not title:
            return ""

        # 커뮤니티 태그 제거 — [뽐뿌], [펨코], [퀘존] 등
        title = re.sub(r"\[(?:뽐뿌|펨코|에펨|퀘존|퀘이사|클리앙|루리웹|아카|알구몬)\]", "", title)

        # 쇼핑몰 태그 제거 — [G마켓], [쿠팡], [11번가] 등
        title = re.sub(r"\[[^\]]{1,10}\]", "", title)

        # 가격 패턴 제거
        title = re.sub(r"\d{1,3}(?:,\d{3})+\s*원", "", title)
        title = re.sub(r"\d{3,}\s*원", "", title)

        # 특수문자 제거 (한글, 영문, 숫자, 공백만 유지)
        title = re.sub(r"[^\w\s가-힣]", " ", title)

        # 연속 공백 정리
        title = re.sub(r"\s+", " ", title).strip().lower()

        return title

    def _char_ngrams(self, text: str, n: int = 2) -> set[str]:
        """텍스트에서 문자 n-gram 집합을 생성한다."""
        if len(text) < n:
            return {text} if text else set()
        return {text[i:i + n] for i in range(len(text) - n + 1)}

    def _jaccard_similarity(self, set_a: set, set_b: set) -> float:
        """두 집합의 Jaccard 유사도를 계산한다."""
        if not set_a and not set_b:
            return 1.0
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0

    def get_stats(self, items: list[dict]) -> dict:
        """중복 통계를 반환한다."""
        grouped = self.find_duplicates(items)

        groups: dict[int, list[dict]] = {}
        for item in grouped:
            gid = item["duplicate_group"]
            groups.setdefault(gid, []).append(item)

        total = len(items)
        unique = len(groups)
        duplicates = total - unique
        dup_groups = {gid: len(g) for gid, g in groups.items() if len(g) > 1}

        return {
            "total_items": total,
            "unique_items": unique,
            "duplicate_items": duplicates,
            "duplicate_groups": len(dup_groups),
            "largest_group": max(dup_groups.values()) if dup_groups else 0,
        }
