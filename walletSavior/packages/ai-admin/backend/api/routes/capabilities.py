"""capabilities 라우트 — shared 계약의 역할/provider 목록을 노출한다.

provider 구현은 아직 없으므로 enum 값과 사람이 읽을 수 있는 라벨만 반환하고,
지원 여부(supported)는 모두 False로 표시해 호출자가 미구현임을 명확히 알 수 있게 한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from core.contracts.ai_pipeline import AIWorkerRole, ProviderKind

router = APIRouter(prefix="/api", tags=["capabilities"])


_ROLE_LABELS: dict[AIWorkerRole, str] = {
    AIWorkerRole.NORMALIZER: "정규화",
    AIWorkerRole.UNIT_CONVERTER: "단위 변환",
    AIWorkerRole.CLASSIFIER: "분류",
    AIWorkerRole.CANONICAL_MATCHER: "표준 매칭",
    AIWorkerRole.KEYWORD_GENERATOR: "키워드 생성",
    AIWorkerRole.PROMPT_CURATOR: "프롬프트 큐레이터",
    AIWorkerRole.DATA_AUDITOR: "데이터 감사",
}

_PROVIDER_LABELS: dict[ProviderKind, str] = {
    ProviderKind.GEMINI: "Google Gemini",
    ProviderKind.OPENAI_COMPATIBLE: "OpenAI 호환",
    ProviderKind.OLLAMA: "Ollama (로컬)",
    ProviderKind.CUSTOM: "사용자 정의",
}


@router.get("/capabilities")
async def get_capabilities() -> dict:
    return {
        "service": "ai-admin",
        "version": "0.1.0",
        "roles": [
            {
                "value": role.value,
                "label": _ROLE_LABELS.get(role, role.value),
                "supported": False,
            }
            for role in AIWorkerRole
        ],
        "providers": [
            {
                "value": kind.value,
                "label": _PROVIDER_LABELS.get(kind, kind.value),
                "supported": False,
            }
            for kind in ProviderKind
        ],
    }
