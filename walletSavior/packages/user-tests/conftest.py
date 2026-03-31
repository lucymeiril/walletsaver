import sys
import os
import pytest

# user-tests 디렉토리를 모듈 경로에 추가 (하이픈 이름 대응)
sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture
def all_pages():
    """웹사이트 전체 페이지 목록"""
    return ["Home", "Hotdeal", "Price", "Mart", "Local", "Community"]


@pytest.fixture
def admin_pages():
    """관리자 페이지 목록"""
    return {
        "crawler-admin": ["Dashboard", "Crawlers", "Logs", "Plugins", "Schedule"],
        "db-admin": ["Dashboard", "Analytics", "Categories", "Keywords", "Prices", "Products"],
    }


@pytest.fixture
def breakpoints():
    """반응형 디자인 브레이크포인트"""
    return {
        "mobile": [360, 390, 414],
        "tablet": [768, 1024],
        "desktop": [1280, 1440, 1920],
    }


@pytest.fixture
def wcag_contrast_ratios():
    """WCAG 2.1 AA 기준 대비율"""
    return {
        "normal_text": 4.5,
        "large_text": 3.0,
        "ui_components": 3.0,
    }
