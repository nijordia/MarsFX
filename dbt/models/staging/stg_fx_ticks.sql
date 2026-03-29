{{
  config(
    materialized='table',
    tags=['staging', 'fx_ticks'],
    properties={
      "format": "'PARQUET'"
    }
  )
}}

/*
  Staging model for FX ticks
  - Renames columns to consistent naming convention
  - Casts data types
  - Adds calculated fields
  - Basic data quality filters
*/

with source as (
    select * from {{ source('fx_raw', 'raw_ticks_streaming') }}
),

renamed_and_typed as (
    select
        -- Primary key
        cast(tick_id as varchar) as tick_id,

        -- Timestamps
        cast(transaction_timestamp as timestamp(6)) as transaction_timestamp,
        cast(event_time as timestamp(6)) as event_time,

        -- Currency pair
        cast(currency_pair as varchar(20)) as currency_pair,
        split_part(currency_pair, '/', 1) as base_currency,
        split_part(currency_pair, '/', 2) as quote_currency,

        -- Prices
        cast(bid_price as decimal(18,8)) as bid_price,
        cast(ask_price as decimal(18,8)) as ask_price,
        cast(mid_price as decimal(18,8)) as mid_price,
        cast(trade_price as decimal(18,8)) as trade_price,
        cast(spread_bps as decimal(8,2)) as spread_bps,

        -- Volume
        cast(volume as decimal(18,8)) as volume,

        -- Metadata
        cast(exchange_location as varchar(50)) as exchange_location,
        cast(trader_type as varchar(50)) as trader_type

    from source
),

filtered as (
    select *
    from renamed_and_typed
    where
        -- Data quality filters
        bid_price > 0
        and ask_price > 0
        and mid_price > 0
        and trade_price > 0
        and volume > 0
        and ask_price >= bid_price  -- Ask should always be >= bid
        and transaction_timestamp is not null
        and currency_pair is not null
)

select * from filtered
