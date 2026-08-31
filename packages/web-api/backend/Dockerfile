FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY packages/web-api/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY packages/shared /app/shared
COPY packages/web-api/backend /app/backend
ENV PYTHONPATH=/app/backend:/app/shared
WORKDIR /app/backend

EXPOSE 8000
CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
