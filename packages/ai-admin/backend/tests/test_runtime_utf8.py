"""Backend startup UTF-8 safety regression tests."""
from __future__ import annotations

import io
import sys

from api.app import create_app


def test_create_app_reconfigures_ascii_stdio_for_korean_startup(
    monkeypatch,
) -> None:
    ascii_stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    ascii_stderr = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    monkeypatch.setattr(sys, "stdout", ascii_stdout)
    monkeypatch.setattr(sys, "stderr", ascii_stderr)

    app = create_app()
    print("이마트 친환경 대추방울토마토")
    sys.stderr.write("한우 양념 소불고기\n")

    assert app.title == "WalletSavior AI 관리"
    assert sys.stdout.encoding.lower().replace("_", "-") == "utf-8"
    assert sys.stderr.encoding.lower().replace("_", "-") == "utf-8"
