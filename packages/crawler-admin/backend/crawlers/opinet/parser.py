"""WalletSavior Phase F4 — 오피넷 저가주유소 HTML 파서.

오피넷 searRgSelect.do (지역별 저가주유소 검색) 응답 HTML을 파싱한다.

테이블 컬럼 순서 (오피넷 표준 레이아웃):
    0: 순위
    1: 상호명 (링크 내 상호명 + JS 인자로 opinet_id)
    2: 브랜드
    3: 주소
    4: 셀프여부
    5: 휘발유 가격 (원/L)
    6: 고급휘발유 가격
    7: 경유 가격
    8: LPG 가격

의존성: beautifulsoup4 (html.parser — 외부 lxml 불필요)
"""

from __future__ import annotations

import re
from typing import Optional

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:
    _HAS_BS4 = False


def _require_bs4() -> None:
    if not _HAS_BS4:
        raise ImportError(
            "beautifulsoup4가 필요합니다. pip install beautifulsoup4"
        )


def _text(cell) -> str:
    """BeautifulSoup cell → stripped text."""
    return cell.get_text(strip=True)


def _extract_opinet_id(cell) -> Optional[str]:
    """상호명 cell에서 JS 링크 인자 추출.

    oilStDetail.do?seq=A0012345 또는 goStation('A0012345') 패턴.
    """
    link = cell.find("a")
    if not link:
        return None
    href = link.get("href", "")
    onclick = link.get("onclick", "")
    # href 패턴: seq=A0012345
    m = re.search(r"seq=([A-Z0-9]+)", href)
    if m:
        return m.group(1)
    # onclick 패턴: goStation('A0012345')
    m = re.search(r"['\"]([A-Z][0-9]{7,})['\"]", onclick)
    if m:
        return m.group(1)
    # href contains station id directly
    m = re.search(r"['\"]([A-Z][0-9]{7,})['\"]", href)
    if m:
        return m.group(1)
    return None


def parse_opinet_low_price_html(
    html: str,
    source_url: str = "https://www.opinet.co.kr/searRgSelect.do",
) -> list[dict]:
    """오피넷 저가주유소 테이블 HTML → raw dict 리스트.

    Args:
        html: searRgSelect.do 응답 HTML 전문.
        source_url: 수집 출처 URL (기록용).

    Returns:
        [
            {
                "name": str,
                "brand": str,
                "address": str,
                "self_service": bool,
                "gasoline_regular": str | None,  # "1,598" 또는 "-"
                "gasoline_premium": str | None,
                "diesel": str | None,
                "lpg": str | None,
                "opinet_id": str | None,
                "source_url": str,
            },
            ...
        ]
    """
    _require_bs4()

    soup = BeautifulSoup(html, "html.parser")

    # tbody 탐색: id="tb_sub" 우선, 없으면 첫 번째 tbody
    tbody = (
        soup.find("tbody", id="tb_sub")
        or soup.find("tbody", id="tb_body")
        or soup.find("tbody")
    )
    if not tbody:
        return []

    results: list[dict] = []
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 7:
            continue

        # 순위 행인지 확인 (colspan=9 같은 '결과 없음' 행 스킵)
        if cells[0].get("colspan"):
            continue

        name_cell = cells[1]
        name_link = name_cell.find("a")
        name = name_link.get_text(strip=True) if name_link else _text(name_cell)
        if not name:
            continue

        opinet_id = _extract_opinet_id(name_cell)
        brand = _text(cells[2])
        address = _text(cells[3])
        self_txt = _text(cells[4])
        self_service = "셀프" in self_txt

        gasoline_regular = _text(cells[5]) if len(cells) > 5 else None
        gasoline_premium = _text(cells[6]) if len(cells) > 6 else None
        diesel = _text(cells[7]) if len(cells) > 7 else None
        lpg = _text(cells[8]) if len(cells) > 8 else None

        results.append(
            {
                "name": name,
                "brand": brand,
                "address": address,
                "self_service": self_service,
                "gasoline_regular": gasoline_regular,
                "gasoline_premium": gasoline_premium,
                "diesel": diesel,
                "lpg": lpg,
                "opinet_id": opinet_id,
                "source_url": source_url,
            }
        )

    return results
