"""conftest.py — price_data 테스트 패키지 경로 설정."""

import sys
import os

# price_data 패키지가 위치한 backend/ 디렉토리를 path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
