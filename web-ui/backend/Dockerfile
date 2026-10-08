FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements-core.txt
COPY web-ui/backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements-core.txt -r requirements.txt

COPY web-ui/backend/ ./
COPY hyperrag ./hyperrag
COPY hyperche ./hyperche
COPY configs ./configs

RUN mkdir -p /app/cache_seed/case1 /app/hyperrag_cache/case1 /app/readonly_caches /app/runtime /app/uploads /app/knowledge_bases \
    && chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
