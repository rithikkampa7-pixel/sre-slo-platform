# Runbook — AvailabilityErrorBudgetBurn*

**Alert fired because:** the 5xx ratio exceeded the burn-rate threshold on both
a long and a short window. See [slo-definitions.md](./slo-definitions.md).

## 1. Decide if this is real (60 seconds)

```bash
# Current error ratio across all windows at once
curl -s 'http://localhost:9090/api/v1/query?query=sli:availability:error_ratio_rate5m' \
  | python3 -m json.tool
```

Then check whether the SLI is even reporting:

```bash
curl -s 'http://localhost:9090/api/v1/query?query=up{job="checkout-api"}'
```

- `up == 0` → this is not an error-rate problem, it is a **down** problem.
  Skip to step 4.
- No data at all → `SLIDataMissing` should also be firing. The monitoring is
  broken; you are flying blind. Fix observability first.

## 2. Establish blast radius

```bash
# Which routes are failing?
curl -s --get 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum by (route,status) (rate(http_requests_total[5m]))'
```

If failures are confined to one route, the problem is almost certainly in that
handler or a dependency it alone uses. If every route fails equally, suspect
something shared: the process, a connection pool, or the host.

## 3. Check for a trigger

Reliability incidents are overwhelmingly caused by change. In order of
likelihood:

1. **A deploy.** `git log --oneline -10` and compare against the alert start
   time. If they line up, roll back first and diagnose afterwards.
2. **A config or flag change.** These are not in `git log` and are the most
   commonly missed cause.
3. **A dependency.** Check its status page and its own SLO dashboard.
4. **Traffic.** Compare `sum(rate(http_requests_total[5m]))` to the same hour
   last week. A 10x spike is a capacity incident, not a code bug.

## 4. Mitigate before you diagnose

Restoring service and finding the root cause are separate activities, and the
first one wins. In order of preference:

```bash
# Roll back to the previous known-good image
docker compose up -d --force-recreate checkout-api

# If a specific dependency is the cause, shed load from it rather than
# letting it take the whole service down.
```

Write down what you changed and at what time, as you go. You will not
remember accurately in 40 minutes, and the postmortem depends on it.

## 5. Confirm recovery

The short window in each alert exists so recovery is detected quickly, but it
still needs a full window to clear. Expect:

- `AvailabilityErrorBudgetBurnFast` — clears ~5-7 minutes after real recovery.
- `AvailabilityErrorBudgetBurnSlow` — up to 30 minutes.

If the alert clears but the 1h ratio is still elevated, you have mitigated the
spike without fixing the leak. Do not close the incident.

## 6. Afterwards

If this consumed more than 10% of the 30-day error budget, it warrants a
postmortem. See [postmortem-2026-10-01.md](./postmortem-2026-10-01.md) for the
template actually used in this repo.

## Reproducing this alert deliberately

```bash
curl -XPOST "http://localhost:8000/admin/inject?error_rate=0.05"
k6 run load/k6/spike.js
docker compose logs -f alert-sink      # watch the page arrive
curl -XPOST "http://localhost:8000/admin/inject?error_rate=0.002"  # reset
```
