// Baseline traffic. Run this first so the SLIs have a healthy history to
// compare against; burn-rate alerts are meaningless without a baseline.
//
//   k6 run load/k6/steady.js
import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  stages: [
    { duration: "1m", target: 20 },
    { duration: "10m", target: 20 },
    { duration: "1m", target: 0 },
  ],
  thresholds: {
    // Mirrors the SLO, so k6 fails the run on the same bar Prometheus alerts on.
    http_req_failed: ["rate<0.001"],
    http_req_duration: ["p(99)<300"],
  },
};

const BASE = __ENV.BASE_URL || "http://localhost:8000";

export default function () {
  const res = http.get(`${BASE}/checkout`);
  check(res, { "status is 200": (r) => r.status === 200 });
  sleep(Math.random() * 0.5);
}
