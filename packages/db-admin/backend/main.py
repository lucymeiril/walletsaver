"""DB 관리 백엔드 진입점"""
import uvicorn
from api.app import create_app

app = create_app()

if __name__ == "__main__":
    from config import settings
    uvicorn.run("main:app", host="0.0.0.0", port=settings.API_PORT, reload=settings.DEBUG)
