#!/bin/sh
set -eu

if [ ! -w /data ]; then
    echo "The application user cannot write to /data" >&2
    exit 1
fi
python -m alembic upgrade head
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
