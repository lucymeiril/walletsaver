"""Wire-level HTTP interceptor for AI provider calls.

Attaches to the httpx client inside the google-genai SDK via event_hooks to
capture every outbound request and inbound response at the transport layer.

Usage
-----
Wire logging is enabled when the environment variable
``WALLETSAVIOR_WIRE_LOG_PATH`` is set to an absolute or relative file path
ending in ``.jsonl``.  Each line written to that file is a JSON object with
fields: timestamp, url, domain, status, latency_ms, req_prompt_hash,
resp_size_bytes.

The ``WALLETSAVIOR_AI_LIVE_FORCE`` environment variable (value ``1``) is a
correctness gate: if it is set and the wire logger was attached but captured
**zero** successful calls at process exit, a warning is printed to stderr.
This prevents silent cache/fixture re-use from masquerading as live runs.

Design note
-----------
httpx.Client supports ``event_hooks`` dicts with ``"request"`` and
``"response"`` lists.  The google-genai SDK's internal ``SyncHttpxClient``
extends ``httpx.Client``; after a ``genai.Client(...)`` is constructed its
internal ``_api_client._httpx_client`` is the live httpx client we inject
hooks into.  This is a private attribute, but it is the only portable way to
intercept at wire level without forking the SDK.

The ``_req_start_times`` dict maps ``httpx.Request`` id → start time.  A
``threading.Lock`` protects concurrent batch calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("walletsavior.wire_logger")

_GOOGLE_API_DOMAIN = "generativelanguage.googleapis.com"


def _prompt_hash(body: bytes | None) -> str:
    """Return a short SHA-256 prefix of the request body — not the full text."""
    if not body:
        return "empty"
    return hashlib.sha256(body).hexdigest()[:16]


class WireLogger:
    """Attaches httpx event hooks and streams wire-log records to a JSONL file.

    Parameters
    ----------
    log_path:
        Absolute path to the ``.jsonl`` output file.  Parent directory is
        created if it does not exist.
    force_live_flag:
        When True the instance keeps a call counter and warns on process exit
        if no successful calls were recorded.
    """

    def __init__(
        self,
        log_path: str | Path,
        *,
        force_live_flag: bool = False,
    ) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self._path.open("a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()
        self._req_start_times: dict[int, float] = {}
        self._req_bodies: dict[int, bytes | None] = {}
        self._ok_calls: int = 0
        self._total_calls: int = 0
        self._force_live_flag = force_live_flag
        if force_live_flag:
            import atexit
            atexit.register(self._exit_check)

    # ------------------------------------------------------------------
    # httpx event hooks
    # ------------------------------------------------------------------

    def on_request(self, request: Any) -> None:
        req_id = id(request)
        with self._lock:
            self._req_start_times[req_id] = time.perf_counter()
            # capture body bytes for hashing
            try:
                body: bytes | None = request.content
            except Exception:
                body = None
            self._req_bodies[req_id] = body

    def on_response(self, response: Any) -> None:
        req_id = id(response.request)
        with self._lock:
            t_start = self._req_start_times.pop(req_id, None)
            body = self._req_bodies.pop(req_id, None)
        latency_ms: float | None = None
        if t_start is not None:
            latency_ms = round((time.perf_counter() - t_start) * 1000, 1)

        url = str(getattr(response, "url", "") or "")
        status = getattr(response, "status_code", 0)
        resp_size: int = 0
        try:
            resp_size = len(response.content)
        except Exception:
            pass

        record: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": url,
            "domain": _GOOGLE_API_DOMAIN if _GOOGLE_API_DOMAIN in url else url.split("/")[2] if "://" in url else url,
            "status": status,
            "latency_ms": latency_ms,
            "req_prompt_hash": _prompt_hash(body),
            "resp_size_bytes": resp_size,
            "is_google_genai": _GOOGLE_API_DOMAIN in url,
        }
        with self._lock:
            self._total_calls += 1
            if 200 <= status < 300:
                self._ok_calls += 1
            if status >= 400:
                logger.warning(
                    "[WIRE] HTTP %s to %s (latency %.0fms) — non-2xx response",
                    status, record["domain"], latency_ms or 0,
                )
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def attach(self, httpx_client: Any) -> None:
        """Inject event hooks into an existing httpx.Client instance."""
        hooks = getattr(httpx_client, "event_hooks", None)
        if hooks is None:
            logger.warning("[WIRE] httpx client has no event_hooks — wire logging disabled")
            return
        if self.on_request not in hooks.get("request", []):
            hooks.setdefault("request", []).append(self.on_request)
        if self.on_response not in hooks.get("response", []):
            hooks.setdefault("response", []).append(self.on_response)
        logger.info(
            "[WIRE] Wire logger attached → %s",
            self._path,
        )

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "wire_log_path": str(self._path),
                "total_calls": self._total_calls,
                "ok_calls": self._ok_calls,
                "failed_calls": self._total_calls - self._ok_calls,
            }

    def _exit_check(self) -> None:
        import sys
        with self._lock:
            ok = self._ok_calls
            total = self._total_calls
        if total == 0:
            print(
                "\n[WALLETSAVIOR WIRE LOGGER] ⚠️  FORCE-LIVE MODE: "
                "0 HTTP calls were captured — "
                "no real provider calls occurred. "
                "This run produced zero wire-level evidence of Google API calls.",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(
                f"\n[WALLETSAVIOR WIRE LOGGER] ✅ FORCE-LIVE MODE: "
                f"{ok}/{total} successful HTTP calls captured → {self._path}",
                file=sys.stderr,
                flush=True,
            )


def get_wire_logger_from_env() -> WireLogger | None:
    """Return a WireLogger if WALLETSAVIOR_WIRE_LOG_PATH is set, else None."""
    path = os.environ.get("WALLETSAVIOR_WIRE_LOG_PATH", "").strip()
    if not path:
        return None
    force = os.environ.get("WALLETSAVIOR_AI_LIVE_FORCE", "").strip() == "1"
    wl = WireLogger(path, force_live_flag=force)
    logger.info("[WIRE] Wire logger initialised: path=%s force=%s", path, force)
    return wl


def attach_wire_logger_to_genai_client(genai_client: Any, wire_logger: WireLogger) -> bool:
    """Inject WireLogger hooks into a google-genai Client's internal httpx client.

    Returns True if injection succeeded, False otherwise.
    The attribute path ``genai_client._api_client._httpx_client`` is a private
    implementation detail of google-genai ≥1.0 and may change across versions.
    """
    try:
        api_client = getattr(genai_client, "_api_client", None)
        if api_client is None:
            logger.warning("[WIRE] genai_client has no _api_client")
            return False
        httpx_client = getattr(api_client, "_httpx_client", None)
        if httpx_client is None:
            logger.warning("[WIRE] api_client has no _httpx_client")
            return False
        wire_logger.attach(httpx_client)
        return True
    except Exception as exc:
        logger.warning("[WIRE] Could not attach wire logger: %s", exc)
        return False
