.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help up down logs validate load spike reset burn

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

up: ## Bring up the whole stack
	$(COMPOSE) up -d --build
	@echo
	@echo "  Grafana      http://localhost:3000  (SLO / checkout-api SLO Overview)"
	@echo "  Prometheus   http://localhost:9090/alerts"
	@echo "  Service      http://localhost:8000/checkout"

down: ## Tear everything down, including stored metrics
	$(COMPOSE) down -v

logs: ## Follow delivered alerts
	$(COMPOSE) logs -f alert-sink

validate: ## Lint rules, config and dashboards (same checks CI runs)
	@echo "==> promtool: rules"
	@docker run --rm -v $(PWD)/observability/prometheus:/w --entrypoint promtool \
	  prom/prometheus:v3.1.0 check rules /w/rules/sli-recording.yaml /w/rules/slo-burn-rate.yaml
	@echo "==> promtool: config"
	@docker run --rm -v $(PWD)/observability/prometheus:/w --entrypoint promtool \
	  prom/prometheus:v3.1.0 check config /w/prometheus.yml
	@echo "==> amtool: alertmanager config"
	@docker run --rm -v $(PWD)/observability/alertmanager:/w --entrypoint amtool \
	  prom/alertmanager:v0.28.0 check-config /w/alertmanager.yml
	@echo "==> compose config"
	@$(COMPOSE) config -q
	@echo "==> dashboard JSON"
	@python3 -c "import json,glob;[json.load(open(f)) for f in glob.glob('observability/grafana/dashboards/*.json')];print('ok')"

load: ## Steady baseline traffic (needs k6)
	k6 run load/k6/steady.js

burn: ## Inject 5% errors and spike traffic until a page fires
	curl -fsS -XPOST "http://localhost:8000/admin/inject?error_rate=0.05" && echo
	k6 run load/k6/spike.js

reset: ## Clear all injected faults
	curl -fsS -XPOST "http://localhost:8000/admin/inject?error_rate=0.002&latency_ms=0" && echo
