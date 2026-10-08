"""checkout-api — a deliberately imperfect service, so SLO burn is observable.

Exposes Prometheus metrics on /metrics. Two control endpoints let you inject
latency and errors at runtime, which is how the runbook and postmortem in
docs/ were produced.
"""
import asyncio
import os
import random
import time

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

app = FastAPI(title="checkout-api")

# Buckets chosen around the 300ms latency SLO threshold so the ratio of
# requests under target can be read straight off a single bucket boundary.
LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0)

REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "route", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
INFLIGHT = Counter(
    "checkout_items_processed_total",
    "Line items processed, a proxy for business volume.",
)

# Runtime-tunable fault injection. Defaults come from the environment so
# docker-compose can start the service in a degraded state for demos.
STATE = {
    "error_rate": float(os.getenv("INJECT_ERROR_RATE", "0.002")),
    "extra_latency_ms": int(os.getenv("INJECT_LATENCY_MS", "0")),
}


async def _simulate_work(route: str) -> int:
    """Sleep for a plausible amount of time, then decide an outcome."""
    base = random.gauss(0.045, 0.02)
    jitter = random.expovariate(60) if random.random() < 0.15 else 0.0
    delay = max(0.001, base + jitter) + STATE["extra_latency_ms"] / 1000.0
    await asyncio.sleep(delay)
    return 500 if random.random() < STATE["error_rate"] else 200


async def _handle(method: str, route: str) -> Response:
    started = time.perf_counter()
    status = await _simulate_work(route)
    LATENCY.labels(method, route).observe(time.perf_counter() - started)
    REQUESTS.labels(method, route, str(status)).inc()
    if status == 200 and route == "/checkout":
        INFLIGHT.inc(random.randint(1, 4))
    if status != 200:
        return Response('{"error":"internal"}', status_code=500,
                        media_type="application/json")
    return Response('{"ok":true}', media_type="application/json")


@app.get("/checkout")
async def checkout() -> Response:
    return await _handle("GET", "/checkout")


@app.get("/cart")
async def cart() -> Response:
    return await _handle("GET", "/cart")


@app.get("/healthz")
async def healthz() -> Response:
    # Deliberately uninstrumented: probe traffic must not pollute the SLI.
    return Response('{"status":"ok"}', media_type="application/json")


@app.post("/admin/inject")
async def inject(error_rate: float | None = None,
                 latency_ms: int | None = None) -> dict:
    """Change fault injection without a restart. Demo-only; never ship this."""
    if error_rate is not None:
        STATE["error_rate"] = max(0.0, min(1.0, error_rate))
    if latency_ms is not None:
        STATE["extra_latency_ms"] = max(0, latency_ms)
    return dict(STATE)


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
