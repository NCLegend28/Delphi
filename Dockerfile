# Delphi gateway + worker share one image — they differ only by start command
# (compose sets it). Multi-stage with uv: deps resolve in the builder against
# the committed lockfile, the runtime stage carries only the venv + source.
#
#   build:  docker build -t delphi .
#   gateway: uvicorn main:app --host 0.0.0.0 --port 8080   (compose default)
#   worker:  arq worker.main.WorkerSettings                (compose override)

# --- builder: install deps into /app/.venv from the frozen lockfile ---------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Layer 1: dependencies only (no project). Cached until the lockfile changes,
# so editing source doesn't reinstall the world.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Layer 2: the project itself.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime: slim image, non-root, venv on PATH ---------------------------
FROM python:3.12-slim AS runtime

# curl for the compose healthcheck; nothing else.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 delphi

WORKDIR /app
COPY --from=builder --chown=delphi:delphi /app /app

# Writable mountpoints. Creating + chowning them here means a fresh named
# volume inherits delphi-ownership on first attach (Docker copies the image
# dir's perms into an empty named volume), so the non-root user can write.
RUN mkdir -p /vault /var/log/delphi \
    && chown -R delphi:delphi /vault /var/log/delphi

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER delphi
EXPOSE 8080

# Default command = gateway. The worker service overrides this in compose.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
