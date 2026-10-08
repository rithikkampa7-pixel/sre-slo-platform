# sre-slo-platform

A runnable SLO and error-budget stack for a deliberately imperfect service.
`make up` gives you a service under load, two SLOs, multi-window burn-rate
alerts that actually fire, and the runbooks you would reach for when they do.

Built to answer the questions SRE interviews actually ask: *what's your SLI,
why that one, how do you alert on it without paging on noise, and what do you
do when the budget runs out?*

```
┌──────────────┐   scrape    ┌────────────┐   fires    ┌──────────────┐
│ checkout-api │ ──────────▶ │ Prometheus │ ─────────▶ │ Alertmanager │
│  :8000       │             │  :9090     │            │  :9093       │
│  5xx + hist  │             │ SLI rules  │            │ page│ticket  │
└──────────────┘             │ burn-rate  │            └──────┬───────┘
       ▲                     └──────┬─────┘                   │
       │ load                       │ query                   ▼
┌──────┴───────┐             ┌──────▼─────┐            ┌──────────────┐
│  k6 steady   │             │  Grafana   │            │  alert-sink  │
│  k6 spike    │             │  :3000     │            │  prints it   │
└──────────────┘             └────────────┘            └──────────────┘
```

## Quick start

```bash
make up          # build and start everything
make load        # steady baseline traffic (needs k6 installed)
make burn        # inject 5% errors + spike -> watch a page fire
make logs        # follow alerts as they are delivered
make reset       # clear injected faults
make down        # tear down, including stored metrics
```

Then open:

- **Grafana** — http://localhost:3000 → dashboard *checkout-api — SLO Overview*
- **Prometheus alerts** — http://localhost:9090/alerts
- **Service** — http://localhost:8000/checkout

## The SLOs

| SLO | Target | Window | Budget |
|---|---|---|---|
| Availability | 99.9% of requests succeed | 30d rolling | 0.1% of requests |
| Latency | 99% of requests under 300ms | 30d rolling | 1% of requests |

Full reasoning, including why latency is measured as a **ratio of good
requests rather than a `histogram_quantile` p99**, is in
[docs/slo-definitions.md](docs/slo-definitions.md).

## Why multi-window burn-rate alerting

A single long window detects outages too late; a single short window pages on
every blip. Each alert here requires both, so it is fast *and* quiet — and the
short window releases the alert promptly on recovery instead of latching for
the length of the long window.

| Severity | Long | Short | Burn | Budget spent | Catches |
|---|---|---|---|---|---|
| page | 1h | 5m | 14.4 | 2% | a hard outage |
| page | 6h | 30m | 6 | 5% | serious degradation |
| ticket | 1d | 2h | 3 | 10% | a slow leak |
| ticket | 3d | 6h | 1 | 10% | chronic underperformance |

Alertmanager also **inhibits** the quieter alerts while a fast-burn page is
firing, so one incident produces one notification rather than four.

There is a seventh alert, `SLIDataMissing`, because an SLI that stops
reporting looks exactly like a perfectly healthy one.

## Watch an alert fire end to end

```bash
make up
curl -XPOST "http://localhost:8000/admin/inject?error_rate=0.05"
k6 run load/k6/spike.js
make logs      # ALERT firing AvailabilityErrorBudgetBurnFast page
```

5% errors is 50x the 0.1% budget, so the fast-burn page arrives in roughly
2-3 minutes (a 2m `for:` clause plus scrape and evaluation delay).

For latency instead:

```bash
curl -XPOST "http://localhost:8000/admin/inject?latency_ms=400"
k6 run load/k6/steady.js
```

## Docs

- [slo-definitions.md](docs/slo-definitions.md) — the SLIs, the budget maths, and the error-budget policy
- [runbook-availability.md](docs/runbook-availability.md) — what to do when the availability page fires
- [runbook-high-latency.md](docs/runbook-high-latency.md) — systemic vs tail latency, and how to tell them apart
- [postmortem-2026-10-01.md](docs/postmortem-2026-10-01.md) — a worked postmortem from an induced incident

## Layout

```
services/checkout-api/     FastAPI service, Prometheus-instrumented,
                           with runtime fault injection for demos
observability/
  prometheus/rules/        SLI recording rules + burn-rate alerts
  grafana/                 provisioned datasource and SLO dashboard
  alertmanager/            page vs ticket routing, inhibition
load/k6/                   steady baseline and spike scenarios
tools/alert-sink/          webhook receiver that prints delivered alerts
docs/                      SLO definitions, runbooks, postmortem
.github/workflows/ci.yaml  promtool/amtool validation + a smoke test that
                           asserts the SLI actually reports
```

## CI

`promtool check rules` runs on every PR, because a typo in a recording rule
silently stops an SLO being measured — a failure mode that is invisible until
you need the data. The smoke job starts the full stack, drives traffic through
it, and asserts the availability SLI returns a value and both fast-burn alerts
are loaded.

## Three findings this repo was built around

Both were found by running the stack, not by reading the config, and both are
documented in place rather than quietly fixed:

**1. Multi-process metrics corrupt the SLI.** The service originally ran
`uvicorn --workers 2`. `prometheus_client` keeps counters in per-process
memory, so Prometheus scraped whichever worker answered and saw values jump
between two independent registries. `rate()` reads each downward jump as a
counter reset, and the latency SLI came out **negative** -- which would have
silently cleared a latency alert rather than firing one. Fixed by pinning to
one worker (see the comment in the Dockerfile); the production fix is
`prometheus_client`'s multiprocess mode with a shared `PROMETHEUS_MULTIPROC_DIR`.

**2. Mixing `_bucket` and `_count` in a ratio.** The latency SLI divided the
`le="0.3"` bucket by `_count`. Both equal total requests, but they are
different series families, so `rate()` extrapolates them independently at
window edges and the ratio can exceed 1. The denominator is now the
`le="+Inf"` bucket from the same family, with `clamp_min(..., 0)` as a
backstop against counter resets.

**3. A ratio SLI cannot recover without traffic.** After clearing an injected
fault the error ratio stayed pinned at 0.39 and the page would not clear --
with a flat counter, `rate()` decays numerator and denominator proportionally,
so the ratio holds its last value until the window rolls past. Driving clean
traffic for one window dropped it to 0.0024 and resolved both pages. The
general fix for low-QPS services is a minimum-traffic guard in the alert
expression; see [slo-definitions.md](docs/slo-definitions.md#pitfall-ratio-slis-need-traffic).

## Notes and limitations

- The 30-day error-budget panel uses `increase(...[30d])`, which needs 30 days
  of data to be meaningful. On a fresh stack it reads optimistically.
- `/admin/inject` is unauthenticated and exists only so the alerts are
  demonstrable. It is the subject of the postmortem's action items for exactly
  that reason, and would never ship.
- Single-replica, single-host. Aggregating SLIs across replicas works
  unchanged (that is the point of using counter ratios), but no multi-cluster
  federation is set up here.
