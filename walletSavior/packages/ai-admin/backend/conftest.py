"""pytest 설정 — backend/와 shared/ 경로를 sys.path에 추가한다."""
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

shared_dir = backend_dir.parent.parent / "shared"
if str(shared_dir) not in sys.path:
    sys.path.insert(0, str(shared_dir))
