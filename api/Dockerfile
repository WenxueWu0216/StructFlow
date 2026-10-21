# Build from the repository root: docker build -f api/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The pricing library is installed as its own package, exactly as the batch job uses it.
COPY structflow /src/structflow
RUN pip install /src/structflow

COPY api /app
RUN pip install "/app[server]"
COPY data /app/data

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn --workers 2 --bind 0.0.0.0:8000 'structflow_api:create_app()'"]
