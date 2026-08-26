"""storage 패키지 — DB/파일 저장소. core/만 의존."""

# 별도 모듈의 ORM 테이블도 Base.metadata에 등록되도록 import한다.
from storage.hotdeal_reports import HotdealReport  # noqa: F401
