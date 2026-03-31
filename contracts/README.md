# Data Contracts

This directory contains the data contract specifications for the MarsFX platform, defined using the [Open Data Contract Standard (ODCS v3)](https://datacontract-specification.com/).

## Learning Roadmap

This project is structured as a learning journey toward building a production-grade data mesh. Each phase builds toward operating at scale — *never assuming we can load entire tables or run tests on full datasets*.

- **Phase 1 (Done)**: Understand individual services and build end-to-end pipeline
  - Single data product (FX Ticks), manual orchestration, batch validation

- **Phase 2 (In Progress)**: Data quality, observability, and operational readiness
  - Incremental dbt validation (last N hours only, not full tables)
  - Monitoring queries for SLA freshness/completeness checks
  - Contract validation at specific points in the pipeline (not full-table scans)
  - Documented operational procedures with alert thresholds
  - See [DATA_PRODUCT_SPECS.md](../DATA_PRODUCT_SPECS.md) for detailed specifications

- **Phase 3 (Next)**: Orchestration and multi-domain mesh
  - Dagster orchestrator: schedules Python → Kafka → Arroyo → dbt → monitoring in a reproducible DAG
  - Second data product (Economic Events or similar) to practice multi-domain contracts
  - Contract versioning in CI/CD: detect breaking changes before merge
  - Data catalog: centralized registry of all products, owners, SLAs
  - Incremental dbt materializations: only touch new data partitions

See [DATA_PRODUCT_SPECS.md](../DATA_PRODUCT_SPECS.md) for the data product specifications that drive the contracts.

## What Are Data Contracts?

A data contract is an **agreement** between a data producer and its consumers about the shape, quality, and availability of data. It is not a single enforcement mechanism — it is implemented across multiple points in the pipeline:

| Enforcement Point | What It Checks | Tool |
|---|---|---|
| **Kafka** (ingestion) | Message schema validity | Future: Schema Registry |
| **Iceberg** (storage) | Column types at write time | Lakekeeper catalog |
| **dbt** (transformation) | Data quality, constraints, freshness | dbt tests (schema.yml) |
| **datacontract CLI** (audit) | Contract compliance against live data | `datacontract test` |

The YAML files in this directory are the **canonical specification** — the single source of truth for what each data product guarantees. The dbt schema tests, Pydantic models, and Arroyo SQL are the enforcement implementations at their respective layers.

## Contracts

| Contract | File | Data Product | Servers |
|---|---|---|---|
| Raw FX Ticks | `marsfx-raw-ticks.yaml` | Tick data from Kafka to Iceberg | Kafka + Trino |
| OHLC Candles | `marsfx-ohlc-candles.yaml` | Aggregated candles (1min, 5min, 1h, 1d) | Trino |

## Usage

### Prerequisites

Install the datacontract CLI (included in project requirements):

```bash
cd python && source venv/bin/activate
pip install "datacontract-cli[all]"
```

Or use the Makefile target:

```bash
make contract-setup
```

### Commands

```bash
# Validate contract YAML syntax
make contract-lint

# Test contracts against live Kafka topic
make contract-test-kafka

# Test contracts against Trino/Iceberg tables
make contract-test-trino

# Test all contracts against all servers
make contract-test

# Export contracts to dbt schema format (for drift comparison)
make contract-export-dbt
```

### Full Validation Workflow

```bash
# 1. Lint the contracts
make contract-lint

# 2. Generate some data
cd python && source venv/bin/activate
python main.py run --duration 60

# 3. Test raw ticks against Kafka
make contract-test-kafka

# 4. Run dbt to create OHLC candles
cd dbt && dbt run --profiles-dir . --target local

# 5. Test all contracts against Trino
make contract-test-trino
```

## Relationship to dbt Schema Tests

The contracts and dbt schema tests are **complementary, not redundant**:

- **Contracts** define the external interface — what consumers can rely on
- **dbt tests** enforce internal transformation correctness — what the pipeline guarantees at build time

The dbt schemas use `dbt_expectations` and `dbt_utils` expression tests (e.g., `ask_price >= bid_price`, OHLC validity rules) that go beyond what the contract spec covers. These remain in the dbt layer.

Some overlap exists (field names, enum values, not-null constraints). This is intentional — if the dbt schema drifts from the contract, `make contract-test-trino` will catch it.

## Future Enhancements

- **Schema Registry**: Export the raw ticks contract to Avro via `datacontract export --format avro` and register it in Confluent Schema Registry for real-time ingestion validation
- **CI/CD**: Add `make contract-lint` and `make contract-test` to a CI pipeline to block merges on contract violations
- **Breaking change detection**: Use `datacontract breaking` to detect backward-incompatible changes before deployment
- **Contract-driven dbt generation**: Use `datacontract export --format dbt` as the baseline for dbt schema files
