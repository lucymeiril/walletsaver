"""
pytest 설정 — 모듈 경로 구성.

db-admin/backend/ 모듈을 올바르게 import 할 수 있도록 sys.path를 구성한다.
"""

import sys
from pathlib import Path

# backend/ 디렉터리 자체를 sys.path에 추가 (storage, services 등 import 가능)
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
# Ensure db-admin backend is first in path (avoid conflicts with crawler-admin)
elif sys.path[0] != str(backend_dir):
    sys.path.remove(str(backend_dir))
    sys.path.insert(0, str(backend_dir))

# shared/ 디렉터리를 sys.path에 추가 (core.models, core.contracts 등 import 가능)
shared_dir = backend_dir.parent.parent / "shared"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))

# Flush cached config from other packages (crawler-admin) to avoid import conflicts
if "config" in sys.modules:
    cached_config = sys.modules["config"]
    if hasattr(cached_config, "__file__") and cached_config.__file__:
        if str(backend_dir) not in cached_config.__file__:
            del sys.modules["config"]
