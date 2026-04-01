# Phase 2: Data Quality & Observability Implementation

## Objective
Design for scale — never scan full tables. Implement incremental validation, monitoring queries, and formalized operational procedures.

---

## ✅ Completed

### 1. Incremental Validation (dbt Tests)
- **Macro**: `dbt/macros/get_incremental_test_bounds.sql`
  - Returns WHERE clause fragments based on model name and test window
  - 1min: last 2 hours | 5min: last 1 hour | 1h: last 3 hours | 1d: last 2 days

- **Custom Generic Tests**: Created new test macros to support incremental bounds
  - `dbt/macros/test_incremental_expression_is_true.sql`: Validates boolean expressions on recent data only
  - `dbt/macros/test_incremental_unique_combination.sql`: Validates uniqueness constraints on recent data only

- **Schema Updates**: `dbt/models/marts/schema.yml`
  - Replaced `dbt_utils.unique_combination_of_columns` with `incremental_unique_combination_of_columns`
  - Replaced `dbt_utils.expression_is_true` with `incremental_expression_is_true`
  - All OHLC validity tests now use incremental macros

- **Why This Works**:
  - Queries only recent data, never scans full tables
  - Maintains data quality checks while avoiding expensive full-table scans
  - Scales to millions of rows without performance degradation

- **How to Run**:
  ```bash
  cd dbt
  source ../python/venv/bin/activate
  dbt test --select ohlc_candles_1min
  dbt test --select tag:ohlc  # Test all OHLC models
  ```

---

## 🚧 In Progress

### 2. Monitoring Queries for SLA Compliance
Query templates for scheduled validation of freshness, completeness, availability.

**Freshness Check** (detect stale data):
```sql
-- Check if raw ticks data is fresh (< 15 min old)
SELECT
  MAX(event_time) as max_event_time,
  CURRENT_TIMESTAMP as now,
  (CURRENT_TIMESTAMP - MAX(event_time)) as age,
  CASE
    WHEN (CURRENT_TIMESTAMP - MAX(event_time)) > INTERVAL '15' MINUTE THEN 'BREACH'
    ELSE 'OK'
  END as freshness_status
FROM iceberg.fx_data.raw_fx_ticks
WHERE event_time > CURRENT_TIMESTAMP - INTERVAL '1' HOUR;
```

**Completeness Check** (detect missing data):
```sql
-- Check if 1min candles row count meets threshold (last hour)
SELECT
  COUNT(*) as row_count,
  COUNT(DISTINCT currency_pair) as distinct_pairs,
  CASE
    WHEN COUNT(*) >= 55 THEN 'OK'  -- ~55 candles per pair per hour
    ELSE 'BREACH'
  END as completeness_status
FROM iceberg.fx_data.ohlc_candles_1min
WHERE candle_timestamp > CURRENT_TIMESTAMP - INTERVAL '1' HOUR;
```

**Test Results Check** (track validation health):
```sql
-- Check if dbt tests passed in last run
SELECT
  'ohlc_candles_1min' as model,
  COUNT(CASE WHEN status = 'pass' THEN 1 END) as passed,
  COUNT(CASE WHEN status = 'fail' THEN 1 END) as failed
FROM iceberg.fx_data.dbt_test_results
WHERE test_timestamp > CURRENT_TIMESTAMP - INTERVAL '1' HOUR
GROUP BY model;
```

**TODO**: Implement these as scheduled dbt tests or monitoring scripts (Phase 2.1)

---

## 📋 Next Steps

### Phase 2.1: Alert Thresholds & Operational Runbooks
- [ ] Formalize alert conditions matrix (when do SLA checks trigger runbooks?)
- [ ] Document on-call response procedures for each breach type
- [ ] Create runbook automation (scripts to auto-investigate/retry)

### Phase 2.2: Consumer Registry
- [ ] Create `CONSUMERS.md`: document downstream dependencies
- [ ] Track which teams use which data products
- [ ] Enable notification strategy for breaking changes

### Phase 2.3: Monitoring Dashboard
- [ ] Trino/Grafana dashboard showing:
  - Data freshness trends
  - Row count by model
  - Test pass/fail rates
  - SLA compliance status

### Phase 2.4: Schema Registry (Optional, High Value)
- [ ] Kafka Schema Registry: reject bad messages at ingestion
- [ ] Enforces contract at Kafka producer level (not just downstream)
- [ ] Prevents bad data from ever entering the system

---

## Design Rationale

### Why Incremental Tests?
- **Scalability**: Millions of rows → scan only last 2 hours, not entire history
- **Cost**: Reduce query volume against Iceberg/Trino
- **Speed**: Tests complete in seconds, not minutes
- **Focus**: Only validate new data; historical data is immutable in Iceberg

### Why Custom Macros?
- dbt's generic test parser doesn't support macro calls in `where` arguments
- Custom macros give us full control over WHERE clause generation
- Easy to test and version control

### Why This Order?
1. **Incremental tests first** (foundational): Quality checks must not be expensive
2. **Monitoring queries next** (operational): Once tests are cheap, automated monitoring is straightforward
3. **Alerting/runbooks** (procedural): Formal response procedures
4. **Consumer registry** (governance): Track dependencies before multi-domain phase
5. **Schema Registry** (optional enhancement): Kafka-level validation

---

## Testing & Validation

**Status**: Macro compilation verified ✅
- dbt successfully parses custom incremental test macros
- Schema.yml changes apply without errors
- Ready to run tests once Trino is reachable (local K8s cluster)

**To Validate Locally**:
1. Ensure cluster is running: `kind get clusters`
2. Port-forward Trino: `kubectl port-forward -n data-trino svc/trino 8080:8080`
3. Run tests: `cd dbt && dbt test --select ohlc_candles_1min`

---

## Files Changed

- `dbt/macros/ohlc_helpers.sql`: Added `get_incremental_test_bounds(model_name)` macro
- `dbt/macros/test_incremental_expression_is_true.sql`: New custom test for boolean expressions
- `dbt/macros/test_incremental_unique_combination.sql`: New custom test for uniqueness
- `dbt/models/marts/schema.yml`: Replaced dbt_utils tests with incremental versions
- `dbt/profiles.yml`: Added missing `user` field to dev/prod targets

---

## Questions for Future Work

1. **Late-Arriving Ticks**: How should candles handle ticks that arrive out-of-order?
   - Current: 5min lookback on 1min models handles most cases
   - Future: Formalize "late tick cutoff" policy (e.g., ticks >1 hour late are rejected)

2. **Monitoring Frequency**: How often should monitoring queries run?
   - Proposal: Every 5 minutes for freshness, hourly for completeness

3. **Consumer Notification**: How to notify downstream teams of breaking changes?
   - Options: Slack channel, Email, Jira ticket, Data catalog UI
