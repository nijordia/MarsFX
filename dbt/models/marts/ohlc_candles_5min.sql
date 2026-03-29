{{
  config(
    materialized='incremental',
    incremental_strategy='merge',
    unique_key=['currency_pair', 'candle_timestamp'],
    views_enabled=false,
    properties={
      "format": "'PARQUET'",
      "partitioning": "ARRAY['day(candle_timestamp)']",
      "sorted_by": "ARRAY['currency_pair', 'candle_timestamp']"
    },
    tags=['marts', 'ohlc', '5min']
  )
}}

/*
  5-minute OHLC candles from FX tick data
  - Aggregates tick data into 5-minute intervals
  - Calculates open, high, low, close prices
  - Tracks volume and trade count
  - Incremental: Only processes new data with 15-minute lookback window
*/

with source_ticks as (
    select * from {{ ref('stg_fx_ticks') }}
    {% if is_incremental() %}
        -- Include lookback window to handle late-arriving data
        -- Process from 15 minutes before the latest candle to avoid gaps
        where date_trunc('minute', transaction_timestamp) >= (
            select max(candle_timestamp) - interval '{{ var("lookback_minutes")["5min"] }}' minute from {{ this }}
        )
    {% endif %}
),

-- Use window functions to get first/last prices correctly
ticks_with_order as (
    select
        date_trunc('minute', transaction_timestamp) -
            (interval '1' minute * (minute(transaction_timestamp) % 5)) as candle_timestamp,
        currency_pair,
        base_currency,
        quote_currency,
        transaction_timestamp,
        trade_price,
        volume,
        spread_bps,
        exchange_location,
        row_number() over (
            partition by
                currency_pair,
                date_trunc('minute', transaction_timestamp) -
                (interval '1' minute * (minute(transaction_timestamp) % 5))
            order by transaction_timestamp asc
        ) as rn_first,
        row_number() over (
            partition by
                currency_pair,
                date_trunc('minute', transaction_timestamp) -
                (interval '1' minute * (minute(transaction_timestamp) % 5))
            order by transaction_timestamp desc
        ) as rn_last
    from source_ticks
),

candles as (
    select
        candle_timestamp,
        currency_pair,
        base_currency,
        quote_currency,

        -- OHLC prices using proper first/last row logic
        min(trade_price) as low_price,
        max(trade_price) as high_price,
        max(case when rn_first = 1 then trade_price end) as open_price,
        max(case when rn_last = 1 then trade_price end) as close_price,

        -- Volume metrics
        sum(volume) as total_volume,
        avg(volume) as avg_trade_volume,
        count(*) as trade_count,

        -- Spread metrics
        avg(spread_bps) as avg_spread_bps,
        min(spread_bps) as min_spread_bps,
        max(spread_bps) as max_spread_bps,

        -- Exchange distribution
        count(distinct exchange_location) as num_exchanges,

        -- Timestamps
        min(transaction_timestamp) as period_start,
        max(transaction_timestamp) as period_end,
        current_timestamp as calculated_at

    from ticks_with_order
    group by
        candle_timestamp,
        currency_pair,
        base_currency,
        quote_currency
),

with_metrics as (
    select
        *,
        -- Price change metrics
        close_price - open_price as price_change,
        case
            when open_price > 0 then ((close_price - open_price) / open_price) * 100
            else null
        end as price_change_pct,

        -- Volatility (high-low range)
        high_price - low_price as price_range,
        case
            when open_price > 0 then ((high_price - low_price) / open_price) * 100
            else null
        end as volatility_pct,

        -- Candle characteristics
        '5min' as candle_interval

    from candles
)

select * from with_metrics
