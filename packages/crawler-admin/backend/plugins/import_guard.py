"""
Import whitelist hook for plugin sandboxing.

Hooks into Python's import system to block dangerous modules
when executing plugin code. This is a Phase 1 mitigation —
full subprocess isolation (Phase 2) is recommended for production.
"""

import builtins
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Modules that plugins are NEVER allowed to import
BLOCKED_MODULES: frozenset[str] = frozenset({
    "os",
    "sys",
    "subprocess",
    "shutil",
    "pathlib",
    "ctypes",
    "importlib",
    "code",
    "codeop",
    "compile",
    "compileall",
    "socket",
    "socketserver",
    "http.server",
    "xmlrpc",
    "exec",
    "eval",
    "pickle",
    "shelve",
    "marshal",
    "signal",
    "multiprocessing",
    "threading",
    "_thread",
    "tempfile",
    "glob",
    "fnmatch",
    "io",
})

# Modules that plugins ARE allowed to import
ALLOWED_MODULES: frozenset[str] = frozenset({
    "json",
    "re",
    "math",
    "datetime",
    "time",
    "hashlib",
    "hmac",
    "base64",
    "urllib.parse",
    "html",
    "collections",
    "dataclasses",
    "typing",
    "enum",
    "functools",
    "itertools",
    "operator",
    "copy",
    "decimal",
    "fractions",
    "statistics",
    "string",
    "textwrap",
    "unicodedata",
    "abc",
    "logging",
    "requests",
    "httpx",
    "aiohttp",
    "bs4",
    "lxml",
    "selectolax",
    "yaml",
    "csv",
    "plugins.plugin_interface",
    "engine",
})


def _is_module_allowed(module_name: str) -> bool:
    """Check if a module import should be allowed for plugin code."""
    top_level = module_name.split(".")[0]

    # Explicitly blocked takes priority
    if top_level in BLOCKED_MODULES or module_name in BLOCKED_MODULES:
        return False

    # Allow internal/private CPython modules (implementation details of stdlib)
    if top_level.startswith("_"):
        return True

    if top_level in ALLOWED_MODULES or module_name in ALLOWED_MODULES:
        return True

    # Unknown modules — block by default (whitelist approach)
    return False


@contextmanager
def guarded_imports(plugin_name: str):
    """
    Context manager that installs an import guard while plugin code executes.

    Usage:
        with guarded_imports("yogiyo"):
            spec.loader.exec_module(module)
    """
    original_import = builtins.__import__

    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level > 0:
            return original_import(name, globals, locals, fromlist, level)

        if not _is_module_allowed(name):
            logger.warning(
                "Plugin '%s' blocked from importing '%s'", plugin_name, name
            )
            raise ImportError(
                f"Plugin '{plugin_name}' is not allowed to import '{name}'. "
                f"Contact admin to add '{name}' to the allowed module list."
            )
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _restricted_import
    try:
        yield
    finally:
        builtins.__import__ = original_import
