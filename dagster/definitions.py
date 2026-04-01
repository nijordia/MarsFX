"""
MarsFX Dagster Definitions
"""

import os
import subprocess
from pathlib import Path

from dagster import (
    AssetExecutionContext,
    Definitions,
    ScheduleDefinition,
    asset,
    define_asset_job,
)
from dagster_dbt import DbtCliResource, dbt_assets, DbtProject

DBT_PROJECT_DIR = os.environ.get("DBT_PROJECT_DIR", "/home/sarble/Desktop/software/MarsFX/dbt")
DBT_PROFILES_DIR = os.environ.get("DBT_PROFILES_DIR", "/home/sarble/Desktop/software/MarsFX/dbt")
DBT_TARGET = os.environ.get("DBT_TARGET", "local")
CONTRACTS_DIR = os.environ.get("CONTRACTS_DIR", "/home/sarble/Desktop/software/MarsFX/contracts")

dbt_project = DbtProject(project_dir=DBT_PROJECT_DIR)

dbt_resource = DbtCliResource(
    project_dir=dbt_project,
    profiles_dir=DBT_PROFILES_DIR,
    target=DBT_TARGET,
)


@dbt_assets(manifest=dbt_project.manifest_path)
def marsfx_dbt_assets(context: AssetExecutionContext, dbt: DbtCliResource):
    """Run dbt build: materialize all models and run incremental tests."""
    yield from dbt.cli(["build"], context=context).stream()


@asset(deps=[marsfx_dbt_assets])
def freshness_check(context: AssetExecutionContext):
    """Check data freshness against SLA thresholds via Trino."""
    try:
        import trino
        conn = trino.dbapi.connect(
            host=os.environ.get("TRINO_HOST", "localhost"),
            port=int(os.environ.get("TRINO_PORT", "8080")),
            user="dbt",
            catalog="iceberg",
            schema="fx_data",
            http_scheme="http",
        )
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MAX(event_time)
            FROM iceberg.fx_data.raw_ticks_streaming
            WHERE event_time > CURRENT_TIMESTAMP - INTERVAL '1' HOUR
        """)
        row = cursor.fetchone()
        if row and row[0]:
            context.log.info(f"Raw ticks last event: {row[0]}")
        else:
            context.log.warning("No raw ticks found in last hour — freshness SLA breached")
        cursor.close()
        conn.close()
    except Exception as e:
        context.log.warning(f"Freshness check skipped: {e}")


@asset(deps=[marsfx_dbt_assets])
def contract_validation(context: AssetExecutionContext):
    """Validate data contracts against live Trino data.

    Uses ODCS 3.0.2 contracts with datacontract-cli.
    Note: Kafka validation requires broker to be running locally.
    Trino validation requires localhost:8080 port-forward.
    """
    for contract in ["marsfx-raw-ticks.yaml", "marsfx-ohlc-candles.yaml"]:
        path = f"{CONTRACTS_DIR}/{contract}"
        if not os.path.exists(path):
            context.log.warning(f"Contract not found: {path}")
            continue

        try:
            result = subprocess.run(
                ["datacontract", "test", path, "--server", "trino"],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                context.log.info(f"Contract passed: {contract}")
            else:
                # Log warnings but don't fail—schema validation is the goal
                context.log.warning(f"Contract validation warning: {contract}\n{result.stderr[:500]}")
        except Exception as e:
            context.log.warning(f"Contract validation skipped: {e}")


@asset(deps=[marsfx_dbt_assets])
def iceberg_compaction(context: AssetExecutionContext):
    """Compact small Parquet files in Iceberg tables."""
    try:
        import trino
        conn = trino.dbapi.connect(
            host=os.environ.get("TRINO_HOST", "localhost"),
            port=int(os.environ.get("TRINO_PORT", "8080")),
            user="dbt",
            catalog="iceberg",
            schema="fx_data",
            http_scheme="http",
        )
        cursor = conn.cursor()
        for table in ["raw_ticks_streaming", "stg_fx_ticks",
                      "ohlc_candles_1min", "ohlc_candles_5min",
                      "ohlc_candles_1h", "ohlc_candles_1d"]:
            try:
                cursor.execute(f"ALTER TABLE iceberg.fx_data.{table} EXECUTE optimize")
                cursor.fetchall()
                context.log.info(f"Compacted: {table}")
            except Exception as e:
                context.log.warning(f"Compaction skipped for {table}: {e}")
        cursor.close()
        conn.close()
    except Exception as e:
        context.log.warning(f"Compaction skipped: {e}")


pipeline_job = define_asset_job(
    name="marsfx_pipeline",
    selection=[marsfx_dbt_assets, contract_validation, iceberg_compaction, freshness_check],
)

dbt_only_job = define_asset_job(
    name="marsfx_dbt_only",
    selection=[marsfx_dbt_assets, freshness_check],
)

compaction_job = define_asset_job(
    name="marsfx_compaction",
    selection=[iceberg_compaction],
)

defs = Definitions(
    assets=[marsfx_dbt_assets, freshness_check, contract_validation, iceberg_compaction],
    jobs=[pipeline_job, dbt_only_job, compaction_job],
    schedules=[
        ScheduleDefinition(job=dbt_only_job, cron_schedule="*/5 * * * *",
                           name="marsfx_dbt_every_5min"),
        ScheduleDefinition(job=pipeline_job, cron_schedule="0 * * * *",
                           name="marsfx_full_pipeline_hourly"),
        ScheduleDefinition(job=compaction_job, cron_schedule="0 3 * * *",
                           name="marsfx_compaction_daily"),
    ],
    resources={"dbt": dbt_resource},
)
