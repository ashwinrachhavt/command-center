FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 10001 app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=builder --chown=app:app /app/.venv ./.venv
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app migrations ./migrations
USER app
EXPOSE 8000
CMD ["uvicorn", "command_center.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
