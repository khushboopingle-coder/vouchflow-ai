# VouchFlow AI - one image for the API (port 8000) and the dashboard (port 8501).
# docker-compose.yml starts the right command for each.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so rebuilding after a code change is fast
COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code and the sample data (the .dockerignore keeps secrets and local databases out)
COPY . .

# Run as a normal user, not root; /app/db holds the SQLite file when no DATABASE_URL is set
RUN useradd --create-home --uid 10001 vouchflow     && mkdir -p /app/db /app/data/workspaces     && chown -R vouchflow:vouchflow /app
USER vouchflow

EXPOSE 8000 8501

# Default: the API. The dashboard service overrides this command.
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
