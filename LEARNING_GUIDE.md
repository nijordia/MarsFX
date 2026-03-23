# Learning Guide: How to Understand MarsFX

This repository was built by Claude in a few minutes, but it represents weeks of manual work. Here's how to digest it systematically.

---

## Start Here: The Learning Path

### Day 1-2: High-Level Understanding (2 hours)

**Goal**: Understand what the system does, not how

1. **Read the main README** (30 min)
   - Focus on "Understanding the System" section
   - Look at the data flow diagram
   - Don't worry about technical details yet

2. **Run the Quick Start** (30 min)
   ```bash
   make deploy
   make status
   ```
   - Watch the pods start
   - Access Trino UI at localhost:8080
   - Just look around, don't try to understand everything

3. **Generate some data** (30 min)
   ```bash
   cd python
   python3 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   python main.py info  # See config
   python main.py run --no-kafka --duration 300  # Generate 5 min
   ls -lh data/ticks/*/  # See output files
   ```

4. **Look at the output** (30 min)
   ```bash
   # Install pandas if needed
   pip install pandas pyarrow

   # View the data
   python -c "
   import pandas as pd
   df = pd.read_parquet('data/ticks/')
   print(df.head())
   print(df.info())
   print(df.currency_pair.value_counts())
   "
   ```

**What you should understand now**:
- MarsFX generates fake FX trading data
- Data is organized by date and hour
- 6 currency pairs trade at 10 ticks/sec each
- Output is Parquet files (columnar format)

---

### Day 3-5: The Infrastructure Layer (4 hours)

**Goal**: Understand Kubernetes components

1. **Study the Makefile** (1 hour)
   - File: `Makefile`
   - Look at each target (deploy, clean, status, logs)
   - Run some commands:
     ```bash
     make help
     make status
     make logs-trino
     ```

2. **Understand the cluster** (1 hour)
   - File: `manifests/cluster/config.yaml`
   - This defines a 3-node Kubernetes cluster
   - Port mappings: 8080 (Trino), 9001 (MinIO), 8181 (Lakekeeper)
   - Run: `kubectl get nodes` to see the nodes

3. **Understand the storage layer** (1 hour)
   - Files:
     - `manifests/storage/postgres.yaml` - Database for metadata
     - `manifests/storage/minio.yaml` - Object storage for data files
   - These store the actual data and metadata
   - Access MinIO console: http://localhost:9001 (admin/minioadmin)

4. **Understand Lakekeeper** (1 hour)
   - File: `manifests/lakekeeper/chart/values.yaml`
   - This is the "catalog" - it tracks which tables exist and their schemas
   - Like a librarian for your data lake
   - Check API: `curl http://localhost:8181/management/v1/health`

**What you should understand now**:
- Kubernetes orchestrates containers
- PostgreSQL stores metadata (schema, table definitions)
- MinIO stores actual data (Parquet files)
- Lakekeeper manages the Iceberg catalog

---

### Day 6-8: The Data Generator (4 hours)

**Goal**: Understand how fake data is created

1. **Study the config** (30 min)
   - File: `python/config/generator_config.yaml`
   - Find these settings:
     - `tick_rate_per_second: 10`
     - `time_acceleration_factor: 60`
     - `currency_pairs:` (list of 6)
   - Try changing tick_rate to 5, run generator, see difference

2. **Understand the data model** (1 hour)
   - File: `python/fx_generator/models.py`
   - Study `FXTick` class:
     ```python
     class FXTick(BaseModel):
         tick_id: UUID
         transaction_timestamp: datetime
         currency_pair: str
         bid_price: Decimal
         ask_price: Decimal
         ...
     ```
   - These are the fields in each tick

3. **Understand price simulation** (1.5 hours)
   - File: `python/fx_generator/price_simulator.py`
   - Don't worry about the math (Geometric Brownian Motion)
   - Understand:
     - Prices start at a base (e.g., 1.5 for ECR/MRT)
     - They drift up/down randomly
     - Volatility makes them jump more or less
     - Correlation makes pairs move together

4. **Understand the main loop** (1 hour)
   - File: `python/fx_generator/tick_generator.py`
   - Find the `generate_batch()` method
   - It does this every second:
     1. Increment simulation time
     2. Generate N ticks per pair
     3. Write to Parquet buffer
     4. Save checkpoint
   - That's it!

**What you should understand now**:
- Generator creates realistic-looking prices using math
- Output is FXTick objects → Parquet files
- Checkpointing lets you resume if interrupted
- Config file controls everything

---

### Day 9-12: The Transformation Layer (dbt) (6 hours)

**Goal**: Understand how ticks become candles

1. **dbt basics** (1 hour)
   - Read dbt docs: https://docs.getdbt.com/docs/introduction
   - Understand: models = SQL files that create tables/views
   - File: `dbt/dbt_project.yml` - Main config

2. **Understand the source** (30 min)
   - File: `dbt/models/sources.yaml`
   - This tells dbt where raw data is: `iceberg.fx_data.raw_ticks`
   - It's just a pointer

3. **Understand staging** (1 hour)
   - File: `dbt/models/staging/stg_fx_ticks.sql`
   - Read the SQL - it's just cleaning:
     - Cast columns to proper types
     - Filter out bad data (negative prices)
     - Extract base/quote currency
   - This creates a view (temporary, not stored)

4. **Understand OHLC candles** (2 hours)
   - File: `dbt/models/marts/ohlc_candles_1min.sql`
   - Read slowly, section by section:
     ```sql
     -- Get source ticks
     with source_ticks as (...)

     -- Number them (first/last in each minute)
     ticks_with_order as (...)

     -- Calculate OHLC
     candles as (
         min(trade_price) as low_price,
         max(trade_price) as high_price,
         ...
     )
     ```
   - **Open** = first tick in period
   - **High** = highest tick in period
   - **Low** = lowest tick in period
   - **Close** = last tick in period

5. **Understand incremental strategy** (1.5 hours)
   - Look at this section in the OHLC model:
     ```sql
     {% if is_incremental() %}
         where date_trunc('minute', transaction_timestamp) >= (
             select max(candle_timestamp) - interval '5' minute from {{ this }}
         )
     {% endif %}
     ```
   - This means: "Only process last 5 minutes of data"
   - Why? Late-arriving ticks need to update existing candles
   - This is the "lookback window"

6. **Run dbt and see results** (30 min)
   ```bash
   cd dbt
   dbt run --select ohlc_candles_1min
   # Watch it create the table

   # Query it
   make port-forward-trino
   # Open Trino UI, run:
   # SELECT * FROM iceberg.marts.ohlc_candles_1min LIMIT 10
   ```

**What you should understand now**:
- dbt transforms data with SQL
- Staging cleans, marts aggregate
- OHLC = Open/High/Low/Close prices per time period
- Incremental models only process new data for efficiency

---

### Day 13-15: The Query Layer (Trino + Iceberg) (3 hours)

**Goal**: Understand how to query the data

1. **Trino basics** (1 hour)
   - Read Trino docs: https://trino.io/docs/current/
   - It's a distributed SQL engine
   - Queries Iceberg tables without moving data

2. **Iceberg basics** (1 hour)
   - Read Iceberg docs: https://iceberg.apache.org/
   - It's a table format that adds features to Parquet:
     - ACID transactions
     - Time-travel
     - Schema evolution
     - Partitioning

3. **Write some queries** (1 hour)
   ```bash
   make port-forward-trino
   # Open http://localhost:8080
   ```

   Try these queries:
   ```sql
   -- Show all tables
   SHOW TABLES FROM iceberg.marts;

   -- See recent candles
   SELECT * FROM iceberg.marts.ohlc_candles_1min
   ORDER BY candle_timestamp DESC
   LIMIT 20;

   -- Most volatile pair today
   SELECT
     currency_pair,
     AVG(volatility_pct) as avg_volatility
   FROM iceberg.marts.ohlc_candles_1min
   WHERE DATE(candle_timestamp) = CURRENT_DATE
   GROUP BY 1
   ORDER BY 2 DESC;

   -- Trading volume by hour
   SELECT
     DATE_TRUNC('hour', candle_timestamp) as hour,
     SUM(total_volume) as hourly_volume
   FROM iceberg.marts.ohlc_candles_1min
   GROUP BY 1
   ORDER BY 1;
   ```

**What you should understand now**:
- Trino = SQL engine for big data
- Iceberg = smart table format
- You can query billions of rows efficiently
- Partitioning makes queries fast (only reads relevant files)

---

## By Topic: How Components Relate

### Data Flow (Follow a Single Tick)

1. **Python generates a tick**
   - File: `fx_generator/tick_generator.py`
   - Creates FXTick object with price, timestamp, volume

2. **Tick is written to Parquet**
   - File: `fx_generator/tick_generator.py` → `_flush_parquet_buffer()`
   - Saved to `data/ticks/2026-03-22/14.parquet`

3. **Parquet is loaded to Iceberg** (manual step for now)
   - Run Trino query:
     ```sql
     CREATE TABLE iceberg.fx_data.raw_ticks AS
     SELECT * FROM read_parquet('data/ticks/**/*.parquet');
     ```

4. **dbt transforms tick to candle**
   - File: `dbt/models/marts/ohlc_candles_1min.sql`
   - Groups ticks by minute
   - Calculates open/high/low/close

5. **Trino queries candle**
   - User runs: `SELECT * FROM iceberg.marts.ohlc_candles_1min`
   - Trino reads from MinIO
   - Returns results

---

## Files Ranked by Importance

### Must Understand (Start Here)
1. `README.md` - Overview
2. `Makefile` - All commands
3. `python/config/generator_config.yaml` - Data generator settings
4. `dbt/models/marts/ohlc_candles_1min.sql` - How candles are made

### Should Understand (Next)
5. `python/fx_generator/models.py` - Data structures
6. `python/fx_generator/tick_generator.py` - Generation logic
7. `dbt/dbt_project.yml` - dbt configuration
8. `dbt/models/staging/stg_fx_ticks.sql` - Data cleaning

### Nice to Understand (Later)
9. `manifests/trino/values.yaml` - Trino config
10. `manifests/lakekeeper/chart/values.yaml` - Lakekeeper config
11. `python/fx_generator/price_simulator.py` - Price math (complex)
12. `dbt/macros/ohlc_helpers.sql` - Reusable functions

### Can Ignore (For Now)
- Kubernetes YAML files (manifests/*) - Infrastructure boilerplate
- Test files (python/tests/*, dbt/tests/*) - Validation logic
- Secrets (manifests/secrets/*) - Just credentials

---

## Common Questions

### "What's the difference between MinIO and PostgreSQL?"
- **PostgreSQL**: Stores metadata (table schemas, partition info)
- **MinIO**: Stores actual data (Parquet files)
- Think: PostgreSQL = index card catalog, MinIO = book shelves

### "What's the difference between Lakekeeper and Trino?"
- **Lakekeeper**: Manages catalog (which tables exist, their schemas)
- **Trino**: Queries the data (executes SQL)
- Think: Lakekeeper = librarian, Trino = researcher

### "Why Iceberg instead of just Parquet?"
- Parquet = file format (just stores data)
- Iceberg = table format (adds features on top of Parquet):
  - ACID transactions (no partial writes)
  - Time-travel (query historical versions)
  - Schema evolution (add columns without rewriting files)
  - Hidden partitioning (automatic based on queries)

### "What's a 'candle' in OHLC?"
- Visualization of price movement over time
- Example: 1-minute candle for ECR/MRT:
  - Open: 1.5000 (first trade at 10:00:00)
  - High: 1.5050 (highest trade at 10:00:45)
  - Low: 1.4950 (lowest trade at 10:00:15)
  - Close: 1.5020 (last trade at 10:00:59)
- Used in trading charts (candlestick charts)

### "What's time acceleration?"
- Config: `time_acceleration_factor: 60`
- Real-time: Generator runs for 1 minute
- Simulated time: Data spans 60 minutes
- Why? Generate months of data in hours

---

## Summary: The Minimum You Need to Know

**What MarsFX does**:
- Generates fake FX trading data (ticks)
- Stores it in a data lake (Iceberg)
- Transforms it into summaries (OHLC candles)
- Lets you query it (Trino SQL)

**3 main components**:
1. **Python generator** (`python/`) - Creates data
2. **dbt** (`dbt/`) - Transforms data
3. **Infrastructure** (`manifests/`) - Runs everything on Kubernetes

**To use it**:
```bash
make deploy                    # Start infrastructure
cd python && python main.py run --no-kafka --duration 300  # Generate data
cd ../dbt && dbt run          # Transform data
make port-forward-trino       # Query data at localhost:8080
```

**To learn it**:
- Start with README
- Run the system, see output
- Read files in order (Day 1-15 above)
- Don't try to understand everything at once!

---

Good luck! Remember: This was built quickly by AI. Some parts are messy. Focus on understanding the concepts, not memorizing every line of code.
