"""플러그인 관리 라우트 — plugin.yaml 기반 실제 플러그인 목록 및 상태 관리."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

# 플러그인 상태 저장 파일
_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _CONFIG_DIR / "plugin_state.json"
_CRAWLERS_DIR = _CONFIG_DIR / "crawlers"


def _load_state() -> dict[str, str]:
    """플러그인 활성/비활성 상태를 파일에서 로드."""
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, str]) -> None:
    """플러그인 상태를 파일에 저장."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"플러그인 상태 저장 실패: {e}")


def _get_running_crawlers() -> set[str]:
    """현재 실행 중인 크롤러 ID 목록 반환."""
    try:
        from api.routes.crawlers import _crawl_results
        return {
            cid for cid, info in _crawl_results.items()
            if info.get("status") == "running"
        }
    except Exception:
        return set()


def _find_plugin_yaml(plugin_id: str) -> Path | None:
    """플러그인 ID에 해당하는 plugin.yaml 경로 반환."""
    if not _CRAWLERS_DIR.exists():
        return None
    for yaml_path in _CRAWLERS_DIR.rglob("plugin.yaml"):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            if config.get("name", yaml_path.parent.name) == plugin_id:
                return yaml_path
        except Exception:
            continue
    return None


def _scan_plugins() -> list[dict[str, Any]]:
    """crawlers/ 디렉토리의 모든 plugin.yaml을 스캔."""
    plugins = []
    state = _load_state()
    running = _get_running_crawlers()

    if not _CRAWLERS_DIR.exists():
        return plugins

    for yaml_path in sorted(_CRAWLERS_DIR.rglob("plugin.yaml")):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

            name = config.get("name", yaml_path.parent.name)
            target = config.get("target", {})
            if isinstance(target, str):
                target = {"url": target}
            schedule = config.get("schedule", {})
            if isinstance(schedule, str):
                schedule = {"cron": schedule}

            plugins.append({
                "id": name,
                "name": config.get("display_name", name),
                "version": config.get("version", "0.0.0"),
                "description": config.get("description", ""),
                "category": config.get("category", config.get("group", "unknown")),
                "status": state.get(name, "active"),
                "isRunning": name in running,
                "author": "WalletSavior",
                "target_url": target.get("url", ""),
                "strategy": target.get("strategy", ""),
                "difficulty": target.get("difficulty", 1),
                "delay": config.get("delay", 1.0),
                "max_items": config.get("max_items", 100),
                "schedule_cron": schedule.get("cron", "manual"),
                "retry_count": schedule.get("retry_count", 0),
                "output_model": config.get("output", {}).get("model", ""),
                "config": yaml.dump(config, allow_unicode=True, default_flow_style=False),
                "path": str(yaml_path.parent),
            })
        except Exception as e:
            logger.warning(f"plugin.yaml 읽기 실패 {yaml_path}: {e}")

    return plugins


@router.get("")
async def list_plugins():
    """등록된 플러그인 목록 (plugin.yaml 기반)."""
    return {"plugins": _scan_plugins()}


class PluginToggleRequest(BaseModel):
    status: str  # "active" or "inactive"


@router.put("/{plugin_id}/status")
async def toggle_plugin(plugin_id: str, body: PluginToggleRequest):
    """플러그인 활성/비활성 토글 — 상태를 파일에 저장."""
    if body.status not in ("active", "inactive"):
        raise HTTPException(400, "status must be 'active' or 'inactive'")

    state = _load_state()
    state[plugin_id] = body.status
    _save_state(state)

    return {"plugin_id": plugin_id, "status": body.status}


class PluginSettingsUpdate(BaseModel):
    target_url: Optional[str] = None
    delay: Optional[float] = None
    max_items: Optional[int] = None


@router.put("/{plugin_id}/settings")
async def update_plugin_settings(plugin_id: str, body: PluginSettingsUpdate):
    """플러그인 설정 업데이트 — plugin.yaml 파일 직접 수정."""
    yaml_path = _find_plugin_yaml(plugin_id)
    if not yaml_path:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        raise HTTPException(500, f"plugin.yaml 읽기 실패: {e}")

    # target 블록 업데이트
    if body.target_url is not None:
        target = config.get("target", {})
        if isinstance(target, str):
            target = {"url": target}
        target["url"] = body.target_url
        config["target"] = target

    if body.delay is not None:
        config["delay"] = body.delay

    if body.max_items is not None:
        config["max_items"] = body.max_items

    try:
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise HTTPException(500, f"plugin.yaml 저장 실패: {e}")

    return {"plugin_id": plugin_id, "settings": {
        "target_url": body.target_url,
        "delay": body.delay,
        "max_items": body.max_items,
    }}
