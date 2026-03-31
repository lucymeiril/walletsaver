"""crawlers.hotdeals.cocodal 패키지.

NOTE: cocodal.in / cocodal.co.kr 사이트가 현재 접속 불가 상태.
      향후 사이트 복구 시 크롤러 활성화 예정.
"""

plugin_info = {
    "name": "코코달",
    "version": "1.0.0",
    "group": "hotdeals",
    "description": "코코달 핫딜 크롤러 — 현재 사이트 접속 불가 (비활성)",
    "target_url": "https://cocodal.in/",
    "strategies": ["requests"],
    "status": "inactive",
}
