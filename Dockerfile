# NetSentinel FastAPI Backend
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install package dependencies and application code
COPY pyproject.toml .
COPY app/ ./app/
COPY alembic.ini .
COPY migrations/ ./migrations/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
