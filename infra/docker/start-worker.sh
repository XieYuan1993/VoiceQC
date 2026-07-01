#!/bin/sh
set -e
cd /app/infra/migrations
alembic upgrade head
cd /app
exec celery -A worker.celery_app worker -B -Q default,audio,stt,llm --loglevel=info --concurrency=1
