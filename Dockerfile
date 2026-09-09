# Bitget S2 Divergent Agent Desk — paper-only image
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PAPER=true \
    HOST=0.0.0.0 \
    PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent ./agent
COPY api ./api
COPY desk ./desk
COPY exec ./exec
COPY ingest ./ingest
COPY risk ./risk
COPY signals ./signals
COPY scripts ./scripts
COPY pyproject.toml README.md ./

RUN mkdir -p /app/data

EXPOSE 8080

# Default: API dashboard. Compose overrides for desk poll service.
# Two services (api + desk) are defined in docker-compose.yml.
CMD ["python", "scripts/run_api.py"]