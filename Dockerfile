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

# Canonical output locations the API serves from (/artifacts mount).
RUN mkdir -p runs artifacts

EXPOSE 8000

# Honors REDIS_URL, WANDB_API_KEY, REZN_ENABLE_INFERENCE, REZN_CORS_ORIGINS from env.
CMD ["uvicorn", "rezn_ai.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
