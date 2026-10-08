# SLO definitions — checkout-api

## Why these two SLIs

`checkout-api` has one job: let a user complete a checkout, quickly. So the
two things worth measuring are whether the request succeeded and whether it
was fast enough. Everything else (CPU, memory, pod restarts) is a cause, not
a symptom, and belongs on a debugging dashboard rather than in an SLO.

Deliberately **not** in the SLI: `/healthz`. Probe traffic is uninstrumented
in the application itself, so it cannot dilute the error ratio. This matters
more than it sounds — a service answering 10 probes/sec and failing every
real request can look 90% healthy if probes are counted.

## SLO 1 — Availability

| | |
|---|---|
| **SLI** | `sum(rate(http_requests_total{status=~"5.."}[w])) / sum(rate(http_requests_total[w]))` |
| **Target** | 99.9% of requests succeed |
| **Window** | 30 days, rolling |
| **Error budget** | 0.1% of requests |

A 5xx is the server's fault and counts against the budget. A 4xx is the
client's and does not — a flood of 400s is a problem, but it is not *this*
SLO's problem, and folding it in would make the number unactionable.

At 1,000 req/s, a 0.1% budget is roughly **2,592 failed requests per 30 days**.
That is the entire allowance. A single 10-minute total outage at that rate
costs 600,000 requests, or 230x the monthly budget — which is the real
argument for fast detection.

## SLO 2 — Latency

| | |
|---|---|
| **SLI** | `1 - (rate(http_request_duration_seconds_bucket{le="0.3"}[w]) / rate(http_request_duration_seconds_count[w]))` |
| **Target** | 99% of requests complete within 300ms |
| **Window** | 30 days, rolling |
| **Error budget** | 1% of requests may exceed 300ms |

This is expressed as a **ratio of good requests**, not as `histogram_quantile`
on a p99. That choice is deliberate:

1. `histogram_quantile` interpolates *within* a bucket, so a reported "p99 =
   297ms" can be an artifact of bucket boundaries rather than a real
   measurement.
2. Quantiles cannot be averaged or summed across instances. A ratio of
   counters can, which means this SLI aggregates correctly across any number
   of replicas.
3. The app's histogram has an explicit `le="0.3"` bucket matching the SLO
   threshold, so the numerator is a direct count, not an estimate.

The cost of this approach is that the threshold is baked into the bucket
layout: changing the SLO to 250ms requires adding a bucket and re-deploying
the service, not just editing a query. That is an acceptable trade for an
exact SLI.

## Burn rate, and why alerts are paired

Burn rate is "how many times faster than sustainable are we spending budget".
Burn rate 1 exhausts the 30-day budget in exactly 30 days.

Alerting on a long window alone is too slow — a 6h window needs hours of
outage before it moves. Alerting on a short window alone pages on every
transient blip. So each alert requires **both** a long window (is this big
enough to matter?) and a short one (is it still happening right now?). The
short window is what resets the alert promptly after recovery instead of
leaving it latched for the length of the long window.

| Severity | Long | Short | Burn | Budget spent if sustained | Catches |
|---|---|---|---|---|---|
| page | 1h | 5m | 14.4 | 2% | a hard outage |
| page | 6h | 30m | 6 | 5% | serious degradation |
| ticket | 1d | 2h | 3 | 10% | a slow leak |
| ticket | 3d | 6h | 1 | 10% | chronic underperformance |

The 14.4 figure is not arbitrary: budget spent = burn x (window / 30d), so
14.4 x (1h / 720h) = 2% of the budget in one hour.

## What the budget is *for*

The error budget is a spending allowance, not a score to maximise. 100% of
budget intact over six months does not mean the service is excellent — it
means the SLO is too loose, or the team is shipping too cautiously and
leaving reliability investment on the table.

Policy for this service:

- **Budget remaining** — ship features; take reasonable risks.
- **Budget exhausted** — feature freeze; reliability work takes priority
  until the trailing 30-day window recovers.
- **Chronically at burn rate 1** — the SLO and the architecture disagree.
  Either the target is wrong or the service needs real work. Decide which
  explicitly rather than re-tuning alert thresholds until the paging stops.
