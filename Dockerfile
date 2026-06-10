# REZN generator API (FastAPI). Builds with uv for reproducible installs.
#   docker build -t rezn-api .
#   docker run -p 8000:8000 --env-file .env rezn-api
FROM python:3.12-slim

# uv (fast, lockfile-reproducible installs)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first for layer caching, then the project itself.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Unbuffered stdout/stderr so logs flush immediately (critical for diagnosing
# startup in container platforms that kill unhealthy containers before a flush).
ENV PYTHONUNBUFFERED=1

# Canonical output locations the API serves from (/artifacts mount).
RUN mkdir -p runs artifacts

EXPOSE 8000

# Honors REZN_PRODUCTION, REDIS_URL, AGENT_MEMORY_*, WANDB_API_KEY,
# REZN_ENABLE_INFERENCE, REZN_INFERENCE_REQUIRED, REZN_CORS_ORIGINS from env.
# Exec-form `sh -c` so $PORT (set by Railway and most PaaS hosts) is always expanded
# by a shell — even when a platform exec's the command without one — falling back to
# 8000 for local `docker run`. `exec` hands PID 1 (and its signals) to uvicorn.
CMD ["sh", "-c", "exec uvicorn rezn_ai.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
