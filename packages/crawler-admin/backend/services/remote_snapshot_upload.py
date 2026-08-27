"""Optional direct snapshot upload from crawler-admin to deployed web-api.

This keeps crawler-owned data out of db-admin: when the remote URL and token are
configured, crawler-admin can publish its own replaceable snapshots directly.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
from urllib.parse import urlparse


class RemoteSnapshotUploadError(RuntimeError):
    pass


def remote_publish_configured() -> bool:
    return bool(
        os.getenv("WALLETSAVIOR_REMOTE_ADMIN_URL", "").strip()
        and os.getenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "").strip()
    )


def upload_snapshot(kind: str, path: str | Path, *, timeout: float = 120.0) -> dict:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise RemoteSnapshotUploadError(f"snapshot 파일을 찾을 수 없습니다: {source}")

    base_url = os.getenv("WALLETSAVIOR_REMOTE_ADMIN_URL", "").strip().rstrip("/")
    token = os.getenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "").strip()
    if not base_url or not token:
        raise RemoteSnapshotUploadError(
            "WALLETSAVIOR_REMOTE_ADMIN_URL/TOKEN이 모두 설정되어야 합니다"
        )

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query:
        raise RemoteSnapshotUploadError("WALLETSAVIOR_REMOTE_ADMIN_URL 형식이 올바르지 않습니다")

    prefix = parsed.path.rstrip("/")
    endpoint = f"{prefix}/api/admin/remote/snapshots/{kind}"
    connection_cls = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    connection = connection_cls(parsed.hostname, parsed.port, timeout=timeout)

    try:
        connection.putrequest("PUT", endpoint)
        connection.putheader("Authorization", f"Bearer {token}")
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(source.stat().st_size))
        connection.endheaders()

        with source.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                connection.send(chunk)

        response = connection.getresponse()
        raw = response.read()
        if response.status < 200 or response.status >= 300:
            detail = f"HTTP {response.status}"
            try:
                payload = json.loads(raw.decode("utf-8"))
                detail = str(payload.get("detail") or payload.get("message") or detail)
            except Exception:
                pass
            raise RemoteSnapshotUploadError(f"snapshot 업로드 실패: {detail}")
        return json.loads(raw.decode("utf-8")) if raw else {}
    except RemoteSnapshotUploadError:
        raise
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RemoteSnapshotUploadError(f"snapshot 업로드 연결 실패: {exc}") from exc
    finally:
        connection.close()


__all__ = ["RemoteSnapshotUploadError", "remote_publish_configured", "upload_snapshot"]
