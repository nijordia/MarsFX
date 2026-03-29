# 🪐 MarsFX - Interplanetary FX Data Platform

A complete data platform for simulating and analyzing interplanetary currency exchange. Built to learn modern data engineering: streaming pipelines, data lakes, incremental transformations, and semantic layers.

**What it does**: Generates realistic FX tick data → Streams to Kafka → Processes with Arroyo → Stores in Iceberg → Transforms with dbt → Queries with Trino

---

## 📖 Table of Contents

1. [Quick Start (5 minutes)](#quick-start)
2. [Understanding the System](#understanding-the-system)
3. [Architecture](#architecture)
4. [Repository Structure](#repository-structure)
5. [Phase-by-Phase Guide](#phase-by-phase-guide)
6. [Common Operations](#common-operations)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Prerequisites
- Docker Desktop (or Docker Engine on Linux)
- [kind](https://kind.sigs.k8s.io/) installed
- [kubectl](https://kubernetes.io/docs/tasks/tools/) installed
- [Helm](https://helm.sh/docs/intro/install/) installed
- Python 3.11+
- Make

### Initial Setup (One-time, ~5 minutes)

```bash
# 1. Configure hostname access (one-time setup)
sudo nano /etc/hosts
# Add these lines:
# 127.0.0.1 trino.marsfx.local
# 127.0.0.1 minio.marsfx.local
# 127.0.0.1 lakekeeper.marsfx.local

# 2. Set up Trino credentials (one-time setup)
cp manifests/trino/values.secret.yaml.example manifests/trino/values.secret.yaml
# Edit values.secret.yaml with your MinIO credentials (default: admin/minioadmin)

# 3. Create cluster and deploy everything
make deploy

# 4. Bootstrap Lakekeeper (creates warehouse and namespace)
make bootstrap-lakekeeper

# 5. Check status - all pods should be Running
make status
```

### After Laptop Restart/Sleep

Your data persists! Just restart the pods if needed:

```bash
# Check if everything is still running
make status

# If pods are stuck, restart them
make restart-pods
```

### Test the Platform

```bash
# Connect to Trino CLI
make connect-trino

# In Trino CLI, create a test table:
CREATE SCHEMA IF NOT EXISTS iceberg.fx_data;

CREATE TABLE iceberg.fx_data.test_table (
  id INT,
  name VARCHAR,
  created_at TIMESTAMP
) WITH (format = 'PARQUET');

INSERT INTO iceberg.fx_data.test_table VALUES
  (1, 'EUR/USD', CURRENT_TIMESTAMP),
  (2, 'GBP/USD', CURRENT_TIMESTAMP);

SELECT * FROM iceberg.fx_data.test_table;
```

**Access Points** (after port-forwarding):
- Trino UI: `make port-forward-trino` → http://localhost:8080
- MinIO Console: `make port-forward-minio` → http://localhost:9001 (admin/minioadmin)
- Lakekeeper API: `make port-forward-lakekeeper` → http://localhost:8181
- Arroyo UI: `make port-forward-arroyo` → http://localhost:5115
- Kafka: localhost:9092 (directly accessible)

---

## Understanding the System

### The Big Picture

Think of MarsFX as a **real-time FX trading data pipeline** with these steps:

```
1. GENERATE → Python creates realistic tick data
2. STREAM   → Kafka carries messages
3. PROCESS  → Arroyo cleans and enriches
4. STORE    → Iceberg tables hold the data
5. TRANSFORM→ dbt creates OHLC candles
6. QUERY    → Trino lets you analyze
```

### What Each Component Does

| Component | What It Does | Why You Need It |
|-----------|--------------|-----------------|
| **Python Generator** | Creates fake FX ticks and events | Simulates a real trading feed |
| **Kafka** | Message bus for streaming | Decouples producers from consumers |
| **Arroyo** | Real-time stream processor | Cleans data before storage |
| **MinIO** | S3-compatible object storage | Stores Parquet files cheaply |
| **PostgreSQL** | Relational database | Stores Iceberg table metadata |
| **Lakekeeper** | Iceberg catalog server | Manages table schemas and versions |
| **Iceberg** | Table format | Adds ACID transactions to data lakes |
| **Trino** | Distributed SQL engine | Queries Iceberg tables fast |
| **dbt** | Data transformation framework | Creates OHLC candles from ticks |
| **PgBouncer** | Connection pooler | Reduces DB load |

### Data Flow Example

**Scenario**: You want to see 5-minute OHLC candles for ECR/MRT pair

1. **Python** generates 10,000 ticks/sec with realistic prices
2. **Parquet files** written to `data/ticks/2026-03-22/14.parquet`
3. **Load to Iceberg**: Manual step creates `iceberg.fx_data.raw_ticks` table
4. **dbt runs**: Reads raw_ticks → Creates `ohlc_candles_5min` table
5. **Trino query**: `SELECT * FROM iceberg.marts.ohlc_candles_5min WHERE currency_pair = 'ECR/MRT'`

---

## Architecture

### Kubernetes Namespaces

```
data-ingress     → Nginx ingress controller
data-storage     → PostgreSQL, MinIO
data-pgbouncer   → PgBouncer connection pooler
data-lakekeeper  → Lakekeeper catalog server
data-trino       → Trino coordinator + workers
data-kafka       → Kafka cluster
data-arroyo      → Arroyo stream processor
data-dagster     → Dagster orchestration (Phase 5)
```

### Data Layers

```
┌────────────────────────────────────────────────┐
│ GENERATION LAYER (Python)                      │
│ • fx_generator: Tick generation with GBM       │
│ • event_generator: Economic events             │
│ • Output: Kafka + Parquet files                │
└────────────────────────────────────────────────┘
                     ↓
┌────────────────────────────────────────────────┐
│ STREAMING LAYER (Kafka + Arroyo)               │
│ • Kafka: marsfx.raw.ticks (6 partitions)       │
│ • Arroyo: Kafka source → Iceberg sink          │
│ • Writes Parquet to MinIO every 30 seconds     │
└────────────────────────────────────────────────┘
                     ↓
┌────────────────────────────────────────────────┐
│ STORAGE LAYER (Iceberg)                        │
│ • fx_data.raw_ticks_streaming                  │
│ • Managed by Lakekeeper REST catalog           │
│ • Format: Parquet on MinIO                     │
└────────────────────────────────────────────────┘
                     ↓
┌────────────────────────────────────────────────┐
│ TRANSFORMATION LAYER (dbt)                     │
│ • staging.stg_fx_ticks (cleaned)               │
│ • marts.ohlc_candles_1min                      │
│ • marts.ohlc_candles_5min                      │
│ • marts.ohlc_candles_1h                        │
│ • marts.ohlc_candles_1d                        │
└────────────────────────────────────────────────┘
                     ↓
┌────────────────────────────────────────────────┐
│ QUERY LAYER (Trino)                            │
│ • Interactive SQL queries                      │
│ • Time-travel (Iceberg snapshots)              │
│ • Partition pruning for speed                  │
└────────────────────────────────────────────────┘
```

---

## Repository Structure

```
MarsFX/
├── Makefile                    # All deployment commands
│
├── manifests/                  # Kubernetes YAML files
│   ├── cluster/config.yaml     # kind cluster definition
│   ├── namespaces/             # 8 namespace definitions
│   ├── storage/                # PostgreSQL + MinIO
│   ├── secrets/                # All credentials
│   ├── pgbouncer/chart/        # PgBouncer Helm chart
│   ├── lakekeeper/             # Lakekeeper Helm chart + bootstrap
│   ├── trino/values.yaml       # Trino + Iceberg config
│   ├── kafka/                  # Kafka broker (KRaft mode)
│   ├── arroyo/                 # Arroyo stream processor (Helm values)
│   └── jobs/                   # One-time jobs (topics, DB init)
│
├── python/                     # Data generator
│   ├── fx_generator/           # Main generator package
│   │   ├── models.py           # Pydantic data models
│   │   ├── price_simulator.py # GBM price simulation
│   │   ├── event_generator.py # Economic events
│   │   └── tick_generator.py  # Main orchestrator
│   ├── config/
│   │   └── generator_config.yaml # All settings
│   ├── tests/                  # Validation tests
│   ├── main.py                 # CLI entrypoint
│   └── requirements.txt
│
└── dbt/                        # Data transformations
    ├── dbt_project.yml         # Project config
    ├── profiles.yml            # Trino connection
    ├── models/
    │   ├── sources.yaml        # Source definitions
    │   ├── staging/
    │   │   ├── stg_fx_ticks.sql       # Clean raw data
    │   │   └── schema.yml
    │   └── marts/
    │       ├── ohlc_candles_1min.sql  # 1-minute candles
    │       ├── ohlc_candles_5min.sql  # 5-minute candles
    │       ├── ohlc_candles_1h.sql    # Hourly candles
    │       ├── ohlc_candles_1d.sql    # Daily candles
    │       └── schema.yml              # Tests
    ├── macros/
    │   └── ohlc_helpers.sql    # Reusable functions
    ├── seeds/
    │   └── currency_pairs.csv  # Reference data
    └── tests/                  # Custom tests
```

---

## Phase-by-Phase Guide

### Phase 1: Infrastructure (DONE ✅)

**What**: Deploy Kubernetes cluster with storage layer

**Files to understand**:
1. `Makefile` - Commands like `make deploy`, `make status`
2. `manifests/cluster/config.yaml` - kind cluster with 3 nodes
3. `manifests/storage/postgres.yaml` - Database for Iceberg metadata
4. `manifests/storage/minio.yaml` - Object storage for Parquet files
5. `manifests/lakekeeper/chart/values.yaml` - Iceberg catalog server config
6. `manifests/trino/values.yaml` - SQL query engine config

**Deploy**:
```bash
make deploy  # Creates cluster + deploys everything
make status  # Check if pods are running
```

**Verify**:
```bash
# All pods should be Running
kubectl get pods --all-namespaces
```

---

### Phase 2: Data Generation (DONE ✅)

**What**: Generate realistic FX tick data with Python

**Files to understand**:
1. `python/main.py` - CLI interface (try `python main.py --help`)
2. `python/config/generator_config.yaml` - All settings (tick rate, pairs, events)
3. `python/fx_generator/models.py` - Data structures (FXTick, EconomicEvent)
4. `python/fx_generator/price_simulator.py` - Geometric Brownian Motion pricing
5. `python/fx_generator/tick_generator.py` - Main generator logic

**Key Concepts**:
- **6 currency pairs**: ECR/MRT, ECR/LCR, ECR/AMC, MRT/LCR, MRT/AMC, LCR/AMC
- **Tick rate**: 10 ticks/sec/pair = 60 ticks/sec total
- **Time acceleration**: 60x (1 hour simulated = 1 minute real)
- **Checkpointing**: Resume from last position
- **Output**: Parquet files organized by date/hour

**Generate data**:
```bash
cd python
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Generate 5 minutes of data
python main.py run --no-kafka --duration 300

# Check output
ls -lh data/ticks/*/
```

**Output location**: `python/data/ticks/YYYY-MM-DD/HH.parquet`

**Run tests**:
```bash
python tests/test_validation.py
```

---

### Phase 3: dbt Transformations (DONE ✅)

**What**: Transform raw ticks into OHLC candles

**Files to understand**:
1. `dbt/dbt_project.yml` - Project configuration (lookback windows, partitions)
2. `dbt/models/sources.yaml` - Defines source table `iceberg.fx_data.raw_ticks`
3. `dbt/models/staging/stg_fx_ticks.sql` - Cleans raw data (type casting, filters)
4. `dbt/models/marts/ohlc_candles_1min.sql` - Creates 1-minute candles
5. `dbt/macros/ohlc_helpers.sql` - Reusable functions

**Key Concepts**:
- **Incremental models**: Only process new data (not full refresh every time)
- **Lookback windows**: Reprocess last N minutes to capture late-arriving data
  - 1-min candles: 5-minute lookback
  - 5-min candles: 15-minute lookback
  - 1-hour candles: 2-hour lookback
  - Daily candles: 1-day lookback
- **OHLC calculation**: Uses `row_number()` for deterministic open/close prices
- **Iceberg partitioning**: Uses transform functions like `hour(timestamp)`

**Run dbt**:
```bash
cd dbt

# Test connection
dbt debug

# Install dependencies
dbt deps

# Load reference data
dbt seed

# Run all models (first time)
dbt run --full-refresh

# Run incrementally (after first time)
dbt run

# Run tests
dbt test

# Generate docs
dbt docs generate
dbt docs serve  # Open http://localhost:8080
```

**Models created**:
- `iceberg.staging.stg_fx_ticks` (view)
- `iceberg.marts.ohlc_candles_1min` (table)
- `iceberg.marts.ohlc_candles_5min` (table)
- `iceberg.marts.ohlc_candles_1h` (table)
- `iceberg.marts.ohlc_candles_1d` (table)

---

### Phase 4: Stream Processing with Kafka + Arroyo (DONE ✅)

**What**: Real-time streaming pipeline: Python → Kafka → Arroyo → Iceberg → Trino

**Files to understand**:
1. `manifests/kafka/kafka-configmap.yaml` - KRaft configuration (no ZooKeeper)
2. `manifests/kafka/kafka-broker.yaml` - Single-broker deployment with EmptyDir storage
3. `manifests/kafka/kafka-service.yaml` - ClusterIP + NodePort services
4. `manifests/jobs/kafka-create-topics.yaml` - Topic creation job
5. `manifests/arroyo/values.yaml` - Arroyo Helm chart config (PostgreSQL, MinIO credentials, worker env)
6. `manifests/arroyo/arroyo-init-job.yaml` - Creates Arroyo database in PostgreSQL
7. `manifests/lakekeeper/config/bootstrap.yaml` - Warehouse config (sts-enabled and remote-signing-enabled must be false for MinIO)
8. `python/config/generator_config.yaml` - Kafka producer configuration

**Key Concepts**:
- **Kafka KRaft mode**: Consensus protocol replacing ZooKeeper
- **Single broker**: Simplified for learning (not production-ready)
- **EmptyDir volumes**: Ephemeral storage (survives pod restarts, not cluster deletion)
- **Port mapping**: localhost:9092 → kind:30092 → kafka-external → pod:9094
- **Topics**: marsfx.raw.ticks (6 partitions), marsfx.raw.events (3 partitions)
- **Arroyo**: Deployed via Helm chart, runs controller + compiler + API in one pod, spawns worker pods per pipeline
- **Arroyo workers**: Dynamically created by Kubernetes scheduler when a pipeline is launched
- **Iceberg sink**: Arroyo writes Parquet files directly to MinIO via the Lakekeeper REST catalog
- **Iceberg partitioning**: Uses `PARTITIONED BY (day(transaction_timestamp))` — partition info lives in Iceberg metadata, not S3 folder paths (unlike Hive). Verify via Trino `$partitions` metadata table
- **Type casting**: Kafka source reads all fields as TEXT; the INSERT uses CAST to convert to TIMESTAMP/DOUBLE for the Iceberg sink
- **Lakekeeper settings**: `sts-enabled: false` and `remote-signing-enabled: false` are required so Arroyo uses its own MinIO credentials instead of Lakekeeper-vended tokens

**Deploy**:
```bash
# Deploy everything (including Kafka + Arroyo)
make deploy

# Or individually
make deploy-kafka
make deploy-arroyo
```

**Create the Arroyo streaming pipeline**:

1. Open Arroyo UI: http://localhost:5115 (or `make port-forward-arroyo`)
2. Create a new pipeline and paste this SQL:

```sql
CREATE TABLE kafka_ticks (
  tick_id TEXT,
  transaction_timestamp TEXT,
  currency_pair TEXT,
  bid_price TEXT,
  ask_price TEXT,
  mid_price TEXT,
  spread_bps DOUBLE,
  trade_price TEXT,
  volume TEXT,
  exchange_location TEXT,
  trader_type TEXT,
  event_time TEXT
) WITH (
  type = 'source',
  connector = 'kafka',
  bootstrap_servers = 'kafka-broker.data-kafka.svc.cluster.local:9092',
  topic = 'marsfx.raw.ticks',
  format = 'json',
  'source.offset' = 'earliest'
);

CREATE TABLE iceberg_ticks (
  tick_id TEXT,
  transaction_timestamp TIMESTAMP,
  currency_pair TEXT,
  bid_price DOUBLE,
  ask_price DOUBLE,
  mid_price DOUBLE,
  spread_bps DOUBLE,
  trade_price DOUBLE,
  volume DOUBLE,
  exchange_location TEXT,
  trader_type TEXT,
  event_time TIMESTAMP
) WITH (
  connector = 'iceberg',
  'catalog.type' = 'rest',
  'catalog.rest.url' = 'http://lakekeeper-chart.data-lakekeeper.svc.cluster.local:8181/catalog',
  'catalog.warehouse' = 'marsfx',
  namespace = 'fx_data',
  table_name = 'raw_ticks_streaming',
  type = 'sink',
  format = 'parquet',
  'rolling_policy.interval' = interval '30 seconds'
) PARTITIONED BY (day(transaction_timestamp));

INSERT INTO iceberg_ticks
SELECT
  tick_id,
  CAST(transaction_timestamp AS TIMESTAMP),
  currency_pair,
  CAST(bid_price AS DOUBLE),
  CAST(ask_price AS DOUBLE),
  CAST(mid_price AS DOUBLE),
  spread_bps,
  CAST(trade_price AS DOUBLE),
  CAST(volume AS DOUBLE),
  exchange_location,
  trader_type,
  CAST(event_time AS TIMESTAMP)
FROM kafka_ticks;
```

3. Click **Launch** (not Preview)

**Generate data and verify end-to-end**:
```bash
cd python
source venv/bin/activate

# Send data through the pipeline
python main.py run --duration 60

# Verify data in Kafka
kubectl run kafka-test --rm -i --restart=Never \
  --image=confluentinc/cp-kafka:7.6.0 \
  --namespace=data-kafka \
  -- kafka-console-consumer \
  --bootstrap-server kafka-broker:9092 \
  --topic marsfx.raw.ticks \
  --from-beginning \
  --max-messages 5

# Verify data landed in Iceberg (via Trino)
kubectl exec -it -n data-trino deployment/trino-coordinator -- trino \
  --execute "SELECT count(*) FROM iceberg.fx_data.raw_ticks_streaming"

# Query sample data
kubectl exec -it -n data-trino deployment/trino-coordinator -- trino \
  --execute "SELECT currency_pair, bid_price, ask_price, volume FROM iceberg.fx_data.raw_ticks_streaming LIMIT 5"

# Verify partitioning (should show transaction_timestamp_day partitions)
kubectl exec -it -n data-trino deployment/trino-coordinator -- trino \
  --execute "SELECT * FROM iceberg.fx_data.\"raw_ticks_streaming\$partitions\""

# Aggregation query (numeric types enable proper AVG, SUM, etc.)
kubectl exec -it -n data-trino deployment/trino-coordinator -- trino \
  --execute "SELECT currency_pair, count(*) as ticks, round(avg(bid_price), 4) as avg_bid, round(avg(spread_bps), 2) as avg_spread FROM iceberg.fx_data.raw_ticks_streaming GROUP BY currency_pair ORDER BY ticks DESC"
```

**Troubleshooting Arroyo pipelines**:
```bash
# Watch worker logs in real-time (run before launching pipeline)
while true; do
  POD=$(kubectl get pods -n data-arroyo --no-headers 2>/dev/null | grep "arroyo-worker" | head -1 | awk '{print $1}')
  if [ -n "$POD" ]; then
    echo "=== Found worker: $POD ==="
    kubectl logs -n data-arroyo "$POD" -f 2>/dev/null
  fi
  sleep 1
done

# Check controller logs
make logs-arroyo-controller

# Common issues:
# - "InvalidAccessKeyId": Check AWS_ACCESS_KEY_ID in arroyo values.yaml matches MinIO (admin, not minioadmin)
# - "Connection refused": Race condition on controller restart, delete pipeline and recreate
# - "channel closed": Usually a cascading panic from an upstream error, check worker logs for root cause
```

---

### Phase 5: dbt Transformations (DONE ✅)

**What**: Transform raw tick data into OHLC candles using dbt + Trino + Iceberg

**Files to understand**:
1. `dbt/dbt_project.yml` - Project config, model materialization settings, lookback windows
2. `dbt/profiles.yml` - Trino connection profiles (dev, prod, local)
3. `dbt/models/sources.yaml` - Source definitions (raw_ticks_streaming, economic_events)
4. `dbt/models/staging/stg_fx_ticks.sql` - Staging model: type casting, currency pair splitting, data quality filters
5. `dbt/models/marts/ohlc_candles_*.sql` - OHLC candle models (1min, 5min, 1h, 1d)
6. `dbt/macros/ohlc_helpers.sql` - Reusable OHLC calculation macros
7. `dbt/seeds/currency_pairs.csv` - Reference data for currency pairs
8. `dbt/tests/verify_ohlc_logic.sql` - Custom OHLC validity test

**Key Concepts**:
- **Iceberg REST catalog**: Does not support views — all dbt models materialized as tables
- **Incremental merge strategy**: OHLC models use `MERGE INTO` with lookback windows to handle late-arriving data
- **Iceberg partitioning via dbt**: Uses `properties={"partitioning": "ARRAY['hour(candle_timestamp)']"}` in model config
- **Trino syntax**: No PostgreSQL-style casts (`::integer`), use `CAST(x AS integer)` and Trino interval syntax (`interval '1' minute * N`)
- **OHLC calculation**: Uses `row_number()` window functions for deterministic open/close price identification

**Models created**:
| Model | Rows | Granularity | Partitioned By |
|-------|------|-------------|---------------|
| `stg_fx_ticks` | 14,424 | tick-level | — |
| `ohlc_candles_1min` | 366 | 1-minute | hour |
| `ohlc_candles_5min` | 78 | 5-minute | day |
| `ohlc_candles_1h` | 12 | hourly | month |
| `ohlc_candles_1d` | 6 | daily | year |

**Setup and run**:
```bash
# Port-forward Trino for local dbt access
kubectl port-forward -n data-trino svc/trino 8080:8080 &

# Install dbt-trino (in project venv)
cd python && source venv/bin/activate
pip install dbt-trino

# Install dbt packages, seed, run, test
cd ../dbt
dbt deps --profiles-dir . --target local
dbt seed --profiles-dir . --target local
dbt run --profiles-dir . --target local
dbt test --profiles-dir . --target local
```

**Verify in Trino**:
```bash
# Hourly OHLC candles
kubectl exec -n data-trino deployment/trino-coordinator -- trino \
  --output-format=ALIGNED \
  --execute "SELECT candle_timestamp, currency_pair, open_price, high_price, low_price, close_price, trade_count FROM iceberg.fx_data_marts.ohlc_candles_1h ORDER BY candle_timestamp, currency_pair"

# Daily candles
kubectl exec -n data-trino deployment/trino-coordinator -- trino \
  --output-format=ALIGNED \
  --execute "SELECT * FROM iceberg.fx_data_marts.ohlc_candles_1d"

# Staging row count
kubectl exec -n data-trino deployment/trino-coordinator -- trino \
  --execute "SELECT count(*) FROM iceberg.fx_data_staging.stg_fx_ticks"
```

### Phase 6: Orchestration (TODO)

**What**: Schedule dbt runs with Dagster

**Not implemented yet**. When ready:
1. Define dbt models as Dagster assets
2. Schedule runs (1-min every minute, hourly every hour, etc.)
3. Monitor freshness and data quality

---

## Common Operations

### Makefile Commands

```bash
make help              # Show all commands
make deploy            # Deploy entire platform
make status            # Check pod status
make clean             # Delete deployments (keep cluster)
make delete-cluster    # Delete kind cluster

# Laptop-friendly helpers
make bootstrap-lakekeeper  # Bootstrap Lakekeeper (run once after deploy)
make restart-pods          # Restart all pods (useful after laptop sleep)
make connect-trino         # Connect to Trino CLI for interactive queries
make check-iceberg         # Check Iceberg tables in Lakekeeper

# Individual components
make deploy-storage
make deploy-lakekeeper
make deploy-trino
make deploy-kafka            # Deploy Kafka broker
make deploy-arroyo           # Deploy Arroyo stream processor

# Logs
make logs-lakekeeper
make logs-trino
make logs-pgbouncer
make logs-kafka              # View Kafka broker logs
make logs-arroyo-controller  # View Arroyo controller logs

# Port forwarding
make port-forward-trino      # Access Trino UI at localhost:8080
make port-forward-minio      # Access MinIO at localhost:9001
make port-forward-lakekeeper # Access Lakekeeper API at localhost:8181
make port-forward-arroyo     # Access Arroyo UI at localhost:8000
```

### Python Generator Commands

```bash
cd python

# Show configuration
python main.py info

# Generate 5 minutes of data (to Kafka + Parquet)
python main.py run --duration 300

# Run without Kafka (Parquet only)
python main.py run --no-kafka --duration 300

# Run forever (Ctrl+C to stop)
python main.py run

# Resume from checkpoint
python main.py run --resume

# Show checkpoint status
python main.py checkpoint-info
```

### dbt Commands

```bash
cd dbt

# Run all models
dbt run

# Run specific model
dbt run --select ohlc_candles_1min

# Run models with tag
dbt run --select tag:ohlc

# Full refresh (rebuild from scratch)
dbt run --full-refresh

# Test data quality
dbt test

# Generate docs
dbt docs generate && dbt docs serve
```

### Trino Queries

```bash
# Connect to Trino CLI directly in the pod
make connect-trino

# Or port-forward and use local Trino CLI
make port-forward-trino
trino --server localhost:8080 --catalog iceberg --schema fx_data
```

Example queries:

```sql
-- Show catalogs
SHOW CATALOGS;

-- Show tables
SHOW SCHEMAS IN iceberg;
SHOW TABLES FROM iceberg.fx_data;
SHOW TABLES FROM iceberg.marts;

-- Create schema (if not exists)
CREATE SCHEMA IF NOT EXISTS iceberg.fx_data;

-- Query raw ticks (after loading data)
SELECT * FROM iceberg.fx_data.raw_ticks
WHERE currency_pair = 'ECR/MRT'
  AND transaction_timestamp > current_timestamp - interval '1' hour
LIMIT 100;

-- Query 1-minute candles (after running dbt)
SELECT
  candle_timestamp,
  currency_pair,
  open_price,
  high_price,
  low_price,
  close_price,
  total_volume
FROM iceberg.marts.ohlc_candles_1min
WHERE currency_pair = 'ECR/MRT'
  AND candle_timestamp > current_timestamp - interval '1' day
ORDER BY candle_timestamp DESC;

-- Most volatile pair in last hour
SELECT
  currency_pair,
  AVG(volatility_pct) as avg_volatility
FROM iceberg.marts.ohlc_candles_1min
WHERE candle_timestamp > current_timestamp - interval '1' hour
GROUP BY currency_pair
ORDER BY avg_volatility DESC;

-- Test Iceberg time travel (query historical snapshots)
SELECT * FROM iceberg.fx_data.test_table
FOR SYSTEM_TIME AS OF TIMESTAMP '2026-03-23 00:00:00';
```

---

## Troubleshooting

### "Pods not starting"

```bash
# Check pod status
kubectl get pods --all-namespaces

# Describe failing pod
kubectl describe pod <pod-name> -n <namespace>

# Check logs
kubectl logs <pod-name> -n <namespace>

# Common fixes:
# 1. Restart pods after laptop sleep
make restart-pods

# 2. Image pull errors: Check Docker Hub rate limits
# 3. Volume mount errors: Delete and recreate cluster
# 4. Resource limits: Increase Docker memory to 8GB+
```

### "After laptop restart, pods won't start"

```bash
# Ensure Docker is running, then:
make restart-pods

# If still stuck, check specific pod:
kubectl get pods -n data-lakekeeper
kubectl logs -n data-lakekeeper <pod-name>

# Worst case: recreate deployment
make clean
make deploy
make bootstrap-lakekeeper
```

### "Lakekeeper bootstrap failed"

```bash
# Check if already bootstrapped
kubectl logs -n data-lakekeeper job/lakekeeper-bootstrap -c bootstrap

# If you see "CatalogAlreadyBootstrapped", that's OK - it's already done
# If job failed, delete and rerun:
kubectl delete job -n data-lakekeeper lakekeeper-bootstrap
make bootstrap-lakekeeper
```

### "dbt can't connect to Trino"

```bash
# Check Trino is running
kubectl get pods -n data-trino

# Test Trino directly
make connect-trino

# Port-forward for external access
make port-forward-trino

# Test connection
curl http://localhost:8080/v1/info
```

### "No fx_data schema in Iceberg"

```bash
# Create it manually with Trino
make connect-trino

# In Trino CLI:
CREATE SCHEMA IF NOT EXISTS iceberg.fx_data;
SHOW SCHEMAS IN iceberg;
```

### "No data in Iceberg tables"

You need to load data first:

1. Generate data with Python generator
2. Load Parquet files into Iceberg (manual step currently)
3. Run dbt models to create OHLC candles

```bash
# Check what tables exist
make check-iceberg
```

### "Python generator errors"

```bash
# Check Python version (need 3.11+)
python --version

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall

# Check config file
cat config/generator_config.yaml

# Run with debug logging
python main.py run --duration 60 -v
```

### "Kafka connection refused"

```bash
# Check Kafka is running
kubectl get pods -n data-kafka

# Verify port mapping
nc -zv localhost 9092

# Check Kafka logs for errors
make logs-kafka

# Verify topics exist
kubectl run kafka-topics --rm -i --restart=Never \
  --image=confluentinc/cp-kafka:7.6.0 \
  --namespace=data-kafka \
  -- kafka-topics --list --bootstrap-server kafka-broker:9092

# If topics missing, recreate them
kubectl delete job/kafka-create-topics -n data-kafka 2>/dev/null || true
kubectl apply -f manifests/jobs/kafka-create-topics.yaml
```

### "Kafka topics missing after restart"

EmptyDir volumes are ephemeral - topics are lost when pods restart. Recreate them:

```bash
kubectl delete job/kafka-create-topics -n data-kafka 2>/dev/null || true
kubectl apply -f manifests/jobs/kafka-create-topics.yaml
kubectl wait --namespace data-kafka \
  --for=condition=complete job/kafka-create-topics --timeout=120s
```

### "Out of memory errors"

```bash
# Increase Docker Desktop memory:
# Docker Desktop → Settings → Resources → Memory: 8GB

# Reduce Python generator rate:
# Edit config/generator_config.yaml:
tick_rate_per_second: 5  # Instead of 10

# Reduce dbt threads:
# Edit dbt/profiles.yml:
threads: 2  # Instead of 4
```

---

## Laptop-Friendly Design

This platform is designed to run on your laptop and survive restarts/sleep cycles.

### What Persists Across Restarts ✅

- **PostgreSQL data** - Stored in PersistentVolumeClaim
- **MinIO data (S3)** - Stored in PersistentVolumeClaim
- **Lakekeeper metadata** - Stored in PostgreSQL
- **Iceberg tables** - Stored in MinIO
- **kind cluster config** - Docker persists it

### What DOES NOT Persist (Ephemeral) ⚠️

- **Kafka topics and messages** - EmptyDir storage, lost on pod restart
- **Arroyo state** - EmptyDir storage

**After Kafka restart:** Recreate topics with `kubectl apply -f manifests/jobs/kafka-create-topics.yaml`

### What Needs Attention After Restart 🔄

- **Pods** - May need restart with `make restart-pods`
- **Port-forwards** - Need to re-run `make port-forward-*`
- **Kafka topics** - Need to recreate if Kafka pod restarted
- **One-time jobs** - Already completed, no need to rerun

### Typical Workflow

```bash
# Initial setup (once)
make deploy
make bootstrap-lakekeeper

# After laptop restart
# 1. Ensure Docker is running
# 2. Check status:
make status

# 3. If pods stuck, restart:
make restart-pods

# 4. Start working:
make connect-trino
```

### Resource Usage

- **Memory**: ~8-10GB total (including Kafka + Arroyo)
- **CPU**: Light (mostly idle, spikes during data generation)
- **Disk**: ~4GB for Docker images + data

You can safely run this alongside other work without slowing down your laptop.

---

## Learning Path

Based on your goals: **Building semantic layers with dbt**, **Understanding Apache Iceberg and Lakekeeper**, **Learning Trino**, and **Understanding data contracts**.

### Week 1: Understand Iceberg Fundamentals
1. Deploy the platform: `make deploy && make bootstrap-lakekeeper`
2. Connect to Trino: `make connect-trino`
3. Create tables with different file formats:
   ```sql
   -- Create Parquet table
   CREATE TABLE iceberg.fx_data.test_parquet (
     id INT, name VARCHAR, ts TIMESTAMP
   ) WITH (format = 'PARQUET');

   -- Create ORC table
   CREATE TABLE iceberg.fx_data.test_orc (
     id INT, name VARCHAR, ts TIMESTAMP
   ) WITH (format = 'ORC');
   ```
4. Test time travel:
   ```sql
   -- Insert data
   INSERT INTO iceberg.fx_data.test_parquet VALUES (1, 'test', CURRENT_TIMESTAMP);

   -- Query current state
   SELECT * FROM iceberg.fx_data.test_parquet;

   -- Query as of specific time
   SELECT * FROM iceberg.fx_data.test_parquet
   FOR SYSTEM_TIME AS OF TIMESTAMP '2026-03-23 00:00:00';
   ```
5. Explore table metadata:
   ```sql
   SELECT * FROM iceberg.fx_data."test_parquet$snapshots";
   SELECT * FROM iceberg.fx_data."test_parquet$files";
   ```

### Week 2-3: Build dbt Semantic Layer
1. Read `dbt/dbt_project.yml` to understand project structure
2. Study staging models: `dbt/models/staging/stg_fx_ticks.sql`
3. Study mart models: `dbt/models/marts/ohlc_candles_*.sql`
4. Key concepts to understand:
   - Incremental models with lookback windows
   - Iceberg partitioning strategies
   - OHLC calculation logic
   - Data quality tests
5. Generate sample data:
   ```bash
   cd python
   python main.py run --no-kafka --duration 300
   ```
6. Load data into Iceberg (manual step currently)
7. Run dbt models:
   ```bash
   cd dbt
   dbt run --full-refresh
   dbt test
   dbt docs generate && dbt docs serve
   ```

### Week 4: Data Contracts
1. Define schema contracts in dbt models
2. Add contract tests to ensure schema stability
3. Version your contracts (use dbt versions feature)
4. Test breaking changes:
   - Add new column (non-breaking)
   - Remove column (breaking)
   - Change data type (breaking)
5. Document contracts in dbt docs

### Week 5+: Real Pipeline
1. Run Python generator to create FX tick data
2. Load into Iceberg tables
3. Transform with dbt (incremental runs)
4. Query with Trino and analyze patterns
5. Iterate on your semantic layer design

---

## Key Technical Decisions

### Why Iceberg?
- ACID transactions on data lakes
- Time-travel (query historical snapshots)
- Schema evolution without rewrites
- Partition pruning for fast queries

### Why dbt?
- SQL-based transformations (easier than Spark)
- Incremental models (only process new data)
- Built-in testing framework
- Documentation generation

### Why Trino?
- Fast SQL queries on Iceberg
- No data movement (queries in-place)
- Supports complex analytics

### Why Lakekeeper?
- Open-source Iceberg REST catalog
- Lighter than Hive Metastore
- Easy to deploy on Kubernetes

---

## What's Next?

1. **Add Dagster**: Orchestrate dbt runs and monitor data quality
2. **Build dashboards**: Connect Superset or Grafana to Trino
3. **More Arroyo pipelines**: Real-time OHLC aggregations, anomaly detection
4. **Data contracts**: Schema enforcement between pipeline stages

---

## Resources

- [Apache Iceberg Docs](https://iceberg.apache.org/)
- [dbt Docs](https://docs.getdbt.com/)
- [Trino Docs](https://trino.io/docs/current/)
- [Lakekeeper](https://lakekeeper.io/)

---

**Questions?** Read the code, run the commands, break things, and learn! 🚀
