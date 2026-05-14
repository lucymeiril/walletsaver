"""ai-admin control DB 저장소 패키지.

이 패키지는 ai-admin 전용 SQLite/Postgres-호환 SQLAlchemy 모델과 repository를
정의한다. db-admin이 사용하는 public catalog ORM과는 별도이며, 비밀값(secret value)
은 절대 저장하지 않고 `secret_alias`만 보관한다.
"""

from .database import (
    Database,
    create_database,
    get_default_database,
    reset_default_database,
)
from .models import Base
from .repositories import (
    FieldProposalRepository,
    JobQueueSqlRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
    PromptPackRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    ReviewQueueRepositoryAdapter,
    WorkerAttemptRepository,
)

__all__ = [
    "Base",
    "Database",
    "create_database",
    "get_default_database",
    "reset_default_database",
    "FieldProposalRepository",
    "JobQueueSqlRepository",
    "KeywordProposalRepository",
    "LearnedKnowledgeRepository",
    "ProductMatchStoreRepository",
    "PromptPackRepository",
    "ProviderConfigRepository",
    "RawCrawlBatchRepository",
    "ReviewDecisionRepository",
    "ReviewQueueRepositoryAdapter",
    "WorkerAttemptRepository",
]
