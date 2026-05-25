"""match_key 정규화 — raw record 필드 → MatchingEntry 조회 키 생성.

정규화 규칙:
    brand    : 소문자, 양쪽 공백 trim
    name_core: 소문자, 특수기호 제거(한글/영문/숫자/공백 유지), 연속 공백 단일화
    pack_qty : 소수점 1자리 round. None → ""
    pack_unit: 소문자. None → ""
    구분자   : "|"

이 규칙이 MatchingEntry.match_key 생성의 단일 진실 집합이다.
build_match_key를 거치지 않고 match_key를 직접 조립하지 말 것.
"""

from __future__ import annotations

import re
from typing import Optional

# 한글 자모/글자, 영문, 숫자, 공백 이외 문자를 공백으로 교체
_SPECIAL_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def build_match_key(
    brand: Optional[str],
    name_core: Optional[str],
    pack_qty: Optional[float],
    pack_unit: Optional[str],
) -> str:
    """brand/name_core/pack_qty/pack_unit → 정규화된 match_key 문자열 반환.

    동일한 입력은 항상 동일한 출력을 보장한다 (결정적).
    None은 "" 로 처리하므로 None과 빈 문자열은 동일하게 취급된다.

    Examples:
        >>> build_match_key("CJ", "햇반", 210.0, "g")
        'cj|햇반|210.0|g'
        >>> build_match_key(None, "신라면", 120.0, "G")
        '|신라면|120.0|g'
        >>> build_match_key("  Nongshim  ", "  신라면  ", 120.0, "g")
        'nongshim|신라면|120.0|g'
    """
    # brand: 소문자 + trim
    b = (brand or "").strip().lower()

    # name_core: 소문자 → 특수기호 → 공백 정규화
    n = (name_core or "").lower()
    n = _SPECIAL_RE.sub(" ", n)
    n = _WHITESPACE_RE.sub(" ", n).strip()

    # pack_qty: 소수점 1자리 round. None → ""
    if pack_qty is not None:
        q = f"{round(float(pack_qty), 1):.1f}"
    else:
        q = ""

    # pack_unit: 소문자
    u = (pack_unit or "").strip().lower()

    return f"{b}|{n}|{q}|{u}"
