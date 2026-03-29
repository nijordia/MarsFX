.PHONY: help create-cluster delete-cluster deploy-namespaces deploy-ingress deploy-storage deploy-secrets deploy-pgbouncer deploy-lakekeeper deploy-trino deploy-kafka deploy-arroyo seed-data deploy clean clean-kafka clean-arroyo status

# Configuration
CLUSTER_NAME := marsfx
KIND_CONFIG := manifests/cluster/config.yaml
KUBECTL := kubectl

# Namespace definitions
NS_INGRESS := ingress-nginx
NS_DATA_INGRESS := data-ingress
NS_DATA_STORAGE := data-storage
NS_DATA_PGBOUNCER := data-pgbouncer
NS_DATA_LAKEKEEPER := data-lakekeeper
NS_DATA_TRINO := data-trino
NS_DATA_KAFKA := data-kafka
NS_DATA_ARROYO := data-arroyo
NS_DATA_DAGSTER := data-dagster

help: ## Show this help message
	@echo "🪐 MarsFX - Interplanetary Currency Exchange Platform"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

create-cluster: ## Create kind cluster with ingress configuration
	@echo "🐳 Creating kind cluster: $(CLUSTER_NAME)"
	@if kind get clusters | grep -q "^$(CLUSTER_NAME)$$"; then \
		echo "⚠️  Cluster $(CLUSTER_NAME) already exists"; \
	else \
		kind create cluster --name $(CLUSTER_NAME) --config $(KIND_CONFIG); \
		echo "✅ Cluster created successfully"; \
	fi
	@echo "📋 Cluster info:"
	@kubectl cluster-info --context kind-$(CLUSTER_NAME)

delete-cluster: ## Delete the kind cluster
	@echo "🗑️  Deleting kind cluster: $(CLUSTER_NAME)"
	@kind delete cluster --name $(CLUSTER_NAME)
	@echo "✅ Cluster deleted"

deploy-namespaces: ## Create all required namespaces
	@echo "📦 Creating namespaces"
	@$(KUBECTL) apply -k manifests/namespaces/
	@echo "✅ Namespaces created"
	@$(KUBECTL) get namespaces | grep "data-"

deploy-ingress: deploy-namespaces ## Deploy ingress-nginx controller
	@echo "🌐 Deploying ingress-nginx"
	@helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx || true
	@helm repo update
	@helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
		--namespace $(NS_INGRESS) \
		--create-namespace \
		--values manifests/ingress/nginx-values.yaml \
		--wait=false
	@echo "⏳ Waiting for ingress controller to be ready..."
	@$(KUBECTL) wait --namespace $(NS_INGRESS) \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/component=controller \
		--timeout=300s
	@echo "✅ Ingress controller ready"

deploy-storage: deploy-namespaces ## Deploy PostgreSQL and MinIO
	@echo "💾 Deploying storage layer (PostgreSQL + MinIO)"
	@$(KUBECTL) apply -k manifests/storage/
	@echo "⏳ Waiting for PostgreSQL to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_STORAGE) \
		--for=condition=ready pod \
		--selector=app=postgres \
		--timeout=300s || true
	@sleep 10
	@echo "⏳ Waiting for MinIO to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_STORAGE) \
		--for=condition=ready pod \
		--selector=app=minio \
		--timeout=300s || true
	@echo "⏳ Running MinIO bucket initialization..."
	@$(KUBECTL) delete job/minio-uploader -n $(NS_DATA_STORAGE) 2>/dev/null || true
	@$(KUBECTL) apply -f manifests/storage/minio-uploader.yaml
	@sleep 5
	@echo "✅ Storage layer ready"
	@echo "📊 MinIO Console: http://localhost:9001 (admin/minioadmin)"
	@echo "📊 PostgreSQL: localhost:5432 (postgres/postgres)"

deploy-secrets: deploy-namespaces ## Create all secrets
	@echo "🔐 Creating secrets"
	@$(KUBECTL) apply -k manifests/secrets/
	@echo "✅ Secrets created"

deploy-pgbouncer: deploy-storage deploy-secrets ## Deploy PgBouncer connection pooler
	@echo "🔌 Deploying PgBouncer"
	@helm upgrade --install pgbouncer manifests/pgbouncer/chart/ \
		--namespace $(NS_DATA_PGBOUNCER) \
		--create-namespace
	@echo "⏳ Waiting for PgBouncer to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_PGBOUNCER) \
		--for=condition=ready pod \
		--selector=app=pgbouncer \
		--timeout=300s
	@echo "✅ PgBouncer ready"

deploy-lakekeeper: deploy-pgbouncer ## Deploy Lakekeeper Iceberg REST catalog
	@echo "🏔️  Deploying Lakekeeper"
	@helm repo add lakekeeper https://lakekeeper.github.io/lakekeeper-charts/ || true
	@helm repo update
	@helm upgrade --install lakekeeper-chart lakekeeper/lakekeeper \
		--namespace $(NS_DATA_LAKEKEEPER) \
		--create-namespace \
		-f manifests/lakekeeper/chart/values.yaml
	@echo "⏳ Waiting for Lakekeeper deployment to rollout..."
	@$(KUBECTL) rollout status deployment/lakekeeper-chart -n $(NS_DATA_LAKEKEEPER)
	@echo "⏳ Waiting for Lakekeeper pod to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_LAKEKEEPER) \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/name=lakekeeper,app.kubernetes.io/component=catalog \
		--timeout=300s
	@sleep 5
	@echo "🌱 Running Lakekeeper bootstrap"
	@$(KUBECTL) apply -f manifests/lakekeeper/config/bootstrap.yaml
	@$(KUBECTL) wait --namespace $(NS_DATA_LAKEKEEPER) \
		--for=condition=complete job/lakekeeper-bootstrap \
		--timeout=120s || true
	@echo "✅ Lakekeeper ready"
	@echo "📊 Lakekeeper REST API: http://localhost:8181"

deploy-trino: deploy-lakekeeper ## Deploy Trino query engine
	@echo "🔱 Deploying Trino"
	@helm repo add trino https://trinodb.github.io/charts || true
	@helm repo update
	@helm upgrade --install trino trino/trino \
		--namespace $(NS_DATA_TRINO) \
		--create-namespace \
		--values manifests/trino/values.yaml \
		--values manifests/trino/values.secret.yaml
	@echo "⏳ Waiting for Trino coordinator to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_TRINO) \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/component=coordinator \
		--timeout=600s
	@echo "✅ Trino ready"
	@echo "📊 Trino UI: http://localhost:8080"

deploy-kafka: deploy-namespaces ## Deploy Kafka broker
	@echo "📨 Deploying Kafka broker"
	@$(KUBECTL) apply -k manifests/kafka/
	@echo "⏳ Waiting for Kafka broker to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_KAFKA) \
		--for=condition=ready pod \
		--selector=app=kafka,component=broker --timeout=300s
	@sleep 10
	@echo "📋 Creating Kafka topics..."
	@$(KUBECTL) delete job/kafka-create-topics -n $(NS_DATA_KAFKA) 2>/dev/null || true
	@$(KUBECTL) apply -f manifests/jobs/kafka-create-topics.yaml
	@$(KUBECTL) wait --namespace $(NS_DATA_KAFKA) \
		--for=condition=complete job/kafka-create-topics --timeout=120s || true
	@echo "✅ Kafka ready at localhost:9092"
	@echo "📊 Topics: marsfx.raw.ticks (6 partitions), marsfx.raw.events (3 partitions)"

deploy-arroyo: deploy-kafka deploy-storage ## Deploy Arroyo stream processor
	@echo "🌊 Deploying Arroyo stream processor"
	@echo "⏳ Creating Arroyo database..."
	@$(KUBECTL) apply -f manifests/arroyo/arroyo-init-job.yaml
	@$(KUBECTL) apply -f manifests/arroyo/arroyo-secrets.yaml
	@$(KUBECTL) wait --namespace $(NS_DATA_ARROYO) \
		--for=condition=complete job/arroyo-init --timeout=120s || true
	@echo "⏳ Installing Arroyo via Helm..."
	@helm repo add arroyo https://arroyosystems.github.io/helm-repo || true
	@helm repo update
	@helm upgrade --install arroyo arroyo/arroyo \
		--namespace $(NS_DATA_ARROYO) \
		--create-namespace \
		-f manifests/arroyo/values.yaml \
		-f manifests/arroyo/values.secret.yaml
	@echo "⏳ Waiting for Arroyo pods to be ready..."
	@$(KUBECTL) wait --namespace $(NS_DATA_ARROYO) \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/name=arroyo --timeout=300s
	@echo "⏳ Exposing Arroyo UI via NodePort..."
	@$(KUBECTL) patch svc arroyo -n $(NS_DATA_ARROYO) \
		-p '{"spec": {"type": "NodePort", "ports": [{"name": "http", "port": 80, "targetPort": "http", "nodePort": 30115}]}}'
	@echo "✅ Arroyo ready at http://localhost:5115"
	@echo "📊 Access Arroyo UI to create streaming pipelines"

build-images: ## Build custom Docker images for data loading
	@echo "🏗️  Building custom Docker images"
	@docker build -t marsfx-data-loader:latest -f manifests/docker/Dockerfile.data-loader .
	@echo "📦 Loading images into kind cluster"
	@kind load docker-image marsfx-data-loader:latest --name $(CLUSTER_NAME)
	@echo "✅ Images built and loaded"

seed-data: deploy-trino build-images ## Seed initial FX reference data
	@echo "🌱 Seeding initial FX reference data"
	@$(KUBECTL) apply -f manifests/jobs/seed-currency-pairs.yaml
	@$(KUBECTL) apply -f manifests/jobs/seed-economic-calendar.yaml
	@echo "⏳ Waiting for seed jobs to complete..."
	@$(KUBECTL) wait --namespace $(NS_DATA_INGRESS) \
		--for=condition=complete job/seed-currency-pairs \
		--timeout=300s || true
	@$(KUBECTL) wait --namespace $(NS_DATA_INGRESS) \
		--for=condition=complete job/seed-economic-calendar \
		--timeout=300s || true
	@echo "✅ Reference data seeded"

deploy: create-cluster deploy-ingress deploy-secrets deploy-storage deploy-pgbouncer deploy-lakekeeper deploy-trino deploy-kafka deploy-arroyo ## Deploy entire stack
	@echo ""
	@echo "✨ MarsFX platform deployed successfully!"
	@echo ""
	@echo "🌐 Access Points:"
	@echo "  • Trino UI:      http://localhost:8080"
	@echo "  • Arroyo UI:     http://localhost:5115"
	@echo "  • MinIO Console: http://localhost:9001 (admin/minioadmin)"
	@echo "  • Lakekeeper:    http://localhost:8181"
	@echo "  • Kafka:         localhost:9092"
	@echo ""
	@echo "📦 Next steps:"
	@echo "  • Run 'make seed-data' to load reference data"
	@echo "  • Run 'make status' to check component health"
	@echo "  • Test streaming: cd python && python main.py run --duration 60"
	@echo "  • Create Arroyo pipelines at http://localhost:5115"
	@echo "  • Configure dbt with 'cd dbt && dbt deps && dbt debug'"

clean: ## Clean all deployments (keep cluster)
	@echo "🧹 Cleaning all deployments"
	@helm uninstall arroyo -n $(NS_DATA_ARROYO) || true
	@$(KUBECTL) delete -k manifests/kafka/ || true
	@helm uninstall trino -n $(NS_DATA_TRINO) || true
	@helm uninstall lakekeeper-chart -n $(NS_DATA_LAKEKEEPER) || true
	@helm uninstall pgbouncer -n $(NS_DATA_PGBOUNCER) || true
	@helm uninstall ingress-nginx -n $(NS_INGRESS) || true
	@$(KUBECTL) delete -k manifests/storage/ || true
	@$(KUBECTL) delete -k manifests/secrets/ || true
	@$(KUBECTL) delete -f manifests/namespaces/ || true
	@echo "✅ Cleanup complete"

clean-kafka: ## Remove Kafka deployment
	@echo "🧹 Removing Kafka..."
	@$(KUBECTL) delete -k manifests/kafka/ || true
	@$(KUBECTL) delete job/kafka-create-topics -n $(NS_DATA_KAFKA) || true
	@echo "✅ Kafka removed"

clean-arroyo: ## Remove Arroyo deployment
	@echo "🧹 Removing Arroyo..."
	@helm uninstall arroyo -n $(NS_DATA_ARROYO) || true
	@$(KUBECTL) delete job/arroyo-init -n $(NS_DATA_ARROYO) || true
	@$(KUBECTL) delete secret/arroyo-secrets -n $(NS_DATA_ARROYO) || true
	@echo "✅ Arroyo removed"

status: ## Check status of all components
	@echo "📊 MarsFX Platform Status"
	@echo ""
	@echo "🐳 Cluster:"
	@kind get clusters | grep $(CLUSTER_NAME) && echo "  ✅ Cluster running" || echo "  ❌ Cluster not found"
	@echo ""
	@echo "📦 Namespaces:"
	@$(KUBECTL) get namespaces | grep "data-" || echo "  ❌ No data namespaces found"
	@echo ""
	@echo "💾 Storage Layer:"
	@$(KUBECTL) get pods -n $(NS_DATA_STORAGE) -o wide 2>/dev/null || echo "  ❌ Storage namespace not found"
	@echo ""
	@echo "🔌 PgBouncer:"
	@$(KUBECTL) get pods -n $(NS_DATA_PGBOUNCER) -o wide 2>/dev/null || echo "  ❌ PgBouncer namespace not found"
	@echo ""
	@echo "🏔️  Lakekeeper:"
	@$(KUBECTL) get pods -n $(NS_DATA_LAKEKEEPER) -o wide 2>/dev/null || echo "  ❌ Lakekeeper namespace not found"
	@echo ""
	@echo "🔱 Trino:"
	@$(KUBECTL) get pods -n $(NS_DATA_TRINO) -o wide 2>/dev/null || echo "  ❌ Trino namespace not found"
	@echo ""
	@echo "📨 Kafka:"
	@$(KUBECTL) get pods -n $(NS_DATA_KAFKA) -o wide 2>/dev/null || echo "  ❌ Kafka namespace not found"
	@echo ""
	@echo "🌊 Arroyo:"
	@$(KUBECTL) get pods -n $(NS_DATA_ARROYO) -o wide 2>/dev/null || echo "  ❌ Arroyo namespace not found"

logs-lakekeeper: ## Show Lakekeeper logs
	@$(KUBECTL) logs -n $(NS_DATA_LAKEKEEPER) -l app.kubernetes.io/name=lakekeeper --tail=100 -f

logs-trino: ## Show Trino coordinator logs
	@$(KUBECTL) logs -n $(NS_DATA_TRINO) -l component=coordinator --tail=100 -f

logs-pgbouncer: ## Show PgBouncer logs
	@$(KUBECTL) logs -n $(NS_DATA_PGBOUNCER) -l app=pgbouncer --tail=100 -f

logs-kafka: ## Show Kafka broker logs
	@$(KUBECTL) logs -n $(NS_DATA_KAFKA) -l app=kafka,component=broker --tail=100 -f

logs-arroyo-controller: ## Show Arroyo controller logs
	@$(KUBECTL) logs -n $(NS_DATA_ARROYO) -l app.kubernetes.io/name=arroyo --tail=100 -f

port-forward-trino: ## Port-forward Trino UI
	@echo "🔱 Port-forwarding Trino UI to localhost:8080"
	@$(KUBECTL) port-forward -n $(NS_DATA_TRINO) svc/trino 8080:8080

port-forward-minio: ## Port-forward MinIO console
	@echo "💾 Port-forwarding MinIO console to localhost:9001"
	@$(KUBECTL) port-forward -n $(NS_DATA_STORAGE) svc/minio-console 9001:9001

port-forward-lakekeeper: ## Port-forward Lakekeeper REST API
	@echo "🏔️  Port-forwarding Lakekeeper to localhost:8181"
	@$(KUBECTL) port-forward -n $(NS_DATA_LAKEKEEPER) svc/lakekeeper-chart 8181:8181

port-forward-arroyo: ## Port-forward Arroyo UI
	@echo "🌊 Port-forwarding Arroyo UI to localhost:5115"
	@$(KUBECTL) port-forward -n $(NS_DATA_ARROYO) svc/arroyo 5115:80

bootstrap-lakekeeper: ## Bootstrap Lakekeeper warehouse (run once after deploy)
	@echo "🌱 Bootstrapping Lakekeeper..."
	@$(KUBECTL) apply -f manifests/lakekeeper/config/bootstrap.yaml
	@$(KUBECTL) wait --namespace $(NS_DATA_LAKEKEEPER) \
		--for=condition=complete job/lakekeeper-bootstrap \
		--timeout=120s || true
	@echo "✅ Bootstrap complete"

restart-pods: ## Restart all data platform pods (useful after laptop sleep)
	@echo "🔄 Restarting all pods..."
	@$(KUBECTL) delete pod --all -n $(NS_DATA_LAKEKEEPER)
	@$(KUBECTL) delete pod --all -n $(NS_DATA_TRINO)
	@echo "⏳ Waiting for pods to restart..."
	@sleep 10
	@$(KUBECTL) wait --namespace $(NS_DATA_LAKEKEEPER) \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/name=lakekeeper \
		--timeout=120s
	@$(KUBECTL) wait --namespace $(NS_DATA_TRINO) \
		--for=condition=ready pod \
		--selector=app.kubernetes.io/component=coordinator \
		--timeout=120s
	@echo "✅ Pods restarted"

connect-trino: ## Connect to Trino CLI for interactive queries
	@$(KUBECTL) exec -it -n $(NS_DATA_TRINO) deployment/trino-coordinator -- trino

check-iceberg: ## Check Iceberg tables in Lakekeeper
	@echo "📊 Checking Iceberg tables..."
	@$(KUBECTL) exec -it -n $(NS_DATA_TRINO) deployment/trino-coordinator -- \
		trino --execute "USE lakehouse.fx_data; SHOW TABLES;"