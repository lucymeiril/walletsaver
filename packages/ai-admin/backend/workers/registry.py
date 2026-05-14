"""기본 worker 레지스트리 빌더."""
from __future__ import annotations

from core.ai_workers import WorkerRegistry

from .canonical_matcher import CanonicalMatcherWorker
from .classifier import ClassifierWorker
from .data_auditor import DataAuditorWorker
from .keyword_generator import KeywordGeneratorWorker
from .normalizer import NormalizerWorker
from .prompt_curator import PromptCuratorWorker
from .unit_converter import UnitConverterWorker


def build_default_registry() -> WorkerRegistry:
    """모든 역할별 placeholder worker를 등록해 반환한다."""
    registry = WorkerRegistry()
    registry.register(NormalizerWorker())
    registry.register(UnitConverterWorker())
    registry.register(ClassifierWorker())
    registry.register(CanonicalMatcherWorker())
    registry.register(KeywordGeneratorWorker())
    registry.register(PromptCuratorWorker())
    registry.register(DataAuditorWorker())
    return registry
