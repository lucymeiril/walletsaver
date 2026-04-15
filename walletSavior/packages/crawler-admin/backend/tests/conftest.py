"""
테스트 설정 — @pytest.mark.live 테스트를 기본 스킵 처리.

라이브 크롤링 테스트(실제 네트워크 + Playwright 브라우저)는
CI/로컬에서 기본 실행 시 hang을 유발할 수 있으므로
--run-live 옵션을 줘야만 실행한다.

사용법:
    py -m pytest tests/               # live 테스트 스킵
    py -m pytest tests/ --run-live     # live 테스트 포함
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="라이브 크롤링 테스트 실행 (네트워크/브라우저 필요)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="--run-live 옵션 필요")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
