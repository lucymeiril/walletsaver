#!/usr/bin/env python3
"""Create conservative proposal-only coverage for every current pass45 remaining record.

This intentionally does not integrate anything, edit accepted/REMAINING/archives, or run tests.
It reuses historical proposals only when the current source identity is an exact match, then
uses current-taxonomy exact evidence where safe, explicit new-leaf lanes for clearly uncovered
product domains, and HOLD for everything that cannot be resolved conservatively.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
PASS45 = ROOT / "handoff" / "2026-09-14-pass45"
REMAINING = PASS45 / "remaining"
TARGET = PASS45 / "proposals" / "complete-remaining-001-451.json"
STATUS = PASS45 / "CURRENT_STATUS.md"

GENERIC_LABELS = {
    "기타", "일반", "혼합", "세트", "상품", "식품", "음료", "과자", "간식",
    "생활용품", "주방용품", "건강식품", "베스트", "냉동식품", "가공식품",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def norm(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def source_key(row: dict) -> str | None:
    normalized = row.get("normalized") or {}
    payload = normalized.get("raw_payload") or {}
    value = normalized.get("source_record_key") or payload.get("source_record_key")
    return None if value is None else str(value)


def source_identity(row: dict) -> tuple[str, str | None, str]:
    classification = row["classification"]
    return (
        str(classification.get("mart") or row.get("normalized", {}).get("crawler_name") or ""),
        source_key(row),
        str(classification.get("source_title") or ""),
    )


def issues_for(row: dict) -> list[str]:
    return sorted({str(x) for x in (row.get("normalized", {}).get("issues") or [])})


def lane_for(decision: str, issues: list[str]) -> str:
    if decision in {"new_leaf_needed", "hold"} or issues:
        return "needs_review"
    return "clear_existing"


def quantity_note(issues: list[str]) -> str:
    if not issues:
        return "unchanged"
    return "unchanged; unresolved issues preserved: " + ", ".join(issues)


def evidence_urls(row: dict) -> list[str]:
    values = row.get("classification", {}).get("source_urls") or []
    return [str(values[0])] if values else []


def current_decision_base(row: dict, raw_record_id: str) -> dict:
    mart, key, title = source_identity(row)
    return {
        "raw_record_ids": [raw_record_id],
        "source_name": mart,
        "source_record_key": key,
        "source_title": title,
        "evidence_urls": evidence_urls(row),
        "quantity_review": quantity_note(issues_for(row)),
        "identity_merge": "not_requested",
    }


def historical_candidates(records: dict[str, dict], leaf_ids: set[str]):
    candidates: dict[str, list[tuple[tuple, str, dict]]] = defaultdict(list)
    for path in sorted(ROOT.glob("handoff/**/proposals/*.json")):
        if path.resolve() == TARGET.resolve():
            continue
        try:
            payload = load_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("decisions"), list):
            continue
        for decision in payload["decisions"]:
            if not isinstance(decision, dict):
                continue
            kind = decision.get("decision")
            if kind not in {"existing_leaf", "new_leaf_needed", "hold", "already_classified"}:
                continue
            if kind == "hold" and decision.get("suggested_new_leaf"):
                # Old semantic shape; force a fresh current-format decision instead of silently reusing it.
                continue
            leaf = decision.get("unified_category_id")
            if kind == "existing_leaf" and leaf not in leaf_ids:
                continue
            if kind != "existing_leaf" and leaf is not None:
                continue
            raw_ids = decision.get("raw_record_ids") or []
            for rid in raw_ids:
                if rid not in records:
                    continue
                row = records[rid]
                mart, key, title = source_identity(row)
                if str(decision.get("source_name") or "") != mart:
                    continue
                if str(decision.get("source_record_key") or "") != str(key or ""):
                    continue
                if str(decision.get("source_title") or "") != title:
                    continue
                fingerprint = (kind, leaf, decision.get("suggested_new_leaf"))
                candidates[rid].append((fingerprint, str(path.relative_to(ROOT)), decision))
    return candidates


def build_leaf_matcher(taxonomy: dict):
    leaf_ids = set(taxonomy["leaf_ids"])
    labels: list[tuple[str, str, str]] = []
    slug_to_ids: dict[str, list[str]] = defaultdict(list)
    for node in taxonomy.get("nodes", []):
        leaf = node.get("id")
        if leaf not in leaf_ids:
            continue
        label = str(node.get("name_ko") or "").strip()
        nlabel = norm(label)
        if nlabel and nlabel not in GENERIC_LABELS and len(nlabel) >= 3:
            labels.append((nlabel, leaf, label))
        slug = str(node.get("slug") or "").strip().lower()
        if len(slug) >= 4:
            slug_to_ids[slug].append(leaf)
    unique_slugs = {slug: ids[0] for slug, ids in slug_to_ids.items() if len(ids) == 1}
    labels.sort(key=lambda item: (-len(item[0]), item[1]))
    return leaf_ids, labels, unique_slugs


def exact_leaf(row: dict, labels, unique_slugs) -> tuple[str, str] | None:
    c = row["classification"]
    title = norm(c.get("source_title"))
    path = norm(c.get("source_path"))
    label_hits = []
    for token, leaf, display in labels:
        in_title = token in title
        in_path = token in path
        if in_title or in_path:
            strength = 2 if in_title else 1
            label_hits.append((strength, len(token), leaf, display, "title" if in_title else "source_path"))
    if label_hits:
        best_strength = max(x[0] for x in label_hits)
        strongest = [x for x in label_hits if x[0] == best_strength]
        best_len = max(x[1] for x in strongest)
        best = [x for x in strongest if x[1] == best_len]
        leaves = {x[2] for x in best}
        if len(leaves) == 1:
            chosen = sorted(best, key=lambda x: x[2])[0]
            return chosen[2], f"현재 taxonomy 리프명 '{chosen[3]}'이 {chosen[4]}에 직접 일치"

    # English slug evidence is accepted only when that slug is globally unique among current leaves.
    text = " ".join(
        [str(c.get("source_title") or ""), str(c.get("source_path") or "")]
        + [str(x) for x in (c.get("url_taxonomy_hints") or [])]
        + [str(x) for x in (c.get("source_urls") or [])]
    ).lower()
    slug_hits = []
    for slug, leaf in unique_slugs.items():
        if re.search(r"(?<![a-z0-9])" + re.escape(slug.replace("_", "[-_ ]?")) + r"(?![a-z0-9])", text):
            slug_hits.append((len(slug), leaf, slug))
    if slug_hits:
        best_len = max(x[0] for x in slug_hits)
        best = [x for x in slug_hits if x[0] == best_len]
        if len({x[1] for x in best}) == 1:
            chosen = sorted(best, key=lambda x: x[1])[0]
            return chosen[1], f"현재 taxonomy의 고유 slug '{chosen[2]}'가 URL/경로 근거와 직접 일치"
    return None


def proposed_new_leaf(row: dict) -> tuple[str, str] | None:
    c = row["classification"]
    title = str(c.get("source_title") or "")
    path = str(c.get("source_path") or "")
    urls = " ".join(str(x) for x in (c.get("source_urls") or []))
    hay = (title + " " + path + " " + urls).lower()

    rules = [
        (("반려동물", "반려견", "반려묘", "강아지", "고양이", "/pet/"), "nonfood.pet.other", "반려동물 상품 축"),
        (("디지털", "가전", "전자제품", "냉장고", "세탁기", "건조기", "제습기", "에어컨", "공기청정기", "노트북", "모니터", "이어폰", "헤드폰"), "nonfood.electronics.other", "전자·가전 상품 축"),
        (("가구", "소파", "책상", "의자", "수납장", "테이블"), "nonfood.home.furniture", "가구 상품 축"),
        (("침구", "이불", "베개", "매트리스", "토퍼", "침대패드"), "nonfood.home.bedding", "침구 상품 축"),
        (("남성의류", "여성의류", "의류", "티셔츠", "셔츠", "바지", "재킷", "자켓", "원피스", "양말"), "nonfood.apparel.other", "의류 상품 축"),
        (("완구", "장난감", "레고", "인형", "보드게임"), "nonfood.toys.other", "완구 상품 축"),
        (("문구", "도서", "책 ", "노트", "색연필", "크레용", "필기구"), "nonfood.stationery_hobby_books.other", "문구·도서·취미 상품 축"),
        (("자동차용품", "캠핑", "등산", "골프", "여행용품", "캐리어"), "nonfood.lifestyle.sports_travel_auto", "스포츠·여행·자동차용품 축"),
        (("망치", "드라이버", "렌치", "공구세트", "전동공구", "드릴"), "nonfood.home.hardware", "공구·하드웨어 상품 축"),
        (("프라이팬", "후라이팬", "냄비", "도마", "식기세트", "접시", "수저세트", "주방칼"), "nonfood.kitchenware.other", "내구성 주방용품 축"),
        (("건전지", "aa 배터리", "aaa 배터리", "리튬배터리", "리튬 건전지"), "household.electrical.batteries", "전지·배터리 상품 축"),
    ]
    for needles, suggested, description in rules:
        if any(n.lower() in hay for n in needles):
            return suggested, f"{description}이 명확하지만 현재 taxonomy에는 대응 리프가 없음"

    supplement_path = any(x in path for x in ("건강식품", "건강기능식품", "영양제"))
    supplement_form = any(x in title.lower() for x in ("비타민", "프로바이오틱", "유산균", "오메가", "루테인", "밀크씨슬", "영양제", "캡슐", "정제", "홍삼정"))
    if supplement_path and supplement_form:
        return "health.supplements.other", "건강기능·영양보조제 형태가 명확하지만 현재 taxonomy에는 보조제 축이 없음"
    return None


def make_historical(row: dict, rid: str, source: str, old: dict) -> dict:
    issues = issues_for(row)
    kind = old["decision"]
    result = current_decision_base(row, rid)
    result.update({
        "decision": kind,
        "review_lane": lane_for(kind, issues),
        "unified_category_id": old.get("unified_category_id"),
        "reason": f"현재 원문 ID·마트·판매키·제목이 정확히 일치하는 기존 제안을 재사용: {source}. " + str(old.get("reason") or ""),
    })
    if kind == "new_leaf_needed":
        result["suggested_new_leaf"] = old.get("suggested_new_leaf")
    return result


def make_fresh(row: dict, rid: str, labels, unique_slugs) -> tuple[dict, str]:
    issues = issues_for(row)
    exact = exact_leaf(row, labels, unique_slugs)
    base = current_decision_base(row, rid)
    if exact:
        leaf, why = exact
        base.update({
            "decision": "existing_leaf",
            "review_lane": lane_for("existing_leaf", issues),
            "unified_category_id": leaf,
            "reason": why + ". 수량·가격·프로모션 원문은 변경하지 않는다.",
        })
        return base, "exact_current_taxonomy"

    new_leaf = proposed_new_leaf(row)
    if new_leaf:
        suggested, why = new_leaf
        base.update({
            "decision": "new_leaf_needed",
            "review_lane": "needs_review",
            "unified_category_id": None,
            "suggested_new_leaf": suggested,
            "reason": why + ". 신규 리프는 설계 검토 대상으로만 제안하며 자동 반영하지 않는다.",
        })
        return base, "explicit_new_leaf_domain"

    base.update({
        "decision": "hold",
        "review_lane": "needs_review",
        "unified_category_id": None,
        "reason": "현재 taxonomy와 제목·진열·URL 근거만으로 단일 기존 리프 또는 명확한 신규 리프 형태를 보수적으로 확정할 수 없어 보류한다. 수량·가격·프로모션 원문은 변경하지 않는다.",
    })
    return base, "conservative_hold"


def validate(records: dict[str, dict], decisions: list[dict], leaf_ids: set[str]):
    seen = []
    for d in decisions:
        ids = d.get("raw_record_ids") or []
        if len(ids) != 1:
            raise AssertionError("generated decisions must be one-current-id-per-decision")
        rid = ids[0]
        if rid not in records:
            raise AssertionError(f"non-current id in output: {rid}")
        row = records[rid]
        mart, key, title = source_identity(row)
        if d.get("source_name") != mart or str(d.get("source_record_key") or "") != str(key or "") or d.get("source_title") != title:
            raise AssertionError(f"source identity mismatch: {rid}")
        kind = d.get("decision")
        leaf = d.get("unified_category_id")
        if kind == "existing_leaf" and leaf not in leaf_ids:
            raise AssertionError(f"invalid existing leaf: {rid} {leaf}")
        if kind in {"new_leaf_needed", "hold", "already_classified"} and leaf is not None:
            raise AssertionError(f"non-existing decision has leaf: {rid}")
        if kind == "new_leaf_needed" and not d.get("suggested_new_leaf"):
            raise AssertionError(f"new leaf missing suggestion: {rid}")
        seen.append(rid)
    if len(seen) != len(set(seen)):
        raise AssertionError("duplicate raw_record_id in generated decisions")
    missing = set(records) - set(seen)
    extra = set(seen) - set(records)
    if missing or extra:
        raise AssertionError(f"coverage mismatch missing={len(missing)} extra={len(extra)}")


def append_status(baseline: str, total: int, counts: Counter, methods: Counter):
    text = STATUS.read_text(encoding="utf-8")
    marker = "complete-remaining-001-451"
    if marker in text:
        raise ValueError("CURRENT_STATUS already contains completion marker")
    block = f"""

## 전체 remaining 제안 큐 완료

- `{marker} / 기준{baseline[:7]} / pass45 remaining/001-451 현재 {total:,}관측 전부 / 제안 완료 / proposals/complete-remaining-001-451.json / 다음: Work 모드 교차검증·일괄검증·통합`. 현재 원문과 ID·마트·판매키·제목이 정확히 맞는 과거 제안은 재사용하고, 나머지는 현재 taxonomy의 직접 일치만 existing_leaf로 제안했다. taxonomy 밖 제품축이 명확한 경우만 new_leaf_needed로 분리했으며 나머지 불명확 항목은 hold로 보존했다.
- 결정수: {total:,}. decision 분포: {dict(sorted(counts.items()))}. 생성근거 분포: {dict(sorted(methods.items()))}.
- 이 완료 표시는 **제안작성 coverage 완료**를 뜻한다. new_leaf_needed/hold/단위·수량·프로모션 이슈는 후속 설계·충돌검사·통합 검토가 필요하며 DB 적재 완료를 뜻하지 않는다.
- 이번 작업은 `REMAINING.md`, `accepted.json`, `archives`, DB를 수정하지 않았다. 테스트·lint·import를 실행하지 않았고 결과파일의 `executed_tests`는 빈 배열이다.
"""
    STATUS.write_text(text.rstrip() + block + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    if TARGET.exists():
        raise ValueError(f"Refusing to replace existing result: {TARGET}")

    taxonomy = load_json(PASS45 / "taxonomy.json")
    leaf_ids, labels, unique_slugs = build_leaf_matcher(taxonomy)

    records: dict[str, dict] = {}
    for path in sorted(REMAINING.glob("*/*.json")):
        rows = load_json(path)
        if not isinstance(rows, list):
            raise TypeError(f"remaining shard is not a list: {path}")
        for row in rows:
            rid = str(row.get("classification", {}).get("raw_record_id") or row.get("normalized", {}).get("raw_record_id") or "")
            if not rid or rid in records:
                raise AssertionError(f"missing/duplicate raw_record_id: {rid}")
            records[rid] = row

    historical = historical_candidates(records, leaf_ids)
    decisions = []
    methods = Counter()
    for rid in sorted(records):
        row = records[rid]
        options = historical.get(rid, [])
        fingerprints = {item[0] for item in options}
        if options and len(fingerprints) == 1:
            _, source, old = sorted(options, key=lambda item: item[1])[-1]
            decision = make_historical(row, rid, source, old)
            method = "exact_historical_reuse"
        else:
            decision, method = make_fresh(row, rid, labels, unique_slugs)
            if options and len(fingerprints) > 1:
                decision["reason"] = "상충하는 과거 제안이 있어 재사용하지 않았다. " + decision["reason"]
                method = "historical_conflict_" + method
        decisions.append(decision)
        methods[method] += 1

    decisions.sort(key=lambda d: d["raw_record_ids"][0])
    validate(records, decisions, leaf_ids)
    counts = Counter(d["decision"] for d in decisions)
    payload = {
        "status": "proposal_only",
        "baseline_pass": "pass45",
        "baseline_commit": args.baseline,
        "scope": "all current handoff/2026-09-14-pass45/remaining/*/*.json records",
        "decisions": decisions,
        "generation_summary": {
            "current_remaining_raw_record_ids": len(records),
            "decision_counts": dict(sorted(counts.items())),
            "method_counts": dict(sorted(methods.items())),
            "coverage_validated": True,
            "duplicate_raw_record_ids": 0,
            "missing_raw_record_ids": 0,
            "existing_leaf_ids_validated_against_current_taxonomy": True,
            "db_integrated": False,
        },
        "executed_tests": [],
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    append_status(args.baseline, len(records), counts, methods)
    print(json.dumps(payload["generation_summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
