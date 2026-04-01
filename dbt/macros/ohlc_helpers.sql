{% macro get_lookback_window(candle_interval) %}
  {#
    Returns the appropriate lookback window for incremental OHLC models
    based on the candle interval.

    Args:
      candle_interval: '1min', '5min', '1h', or '1d'

    Returns:
      SQL interval expression for the lookback window
  #}

  {% if candle_interval == '1min' %}
    interval '{{ var("lookback_minutes")["1min"] }}' minute
  {% elif candle_interval == '5min' %}
    interval '{{ var("lookback_minutes")["5min"] }}' minute
  {% elif candle_interval == '1h' %}
    interval '{{ var("lookback_minutes")["1h"] }}' minute
  {% elif candle_interval == '1d' %}
    interval '{{ var("lookback_minutes")["1d"] }}' minute
  {% else %}
    {{ exceptions.raise_compiler_error("Invalid candle_interval: " ~ candle_interval) }}
  {% endif %}

{% endmacro %}


{% macro get_partition_by(candle_interval) %}
  {#
    Returns the appropriate Iceberg partition transform for the given candle interval.

    Args:
      candle_interval: '1min', '5min', '1h', or '1d'

    Returns:
      Iceberg partition transform expression
  #}

  {% if candle_interval == '1min' %}
    ARRAY['day(candle_timestamp)']
  {% elif candle_interval == '5min' %}
    ARRAY['day(candle_timestamp)']
  {% elif candle_interval == '1h' %}
    ARRAY['month(candle_timestamp)']
  {% elif candle_interval == '1d' %}
    ARRAY['year(candle_timestamp)']
  {% else %}
    {{ exceptions.raise_compiler_error("Invalid candle_interval: " ~ candle_interval) }}
  {% endif %}

{% endmacro %}


{% macro calculate_ohlc_prices() %}
  {#
    Generates the OHLC price calculation SQL using row_number() approach.
    Expects columns: rn_first, rn_last, trade_price

    Returns:
      SQL for calculating open, high, low, close prices
  #}

  min(trade_price) as low_price,
  max(trade_price) as high_price,
  max(case when rn_first = 1 then trade_price end) as open_price,
  max(case when rn_last = 1 then trade_price end) as close_price

{% endmacro %}


{% macro calculate_price_metrics() %}
  {#
    Generates derived price metrics from OHLC prices.
    Expects columns: open_price, high_price, low_price, close_price

    Returns:
      SQL for calculating price_change, price_change_pct, volatility_pct, price_range
  #}

  close_price - open_price as price_change,
  case
    when open_price > 0 then ((close_price - open_price) / open_price) * 100
    else null
  end as price_change_pct,

  high_price - low_price as price_range,
  case
    when open_price > 0 then ((high_price - low_price) / open_price) * 100
    else null
  end as volatility_pct

{% endmacro %}


{% macro calculate_volume_metrics() %}
  {#
    Generates volume aggregation metrics.
    Expects column: volume

    Returns:
      SQL for calculating total_volume, avg_trade_volume, trade_count
  #}

  sum(volume) as total_volume,
  avg(volume) as avg_trade_volume,
  count(*) as trade_count

{% endmacro %}


{% macro calculate_spread_metrics() %}
  {#
    Generates spread metrics.
    Expects column: spread_bps

    Returns:
      SQL for calculating avg_spread_bps, min_spread_bps, max_spread_bps
  #}

  avg(spread_bps) as avg_spread_bps,
  min(spread_bps) as min_spread_bps,
  max(spread_bps) as max_spread_bps

{% endmacro %}


{% macro truncate_to_interval(timestamp_column, interval_type) %}
  {#
    Truncates a timestamp to the specified interval.

    Args:
      timestamp_column: Name of the timestamp column
      interval_type: 'minute', '5min', 'hour', 'day'

    Returns:
      SQL expression for truncated timestamp
  #}

  {% if interval_type == 'minute' %}
    date_trunc('minute', {{ timestamp_column }})

  {% elif interval_type == '5min' %}
    date_trunc('minute', {{ timestamp_column }}) -
    (interval '1' minute * (minute({{ timestamp_column }}) % 5))

  {% elif interval_type == 'hour' %}
    date_trunc('hour', {{ timestamp_column }})

  {% elif interval_type == 'day' %}
    date_trunc('day', {{ timestamp_column }})

  {% else %}
    {{ exceptions.raise_compiler_error("Invalid interval_type: " ~ interval_type) }}
  {% endif %}

{% endmacro %}


{% macro add_row_numbers(partition_cols, timestamp_column) %}
  {#
    Adds row numbers for first/last tick identification.

    Args:
      partition_cols: List of columns to partition by
      timestamp_column: Column to order by

    Returns:
      SQL for row_number() window functions
  #}

  row_number() over (
    partition by {{ partition_cols | join(', ') }}
    order by {{ timestamp_column }} asc
  ) as rn_first,
  row_number() over (
    partition by {{ partition_cols | join(', ') }}
    order by {{ timestamp_column }} desc
  ) as rn_last

{% endmacro %}


{% macro ohlc_config(candle_interval) %}
  {#
    Generates complete dbt config block for OHLC models.

    Args:
      candle_interval: '1min', '5min', '1h', or '1d'

    Returns:
      Complete config() block
  #}

  {{
    config(
      materialized='incremental',
      incremental_strategy='merge',
      unique_key=['currency_pair', 'candle_timestamp'],
      properties={
        "format": "'PARQUET'",
        "partitioning": get_partition_by(candle_interval),
        "sorted_by": "ARRAY['currency_pair', 'candle_timestamp']"
      },
      tags=['marts', 'ohlc', candle_interval]
    )
  }}

{% endmacro %}


{% macro get_incremental_test_bounds(model_name) %}
  {#
    Returns a WHERE clause for incremental test validation.
    Only tests recent data to avoid expensive full-table scans.

    Args:
      model_name: Name of the model (e.g., 'ohlc_candles_1min')

    Returns:
      SQL WHERE clause fragment (e.g., "candle_timestamp > CURRENT_TIMESTAMP - INTERVAL '2' HOUR")
  #}

  {% if model_name == 'ohlc_candles_1min' %}
    candle_timestamp > CURRENT_TIMESTAMP - INTERVAL '2' HOUR

  {% elif model_name == 'ohlc_candles_5min' %}
    candle_timestamp > CURRENT_TIMESTAMP - INTERVAL '1' HOUR

  {% elif model_name == 'ohlc_candles_1h' %}
    candle_timestamp > CURRENT_TIMESTAMP - INTERVAL '3' HOUR

  {% elif model_name == 'ohlc_candles_1d' %}
    candle_timestamp > CURRENT_TIMESTAMP - INTERVAL '2' DAY

  {% else %}
    {{ exceptions.raise_compiler_error("Unknown model for incremental test bounds: " ~ model_name) }}
  {% endif %}

{% endmacro %}
