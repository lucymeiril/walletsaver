"""ai-admin 백엔드 worker 구현 패키지.

Phase2 단계에서는 실제 LLM provider 호출을 하지 않고, 결정론적 placeholder
출력을 만들어 검수 큐/파이프라인 통합 테스트에 사용한다. 모든 worker는
`shared.core.ai_workers.BaseAIWorker`를 상속하고 역할 검증 후
`AIWorkerOutput`을 반환한다.
"""

from .base import build_provenance, make_proposal
from .canonical_matcher import CanonicalMatcherWorker
from .classifier import ClassifierWorker
from .data_auditor import DataAuditorWorker
from .keyword_generator import KeywordGeneratorWorker
from .normalizer import NormalizerWorker
from .prompt_curator import PromptCuratorWorker
from .registry import build_default_registry
from .unit_converter import UnitConverterWorker

__all__ = [
    "CanonicalMatcherWorker",
    "ClassifierWorker",
    "DataAuditorWorker",
    "KeywordGeneratorWorker",
    "NormalizerWorker",
    "PromptCuratorWorker",
    "UnitConverterWorker",
    "build_default_registry",
    "build_provenance",
    "make_proposal",
]
