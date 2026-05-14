"""Local secret alias resolution for provider adapters.

Only alias names are stored in provider config. Secret values are resolved at
runtime from local, gitignored ``.env`` files before falling back to process env.
"""
from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[2]

DEFAULT_ENV_PATHS = (
    BACKEND_DIR / ".env",
    REPO_ROOT / ".env",
)


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_optional_quotes(value.strip())
    return values


def resolve_secret_alias(
    alias: str,
    env_paths: tuple[Path, ...] | list[Path] | None = None,
) -> str | None:
    """Resolve ``alias`` from local .env files first, then process env."""
    paths = DEFAULT_ENV_PATHS if env_paths is None else env_paths
    for path in paths:
        value = _parse_env_file(Path(path)).get(alias)
        if value:
            return value
    return os.getenv(alias) or None


def env_setup_hint(alias: str) -> str:
    """Return a setup hint that names the alias but never the secret value."""
    locations = " or ".join(str(path) for path in DEFAULT_ENV_PATHS)
    return f"missing API key for alias '{alias}'. Add {alias} to {locations}"
