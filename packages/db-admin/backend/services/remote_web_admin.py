"""HTTP client from local db-admin to the deployed web-api management surface."""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


class RemoteWebAdminError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    return os.getenv("WALLETSAVIOR_REMOTE_ADMIN_URL", "http://127.0.0.1:8000").rstrip("/") + "/"


def _token() -> str:
    token = os.getenv("WALLETSAVIOR_REMOTE_ADMIN_TOKEN", "").strip()
    if not token:
        raise RemoteWebAdminError(
            "WALLETSAVIOR_REMOTE_ADMIN_TOKEN이 설정되지 않았습니다",
            status_code=503,
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {_token()}",
    }


def _decode_error(payload: bytes, fallback: str) -> str:
    try:
        data = json.loads(payload.decode("utf-8"))
        return str(data.get("detail") or data.get("message") or fallback)
    except Exception:
        return fallback


def _request_json(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    timeout: float = 15.0,
) -> dict:
    url = urljoin(_base_url(), path.lstrip("/"))
    if params:
        clean = {key: value for key, value in params.items() if value not in (None, "")}
        if clean:
            url = f"{url}?{urlencode(clean)}"

    payload = None
    headers = _headers()
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=payload, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        raw = exc.read()
        raise RemoteWebAdminError(
            _decode_error(raw, f"HTTP {exc.code}"),
            status_code=exc.code,
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RemoteWebAdminError(f"원격 웹 API 연결 실패: {exc}", status_code=503) from exc


def list_community_posts(**params) -> dict:
    return _request_json("GET", "api/admin/remote/community/posts", params=params)


def get_community_post(post_id: int) -> dict:
    return _request_json("GET", f"api/admin/remote/community/posts/{post_id}")


def delete_community_post(post_id: int) -> dict:
    return _request_json("DELETE", f"api/admin/remote/community/posts/{post_id}")


def restore_community_post(post_id: int) -> dict:
    return _request_json("POST", f"api/admin/remote/community/posts/{post_id}/restore", body={})


def delete_community_comment(comment_id: int) -> dict:
    return _request_json("DELETE", f"api/admin/remote/community/comments/{comment_id}")


def restore_community_comment(comment_id: int) -> dict:
    return _request_json("POST", f"api/admin/remote/community/comments/{comment_id}/restore", body={})


def ban_community_user(user_id: int) -> dict:
    return _request_json("POST", f"api/admin/remote/community/users/{user_id}/ban", body={})


def unban_community_user(user_id: int) -> dict:
    return _request_json("POST", f"api/admin/remote/community/users/{user_id}/unban", body={})


def upload_snapshot(kind: str, path: Path | str, *, timeout: float = 120.0) -> dict:
    source = Path(path).resolve()
    if not source.is_file():
        raise RemoteWebAdminError(f"snapshot 파일을 찾을 수 없습니다: {source}", status_code=400)

    parsed = urlparse(_base_url())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RemoteWebAdminError("WALLETSAVIOR_REMOTE_ADMIN_URL 형식이 올바르지 않습니다", status_code=503)

    prefix = parsed.path.rstrip("/")
    endpoint = f"{prefix}/api/admin/remote/snapshots/{kind}"
    if parsed.query:
        raise RemoteWebAdminError("원격 관리 URL에는 query string을 넣을 수 없습니다", status_code=503)

    connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_cls(parsed.hostname, parsed.port, timeout=timeout)
    size = source.stat().st_size

    try:
        connection.putrequest("PUT", endpoint)
        connection.putheader("Authorization", f"Bearer {_token()}")
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("Content-Length", str(size))
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
            raise RemoteWebAdminError(
                _decode_error(raw, f"HTTP {response.status}"),
                status_code=response.status,
            )
        return json.loads(raw.decode("utf-8")) if raw else {}
    except RemoteWebAdminError:
        raise
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RemoteWebAdminError(f"snapshot 업로드 실패: {exc}", status_code=503) from exc
    finally:
        connection.close()
