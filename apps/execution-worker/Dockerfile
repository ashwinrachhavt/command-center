FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra executor
COPY apps/api/src ./src
RUN uv sync --frozen --no-dev --no-editable --extra executor

FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
RUN useradd --create-home --uid 10001 app \
    && install -d -m 0700 -o app -g app /var/lib/command-center/blobs
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=builder --chown=app:app /app/.venv ./.venv
USER app
ENTRYPOINT ["celery", "-A", "command_center.agents.queue:celery", "worker", "--loglevel=WARNING", "--concurrency=1", "--queues=execution"]
