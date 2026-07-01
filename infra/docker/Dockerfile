# Production image for the VoiceQA backend (api + worker share one image).
# Build context is the repo root:
#   docker build -f infra/docker/Dockerfile -t voiceqa-backend .
#
# The api service runs:    uvicorn app.main:app --host 0.0.0.0 --port $PORT
# The worker service runs: celery -A worker.celery_app worker -B -Q default,audio,stt,llm
# (start commands are set per-service in render.yaml).

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ffmpeg: the worker's audio pipeline shells out to it (stereo channel split,
# 16 kHz resample). The api doesn't need it, but one image keeps things simple.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install EVERY workspace member (api + worker + shared) and their deps, plus the
# root dev group which carries alembic for the migration step. --all-packages is
# required: a bare `uv sync` only syncs the root project (which has no runtime
# deps), leaving fastapi/celery/app/worker uninstalled. .dockerignore keeps
# node_modules, .venv, .git and secrets out of the context.
COPY . .
RUN uv sync --frozen --all-packages \
    && chmod +x /app/infra/docker/start-worker.sh

# Put the venv's console scripts (uvicorn, celery, alembic) on PATH.
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 7870

# Default to the api; render.yaml overrides this for the worker service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7870"]
