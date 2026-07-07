#!/bin/sh
set -e
if [ "${WORKER_RUN_MIGRATIONS:-true}" = "true" ]; then
  cd /app/infra/migrations
  alembic upgrade head
fi
cd /app
BEAT_ARGS=""
if [ "${WORKER_BEAT:-false}" = "true" ]; then
  BEAT_ARGS="-B"
fi
exec celery -A worker.celery_app worker $BEAT_ARGS -Q "${WORKER_QUEUES:-default,audio,stt,llm}" --loglevel=info --concurrency="${WORKER_CONCURRENCY:-3}"
