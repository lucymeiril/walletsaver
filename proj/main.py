"""
메인 진입점.

CLI에서 크롤러 앱을 실행한다.
DI 컨테이너를 부트스트랩하고, 요청된 명령을 수행.
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

    # DI 컨테이너 부트스트랩
    container = Container()
    container.bootstrap()

    if args.command == "server":
        logger.info(f"서버 시작: {args.host}:{args.port}")
        # TODO: uvicorn 실행
        logger.info("서버 기능은 Phase 7에서 구현됩니다.")

    elif args.command == "crawl":
        logger.info(f"크롤링 실행: {args.crawler}")
        # TODO: engine.execute_crawler
        logger.info("크롤링 엔진은 Phase 2에서 구현됩니다.")

    elif args.command == "init-db":
        logger.info("DB 초기화...")
        # TODO: storage.init_db
        logger.info("DB 모듈은 Phase 1 이후 구현됩니다.")

    elif args.command == "list":
        logger.info("등록된 크롤러:")
        # TODO: engine.list_crawlers
        logger.info("크롤러 등록은 Phase 3~6에서 구현됩니다.")


if __name__ == "__main__":
    asyncio.run(main())
