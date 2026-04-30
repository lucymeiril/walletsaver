"""ai-admin 백엔드 진입점 (로컬 전용 스켈레톤)."""
import uvicorn

from api.app import create_app

app = create_app()

if __name__ == "__main__":
    from config import settings

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
        timeout_keep_alive=30,
    )
