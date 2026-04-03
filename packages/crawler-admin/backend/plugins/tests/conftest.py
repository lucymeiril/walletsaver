"""
pytest 설정 — plugins 테스트용.

shared/core, backend 모듈을 올바르게 import 할 수 있도록 sys.path를 구성한다.
"""

import sys
from pathlib import Path

# backend/ 디렉터리를 sys.path에 추가
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# shared/ 디렉터리를 sys.path에 추가
shared_dir = backend_dir.parent.parent / "shared"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))
