"""Runtime safety helpers for ai-admin backend processes."""
from __future__ import annotations

import os
import sys


def configure_utf8_runtime() -> None:
    """Make backend startup and provider calls safe under ASCII stdio/env.

    Some validation agents launch ai-admin from non-interactive shells where
    Python's stdio encoding can fall back to ASCII. Configure the process before
    Uvicorn/provider code can log Korean prompts or product names.
    """
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
