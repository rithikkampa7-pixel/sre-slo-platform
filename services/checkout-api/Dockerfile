FROM python:3.12-slim

WORKDIR /app

# Dependencies first so code edits don't bust the layer cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

RUN adduser --disabled-password --gecos "" --uid 10001 app
USER 10001

EXPOSE 8000

# --workers 1 is deliberate, not laziness.
#
# prometheus_client keeps counters in per-process memory. With >1 worker,
# Prometheus scrapes whichever worker happens to answer /metrics, so the
# values it sees jump between independent registries. rate() interprets each
# downward jump as a counter reset, and the resulting SLI is garbage -- it can
# even go negative. This bit us during development.
#
# The production fix is prometheus_client's multiprocess mode with a shared
# PROMETHEUS_MULTIPROC_DIR; for a single-service demo, one worker is simpler
# and exactly as correct.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--access-log", "--workers", "1"]
