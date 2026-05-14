"""DB 관리 백엔드 진입점"""
import uvicorn
from logging_config import setup_logging

setup_logging()

from api.app import create_app

app = create_app()

if __name__ == "__main__":
    from config import settings
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        timeout_keep_alive=30,
    )
