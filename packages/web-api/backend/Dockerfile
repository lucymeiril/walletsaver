FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    PYTHONPATH=/app/packages/web-api/backend:/app/packages/shared

# Prepare paths and source while the rootfs is still the slim base.
WORKDIR /app/packages/web-api/backend
COPY packages/shared /app/packages/shared
COPY packages/web-api/backend /app/packages/web-api/backend

# Install declared Python dependencies and the ordinary browser in one final layer.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca \
      pip install --no-cache-dir -r /app/packages/web-api/backend/requirements.txt && \
      NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca \
      PIP_CERT=/run/secrets/proxy_ca \
      python -m playwright install --with-deps chromium --only-shell; \
    else \
      pip install --no-cache-dir -r /app/packages/web-api/backend/requirements.txt && \
      python -m playwright install --with-deps chromium --only-shell; \
    fi

EXPOSE 8000
CMD ["uvicorn", "api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
