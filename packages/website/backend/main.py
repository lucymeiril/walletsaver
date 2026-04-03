"""
Website Backend 엔트리포인트 — FastAPI 앱 생성 및 uvicorn 서빙.

Usage:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from api.app import create_app
from config import API_HOST, API_PORT

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
    )
