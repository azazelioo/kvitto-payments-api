FROM python:3.14.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements-runtime.txt ./
RUN python -m pip install -r requirements-runtime.txt
COPY pyproject.toml alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY docker-entrypoint.sh ./
RUN python -m pip install --no-deps . \
    && python -m pip check \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir /data \
    && chown app:app /data

USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
