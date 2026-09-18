# syntax=docker/dockerfile:1
# --------------------------------------------------------------------------
# Bifrost API Gateway production image.
# Dependencies are installed from uv.lock so the image is reproducible, only
# runtime dependencies are installed, and the service runs as a non-root user.
# --------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY --from=ghcr.io/astral-sh/uv:0.8.4 /uv /usr/local/bin/uv

WORKDIR /app

# Install the locked runtime dependencies first so the layer is cached.
COPY pyproject.toml uv.lock README.md ./
COPY src/__init__.py ./src/__init__.py
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000 \
    FORWARDED_ALLOW_IPS=127.0.0.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 bifrost \
    && useradd --system --uid 10001 --gid bifrost --home /app bifrost

WORKDIR /app

COPY --from=builder --chown=bifrost:bifrost /app/.venv /app/.venv
COPY --chown=bifrost:bifrost src/ ./src/

USER bifrost

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# The console entry point reads HOST, PORT and FORWARDED_ALLOW_IPS from the
# same Settings object the application uses, so the container command cannot
# drift from the application configuration. It pins a single worker because
# the service registry is an in-process snapshot.
CMD ["python", "-m", "src.main"]
