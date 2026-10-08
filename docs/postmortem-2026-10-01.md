# Postmortem — checkout-api latency regression

> **This is a drill, not a real outage.** The incident was induced against the
> local demo service using the fault-injection endpoint, and every step below
> is reproducible from this repo with the commands in the Timeline. It is here
> to show the analysis format and the reasoning, not to claim production
> experience of an event that never happened.

| | |
|---|---|
| **Date** | 2026-10-01 |
| **Duration** | 34 minutes (14:02 – 14:36 UTC) |
| **Severity** | SEV-2 — SLO violated, no data loss |
| **Budget consumed** | ~31% of the 30-day latency budget |
| **Author** | — |
| **Status** | Action items open |

## Summary

A 400ms artificial delay was introduced on the `/checkout` path. The latency
SLI went from 0.4% of requests over 300ms to 99.6% within two scrape
intervals. `LatencyErrorBudgetBurnFast` paged 2m20s after onset. Availability
was unaffected throughout — every request succeeded, slowly. Mitigation was
removing the injected delay; recovery was immediate.

## Impact

- ~99.6% of checkout requests exceeded the 300ms target for 34 minutes.
- At the test rate (20 VUs, ~40 req/s) that is roughly **81,600 slow
  requests**, against a 30-day budget of about 1% of traffic.
- No failed requests. No data loss. The availability SLO stayed green, which
  is exactly why a latency SLO exists separately.

## Timeline (UTC)

| Time | Event |
|---|---|
| 14:00 | Baseline established. `k6 run load/k6/steady.js`, slow ratio ~0.4%. |
| 14:02 | Fault injected: `curl -XPOST "localhost:8000/admin/inject?latency_ms=400"` |
| 14:02:30 | First scrape reflecting the regression. 5m slow ratio begins climbing. |
| 14:03 | `sli:latency:slow_ratio_rate5m` crosses 14.4% (the 14.4x page threshold). |
| 14:04:20 | `LatencyErrorBudgetBurnFast` fires after its 2m `for:` clause. Delivered to `alert-sink`. |
| 14:05 | Runbook step 1: heatmap shows the **entire** distribution shifted right, not just the tail — systemic, not a subset. |
| 14:09 | Runbook step 2: throughput flat at ~40 req/s while latency rose. Ruled out a capacity problem; scaling out would not have helped. |
| 14:21 | Cause identified in the injection state: `GET /admin/inject` returned `extra_latency_ms: 400`. |
| 14:34 | Mitigated: `curl -XPOST "localhost:8000/admin/inject?latency_ms=0"` |
| 14:36 | 5m slow ratio back under 1%. Alert cleared. |

## Root cause

A runtime configuration value (`extra_latency_ms`) was changed to 400ms on a
running process. No code was deployed and no dependency degraded, so the
change was invisible to `git log` and to the deploy timeline.

The deeper cause is that this value is mutable at runtime through an
unauthenticated endpoint with no audit trail. There was no record of *who*
changed it or *when*, which is why identifying the cause took 19 of the 34
minutes while mitigation itself took 2.

## What went well

- The multi-window alert did its job: paged in 2m20s, and the pairing with a
  5-minute short window meant it cleared within 2 minutes of real recovery
  rather than latching for an hour.
- Separating the latency SLO from availability caught an incident that an
  availability-only SLO would have scored as a perfectly healthy 100%.
- The heatmap panel answered "systemic or tail?" immediately. A
  `histogram_quantile` p99 number alone would not have distinguished them.

## What went badly

- **19 minutes to find the cause, 2 to fix it.** Time-to-mitigate was
  dominated entirely by time-to-identify.
- **Runtime config changes were not observable.** No metric, log line, or
  dashboard annotation marked the change. The first four runbook hypotheses
  (deploy, dependency, traffic, saturation) were all checked and discarded
  before anyone thought to inspect mutable state.
- **The runbook did not mention runtime config.** It listed "config or flag
  change" as cause #2 but gave no command to check it. It does now.

## Action items

| # | Action | Type | Owner | Status |
|---|---|---|---|---|
| 1 | Export injection state as a gauge (`checkout_inject_latency_ms`) so config drift is visible on the dashboard | Detect | — | Open |
| 2 | Add a Grafana annotation whenever `/admin/inject` is called | Detect | — | Open |
| 3 | Require auth on `/admin/inject`, or compile it out of non-dev builds | Prevent | — | Open |
| 4 | Add "check mutable runtime config" with a concrete command to the latency runbook | Respond | — | **Done** |
| 5 | Alert on `checkout_inject_latency_ms > 0` outside dev | Detect | — | Open |

## Lessons

The alerting worked and the mitigation was trivial. Nearly all the lost time
came from a gap in **observability of configuration** rather than of traffic.
Metrics covered what the service was doing to requests but not what had been
done to the service.

A corollary worth stating: an endpoint that can degrade production needs the
same audit discipline as a deploy. It bypassed every safeguard — code review,
CI, deploy log — because it was "just a config value".
