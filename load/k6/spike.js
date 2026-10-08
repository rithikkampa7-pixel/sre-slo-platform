// Spike test. Pair this with fault injection to watch a fast-burn page fire:
//
//   curl -XPOST "localhost:8000/admin/inject?error_rate=0.05"
//   k6 run load/k6/spike.js
//   docker compose logs -f alert-sink
//
// 5% errors is 50x the 0.1% budget, so AvailabilityErrorBudgetBurnFast
// should fire within about 2-3 minutes (2m `for:` plus scrape delay).
import http from "k6/http";
import { sleep } from "k6";

export const options = {
  stages: [
    { duration: "30s", target: 50 },
    { duration: "3m", target: 200 },
    { duration: "30s", target: 0 },
  ],
  // No thresholds: this run is EXPECTED to breach the SLO. The point is to
  // prove the alerting detects it, not to pass.
};

const BASE = __ENV.BASE_URL || "http://localhost:8000";

export default function () {
  http.get(`${BASE}/checkout`);
  sleep(0.1);
}
