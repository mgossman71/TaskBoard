# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# TaskBoard API image (multi-stage)
#   builder  -> resolves locked production dependencies into /opt/venv
#   test     -> builder + dev dependencies + tests (used by compose.test.yaml)
#   runtime  -> slim, non-root production image (default target)
# ---------------------------------------------------------------------------
ARG PYTHON_IMAGE=python:3.13.18-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.30

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY taskboard ./taskboard
# --reinstall-package: never reuse a cached wheel of the app itself (its version
# number does not change between builds, so the uv cache would serve stale code).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --reinstall-package taskboard

FROM builder AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --reinstall-package taskboard
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests
RUN useradd --uid 10001 --create-home app && mkdir -p /data/attachments && chown -R app /data /app
USER app
CMD ["pytest"]

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /data/attachments \
 && chown -R app:app /data
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY alembic ./alembic
USER app
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=4).status == 200 else 1)"]
CMD ["python", "-m", "taskboard.serve"]
