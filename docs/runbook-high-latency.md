# Runbook — LatencyErrorBudgetBurn*

**Alert fired because:** the share of requests slower than 300ms exceeded the
burn-rate threshold. Note this says nothing about *errors* — a service can be
100% available and still violate this SLO.

## 1. Is it everything, or is it the tail?

```bash
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum by (le) (rate(http_request_duration_seconds_bucket[5m]))'
```

Compare the shape against the heatmap panel in the SLO dashboard:

- **Whole distribution shifted right** → systemic. Usually resource
  saturation or a slow dependency affecting every request.
- **Only the tail moved, median flat** → a subset of requests. Usually a cache
  miss path, an N+1 query, lock contention, or one unhealthy replica.

The second case is the one a p99 alone hides, which is why the heatmap is on
the dashboard.

## 2. Separate "slow" from "overloaded"

```bash
# Throughput alongside latency
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum(rate(http_requests_total[5m]))'
```

Latency rising **with** throughput is a capacity problem — scale out. Latency
rising while throughput is flat or falling is a dependency or code problem,
and scaling out will make it worse by adding load to whatever is already
struggling.

## 3. Common causes, in order

1. **A slow dependency.** Most latency incidents are someone else's latency
   incident.
2. **Connection pool exhaustion.** Looks like latency, is actually queueing.
   Check pool saturation before CPU.
3. **A deploy** that added a synchronous call to a hot path.
4. **Noisy neighbour / CPU throttling.** Check throttling metrics, not just
   CPU usage — a throttled container shows low usage and high latency.

## 4. Mitigate

- Scale out if saturation-driven.
- Roll back if deploy-correlated.
- If one dependency is the cause, apply a timeout. An unbounded call is how
  one slow dependency becomes a total outage; a 300ms SLO cannot be met with
  a 30s timeout on the critical path.

## Reproducing this alert deliberately

```bash
# 400ms added latency puts every request over the 300ms target
curl -XPOST "http://localhost:8000/admin/inject?latency_ms=400"
k6 run load/k6/steady.js
curl -XPOST "http://localhost:8000/admin/inject?latency_ms=0"   # reset
```
