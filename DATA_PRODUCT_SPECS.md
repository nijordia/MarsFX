# Data Product Specifications

This document defines the data products in the MarsFX platform. Each product has an associated contract (in `contracts/`) and operational runbooks.

---

## Data Product 1: FX Ticks (Raw)

### Ownership & Purpose

**Owner**: data-engineering
**Purpose**: Provide real-time FX tick data for downstream aggregation and analysis
**Consumers**: Analytics team (OHLC aggregations), BI dashboards, data scientists
**Business Driver**: Need accurate, low-latency market data to power trading decisions

### Schema & Constraints

See `contracts/marsfx-raw-ticks.yaml` for the complete schema.

**Key Constraints**:
- `tick_id`: Unique identifier (UUID), must be unique
- `currency_pair`: One of [ECR/MRT, ECR/LCR, ECR/AMC, MRT/LCR, MRT/AMC, LCR/AMC]
- Prices (`bid_price`, `ask_price`, `trade_price`, `mid_price`): Positive, decimal(18,8)
- `transaction_timestamp`: ISO 8601 timestamp, microsecond precision

### Quality SLAs

| SLA | Target | Rationale |
|-----|--------|-----------|
| **Freshness** | Max 15 minutes | Analytical queries (OHLC) don't need sub-minute latency; 15min allows for batch processing |
| **Completeness** | 99.5% | Some tick loss acceptable (e.g., network hiccups); patterns still visible |
| **Availability** | 95% | Dev environment; not production SLA |
| **Latency (end-to-end)** | Kafka → Iceberg in < 60 seconds | Real-time feel for users; allows for Arroyo processing |

### Validation Strategy

**At Ingestion (Kafka)**:
- Future: Schema Registry validates message format before entry
- Current: Python Pydantic validation (client-side)
- Rejects: Malformed JSON, wrong field types, invalid enum values

**Daily (dbt)**:
- Run `dbt test` on incremental data (last 24 hours)
- Check: not-null, accepted-values, uniqueness, price constraints
- Fail if: Any test fails → alert on-call

**Weekly (Audit)**:
- Manual query for anomalies (e.g., 10x volume spike, price gaps)
- Investigate outliers; document findings

### Operational Procedures

**Freshness SLA Breached**:
1. Check Arroyo controller logs: `make logs-arroyo-controller`
2. Check pipeline status in Arroyo UI
3. If stuck: restart pipeline or investigate Kafka backlog
4. If Kafka topic empty: check Python generator status

**Data Quality Test Failure**:
1. Review dbt test output in logs
2. Query raw data to identify bad records
3. Determine root cause: Python generator bug? Kafka corruption? Arroyo casting?
4. Fix at source; backfill if needed

**Data Recovery**:
- Iceberg supports time-travel: query previous snapshots
- Rollback: manual, not automated
- Process: TBD (not yet implemented)

### Evolution & Versioning

**Schema Changes**:
- Adding optional fields: backward compatible, no action needed
- Adding required fields: breaking change, must notify consumers
- Removing fields: breaking change, must notify consumers
- Changing types: breaking change

**Contract Versioning**:
- Currently: v1.0.0
- Breaking changes: bump major version (v2.0.0)
- Minor improvements: bump minor version (v1.1.0)
- Notification: TBD (who gets notified of contract changes?)

---

## Data Product 2: OHLC Candles (Aggregated)

### Ownership & Purpose

**Owner**: data-engineering
**Purpose**: Provide aggregated OHLC (Open-High-Low-Close) price candles at multiple granularities
**Consumers**: BI dashboards, analysts, trading algorithms
**Business Driver**: Need time-series data for technical analysis and backtesting

### Schema & Constraints

See `contracts/marsfx-ohlc-candles.yaml` for the complete schema (4 models: 1min, 5min, 1h, 1d).

**Key Constraints**:
- Uniqueness: (currency_pair, candle_timestamp) must be unique per granularity
- OHLC validity: `low_price <= open_price, close_price <= high_price`
- Prices: All positive, decimal(18,8)
- Timestamps: ISO 8601, microsecond precision

### Quality SLAs

| SLA | Target | Rationale |
|-----|--------|-----------|
| **Freshness** | 1min candles: 10min; 5min: 30min; 1h: 2h; 1d: 25h | Each granularity has proportional SLA based on typical query patterns |
| **Completeness** | 99.0% | Some gaps acceptable (e.g., during backfills); trends still visible |
| **Availability** | 95% | Dev environment |
| **Latency (end-to-end)** | Raw tick → 1min candle in < 5 minutes | Users need recent data for analysis |

### Validation Strategy

**At Creation (dbt)**:
- Run tests on all 4 models after dbt transformation
- Check: not-null, OHLC validity, uniqueness, volume > 0
- Fail if: Any test fails → block deployment

**Incremental (dbt)**:
- Only validate new/updated candles (last N hours per granularity)
- Don't re-scan entire 1d table every run

**Manual (Ad-hoc)**:
- Spot checks: compare candles to raw ticks (e.g., open_price == first tick price)
- Audit: check for gaps in time series (missing hours/days)

### Operational Procedures

**Freshness SLA Breached**:
1. Check dbt run logs: `dbt run --select ohlc_candles_1min`
2. If dbt failed: review error, rerun
3. If dbt succeeded but data old: check Arroyo freshness (raw ticks might be stale)
4. If both fresh but Trino query slow: investigate Trino query performance

**Data Quality Test Failure**:
1. Review dbt test failure details
2. Identify which candles failed (which timestamp/currency_pair)
3. Rerun dbt with `--full-refresh` if needed (or targeted rerun)
4. Verify fix; document root cause

**Data Recovery**:
- Iceberg time-travel: query previous snapshot
- Rollback: manual via dbt full-refresh (expensive)
- Process: TBD

### Evolution & Versioning

**Schema Changes**:
- Adding derived columns (e.g., new `volatility_pct`): non-breaking
- Changing OHLC calculation logic: breaking (consumers' analysis changes)
- Removing granularity (e.g., drop 5min candles): breaking

**Contract Versioning**:
- Currently: v1.0.0
- Any calculation change: bump major version (v2.0.0)

---

## Gaps & Future Work

### Phase 2 (Data Quality & Observability)

*Mindset: Design for scale — assume millions of incoming data points. Never scan full tables; only validate incremental data.*

- [ ] **Incremental Validation**: dbt tests only on last N hours of data, not full tables
  - Raw ticks: test last 24 hours (last 1440 minutes of ticks)
  - 1min candles: test last 2 hours of candles
  - Prevent expensive full-table scans that don't scale

- [ ] **Monitoring Queries**: Scheduled SQL checks for SLA compliance
  - Freshness: `MAX(event_time) - NOW() < threshold?`
  - Completeness: `COUNT(*) in last hour > expected_min_rows?`
  - Availability: `dbt test results passed in last run?`

- [ ] **Alert Conditions Matrix**: Formalize when runbooks activate
  - E.g., "Freshness breached when event_time > 15min old for 2 consecutive checks"
  - E.g., "Completeness warning when row_count < 99.5% of expected"

- [ ] **Contract Testing**: Only validate at merge time (CI/CD) and after major transformations, not continuously
  - `make contract-lint`: on every commit
  - `make contract-test-trino`: after dbt runs in CI/CD

- [ ] **Consumer Registry**: Document who depends on each data product
  - Enables notification strategy for breaking changes
  - Tracks downstream impact of schema changes

### Phase 3 (Orchestration & Multi-Domain Mesh)

*Mindset: Reproducible, scheduled, observable pipelines. No manual steps.*

- [ ] **Dagster Orchestrator**: Schedule the full pipeline as a DAG
  - Job: `generate_ticks` → `arroyo_stream` → `dbt_run` → `monitoring_checks` → `alert_if_needed`
  - Scheduled every 5 minutes (or continuous based on Kafka lag)
  - Built-in retry, alerting, run history
  - Replaces manual `make deploy-arroyo` and `dbt run` commands

- [ ] **Second Data Product**: Add "Economic Events" (e.g., interest rate changes, GDP releases)
  - Practice multi-domain contract scenarios
  - Different freshness SLAs (daily, not minute-level)
  - Different consumers (policy team vs analytics)

- [ ] **Contract Versioning in CI/CD**: Detect breaking changes before merge
  - Tool: `datacontract breaking` command
  - Block PRs that introduce incompatible schema changes
  - Enforce notification of affected consumers

- [ ] **Data Catalog**: Centralized registry of all data products
  - What products exist? Who owns them? What are the SLAs?
  - Where are they stored (Kafka topic, Iceberg table, Trino view)?
  - Who consumes them? (links to downstream systems)
  - Tool options: Apache Atlas, Collibra, or custom dbt docs

- [ ] **Incremental dbt Materializations**: Only touch changed partitions
  - Raw ticks: append-only (no updates)
  - OHLC candles: incremental by `candle_timestamp` partition
  - Avoid recomputing historical candles for every run

---

## Questions for Feedback

As you review this spec, consider:

1. **Are the SLAs realistic?** Would you adjust freshness targets?
2. **Are the validation strategies practical?** What's missing?
3. **Are the runbooks clear?** Could someone follow them without calling you?
4. **Are the schema constraints complete?** Any missing constraints?
5. **Is the versioning strategy sound?** How would you notify consumers of breaking changes?

These answers will shape Phase 2 implementation.