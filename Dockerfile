# Variance Detective — container image
# Build:  docker build -t variance-detective .
# Run:    docker run --rm -e VD_LLM__PROVIDER=offline -v $PWD/workspace:/app/workspace variance-detective vd demo
# Serve:  docker run --rm -p 8080:8080 --env-file .env variance-detective uvicorn variance_detective.api:app --host 0.0.0.0 --port 8080

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# uv/uvx is used by stdio MCP servers such as SAC-MCP (`command: uvx`)
RUN pip install --no-cache-dir uv && useradd -m -u 1000 vd

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY demo ./demo
RUN pip install --no-cache-dir ".[all]" fastapi uvicorn

RUN mkdir -p /app/workspace && chown -R vd:vd /app
USER vd
VOLUME ["/app/workspace"]
EXPOSE 8080
ENV VD_CONFIG=/app/config/agent.yaml
ENTRYPOINT []
CMD ["vd", "--help"]
