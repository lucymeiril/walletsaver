"""
CLI 진입점 — 개발자가 터미널에서 크롤링·서버·DB 초기화를 실행하는 관문.

왜 존재하는가:
    모든 실행은 Container.bootstrap()으로 시작해야 의존성이 올바르게 조립된다.
    이 파일이 (1) CLI 인자 파싱 → (2) Container 부트스트랩 → (3) 명령 실행
    흐름을 강제하여, 어떤 명령이든 항상 동일한 초기화 경로를 거치게 한다.
어디서 쓰이는가:
    `python main.py crawl emart`, `python main.py server` 등 터미널에서 직접 실행.
"""

import argparse
import asyncio
import logging
import sys

from container import Container

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("wallet_guardian")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="지갑 지키미 크롤러",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # 서버 시작
    server = subparsers.add_parser("server", help="API 서버 + 대시보드 시작")
    server.add_argument("--host", default="0.0.0.0")
    server.add_argument("--port", type=int, default=8000)

    # 크롤링 실행
    crawl = subparsers.add_parser("crawl", help="크롤링 실행")
    crawl.add_argument("crawler", help="크롤러 이름 (예: emart, kamis, all)")
    crawl.add_argument("--strategy", help="강제 전략 지정", default=None)

    # DB 초기화
    subparsers.add_parser("init-db", help="데이터베이스 초기화")

    # 크롤러 목록
    subparsers.add_parser("list", help="등록된 크롤러 목록")

    return parser


async def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # DI 컨테이너 부트스트랩 — 모든 명령 실행 전에 의존성 조립이 선행되어야 함
    container = Container()
    container.bootstrap()

    if args.command == "server":
        logger.info(f"서버 시작: {args.host}:{args.port}")
        if container.api_app:
            import uvicorn
            uvicorn.run(container.api_app, host=args.host, port=args.port)
        else:
            logger.error("API 앱이 초기화되지 않았습니다.")

    elif args.command == "crawl":
        logger.info(f"크롤링 실행: {args.crawler}")
        # TODO: engine.execute_crawler
        logger.info("크롤링 엔진은 Phase 2에서 구현됩니다.")

    elif args.command == "init-db":
        logger.info("DB 초기화...")
        if container.storage:
            container.storage.init_db()
            from storage.seed import seed_all
            seed_all(engine=container.storage.engine)
            logger.info("DB 초기화 + 시드 데이터 투입 완료.")
        else:
            logger.error("저장소가 초기화되지 않았습니다.")

    elif args.command == "list":
        logger.info("등록된 크롤러:")
        # TODO: engine.list_crawlers
        logger.info("크롤러 등록은 Phase 3~6에서 구현됩니다.")


if __name__ == "__main__":
    asyncio.run(main())
