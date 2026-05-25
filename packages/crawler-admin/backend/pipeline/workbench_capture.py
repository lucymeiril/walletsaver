"""
워크밴치 산출물 4등급 — crawler-FINAL §5-C.

한 WorkbenchCapture 세션 → 4종 자식 객체, 각자 lifecycle/TTL/검토상태:
- InstantHarvest   : 24h, AI/DB 검증 후 raw record 로 승격
- TrackedUrlEntry  : tracked_urls 영구 등록 (lifecycle = TrackedUrlStore)
- SessionAsset    : 쿠키 jar / persistent profile / HAR 일부 — 다음 cron 재사용
- Fixture         : HTML/JSON 스냅샷 — drift baseline + 회귀 테스트

본 모듈은 *데이터 모델 + 분리/저장 디렉토리 규약* 만 제공. UI/Playwright 호출은
pipeline.operator_browser_session 이 담당하고 ingest_operator_capture 가 합쳐 호출한다.

회피 코드가 아니다 — 워크밴치는 1급 시민 (FINAL §5-A).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class CaptureGrade(str, Enum):
    INSTANT_HARVEST = "instant_harvest"
    TRACKED_URL_ENTRY = "tracked_url_entry"
    SESSION_ASSET = "session_asset"
    FIXTURE = "fixture"


@dataclass
class InstantHarvest:
    """지금 화면의 상품 카드를 raw item 후보로 즉시 수확. TTL 24h."""
    items: list[dict[str, Any]] = field(default_factory=list)
    captured_at: float = field(default_factory=time.time)
    ttl_seconds: int = 24 * 3600

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return (now - self.captured_at) > self.ttl_seconds


@dataclass
class TrackedUrlEntry:
    """tracked_urls 영구 등록 후보. lifecycle 은 TrackedUrlStore 가 관장."""
    url: str
    title_hint: str = ""
    refresh_tier_hint: str = "daily"
    is_sponsored_suspicion: bool = False


@dataclass
class SessionAsset:
    """쿠키 jar / persistent profile / HAR 부분 — 다음 cron 재사용용."""
    profile_id: str
    cookies_jar_path: Optional[str] = None     # 디스크 경로 또는 raw
    har_excerpt_path: Optional[str] = None
    login_state_probe_ok: bool = True
    region_state_probe_ok: bool = True
    profile_age_seconds: float = 0.0


@dataclass
class Fixture:
    """HTML/JSON 스냅샷 — drift baseline + 회귀 테스트."""
    fixture_id: str
    content_path: str          # 디스크 경로
    content_type: str = "html"  # html | json | har
    selector_baseline: dict[str, Any] = field(default_factory=dict)
    captured_at: float = field(default_factory=time.time)


@dataclass
class WorkbenchCapture:
    """한 세션의 4등급 부분 산출. 운영자가 1회 조작 후 분리 저장."""
    capture_id: str
    source_id: str
    url: str
    operator_id: Optional[str] = None
    captured_at: float = field(default_factory=time.time)
    instant_harvest: Optional[InstantHarvest] = None
    tracked_url_entries: list[TrackedUrlEntry] = field(default_factory=list)
    session_asset: Optional[SessionAsset] = None
    fixture: Optional[Fixture] = None
    notes: str = ""

    @staticmethod
    def new(source_id: str, url: str, operator_id: Optional[str] = None) -> "WorkbenchCapture":
        return WorkbenchCapture(
            capture_id=str(uuid.uuid4()),
            source_id=source_id,
            url=url,
            operator_id=operator_id,
        )

    def grades_present(self) -> list[CaptureGrade]:
        present: list[CaptureGrade] = []
        if self.instant_harvest is not None:
            present.append(CaptureGrade.INSTANT_HARVEST)
        if self.tracked_url_entries:
            present.append(CaptureGrade.TRACKED_URL_ENTRY)
        if self.session_asset is not None:
            present.append(CaptureGrade.SESSION_ASSET)
        if self.fixture is not None:
            present.append(CaptureGrade.FIXTURE)
        return present


class WorkbenchCaptureStore:
    """디스크 저장소. crawlers/<source>/_workbench/<capture_id>/ 아래에 부분 저장."""

    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _capture_dir(self, source_id: str, capture_id: str) -> Path:
        d = self.root / source_id / capture_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, capture: WorkbenchCapture) -> Path:
        """전체 capture 를 JSON 으로 직렬화."""
        d = self._capture_dir(capture.source_id, capture.capture_id)
        manifest_path = d / "capture.json"
        manifest_path.write_text(
            json.dumps(_to_jsonable(capture), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest_path

    def load(self, source_id: str, capture_id: str) -> Optional[WorkbenchCapture]:
        manifest_path = self.root / source_id / capture_id / "capture.json"
        if not manifest_path.exists():
            return None
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return _from_jsonable(data)


def _to_jsonable(c: WorkbenchCapture) -> dict[str, Any]:
    out = asdict(c)
    return out


def _from_jsonable(data: dict[str, Any]) -> WorkbenchCapture:
    ih = data.get("instant_harvest")
    tu = data.get("tracked_url_entries") or []
    sa = data.get("session_asset")
    fx = data.get("fixture")
    return WorkbenchCapture(
        capture_id=data["capture_id"],
        source_id=data["source_id"],
        url=data["url"],
        operator_id=data.get("operator_id"),
        captured_at=data.get("captured_at", time.time()),
        instant_harvest=InstantHarvest(**ih) if ih else None,
        tracked_url_entries=[TrackedUrlEntry(**t) for t in tu],
        session_asset=SessionAsset(**sa) if sa else None,
        fixture=Fixture(**fx) if fx else None,
        notes=data.get("notes", ""),
    )
