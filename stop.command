#!/bin/bash
# CallQA — stop the app. Double-click to run.
cd "$(dirname "$0")"

echo "Stopping the CallQA app processes…"
pkill -f "uvicorn app.main:app"        2>/dev/null
pkill -f "celery -A worker.celery_app" 2>/dev/null
pkill -f "next dev"                    2>/dev/null
pkill -f "next-server"                 2>/dev/null
pkill -f "pnpm dev"                    2>/dev/null

# Next.js / uv spawn child workers whose command lines don't match the patterns
# above, so they can keep holding the ports. Force-free the two app ports so a
# later start.command never hits "port already in use".
sleep 1
for port in 3020 7870; do
  pids=$(lsof -ti tcp:$port 2>/dev/null)
  [ -n "$pids" ] && kill -9 $pids 2>/dev/null
done

echo
echo "App stopped."
echo "The database (Postgres/Redis) is still running so your data is kept."
echo "To shut those down too:  open Terminal here and run  make down"
read -r -p "Press Return to close."
