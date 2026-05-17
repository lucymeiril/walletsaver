"""Add the tools/ directory to sys.path so test modules can import from it."""
import sys
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parents[1])
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
