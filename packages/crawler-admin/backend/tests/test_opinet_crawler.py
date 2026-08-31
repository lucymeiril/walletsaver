from __future__ import annotations

from crawlers.opinet.crawler import OpinetCrawler
from crawlers.opinet.parser import parse_opinet_public_region_html


def _public_html() -> str:
    args = [""] * 38
    args[2] = "1789"
    args[3] = "1774"
    args[7] = "2026-08-30 17:59:31"
    args[8] = "2026-08-30 17:58:41"
    args[11] = "299700.00000"
    args[12] = "564256.00000"
    args[21] = "HDO"
    args[22] = "(주)원흥 원당동지점"
    args[23] = "HD현대오일뱅크"
    args[25] = "경기 고양시 덕양구 호국로 1113"
    args[31] = "A0005266"
    href = "javascript:fn_osPop(" + ",".join(f"'{value}'" for value in args) + ");"
    return f"""
    <html><body><table id="os_price1"><tbody>
      <tr><th>주유소명</th><th>휘발유</th><th>경유</th></tr>
      <tr>
        <td class="rlist" title="(주)원흥 원당동지점">
          <img alt="HD현대오일뱅크" />
          <a href="{href}">(주)원흥 원당동지점</a>
          <span class="ic ico_self"><span>셀프</span></span>
        </td>
        <td class="price">1,789</td><td class="price">1,774</td>
      </tr>
    </tbody></table></body></html>
    """


def test_current_public_region_table_parser_preserves_station_evidence():
    rows = parse_opinet_public_region_html(_public_html())

    assert len(rows) == 1
    assert rows[0]["opinet_id"] == "A0005266"
    assert rows[0]["address"] == "경기 고양시 덕양구 호국로 1113"
    assert rows[0]["gasoline_regular"] == "1,789"
    assert rows[0]["diesel"] == "1,774"
    assert rows[0]["self_service"] is True


def test_public_fallback_is_explicit_and_uses_fresh_cache_without_network(tmp_path, monkeypatch):
    cache = tmp_path / "opinet.html"
    cache.write_text(_public_html(), encoding="utf-8")
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network should not be used")),
    )

    disabled = OpinetCrawler(api_key="", public_fallback_enabled=False, public_cache_path=cache)
    assert disabled.live_crawl() == []

    crawler = OpinetCrawler(api_key="", public_fallback_enabled=True, public_cache_path=cache)
    records = crawler.live_crawl()

    assert len(records) == 1
    assert records[0].station_code == "A0005266"
    assert records[0].name == "(주)원흥 원당동지점"
    assert {price.fuel_type: price.price for price in records[0].prices} == {
        "gasoline": 1789,
        "diesel": 1774,
    }
    assert records[0].lat is not None
    assert records[0].lng is not None
