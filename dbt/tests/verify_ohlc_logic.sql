-- Custom test to verify OHLC logic across all candle models
-- Run with: dbt test --select test_type:singular

{% set models = ['ohlc_candles_1min', 'ohlc_candles_5min', 'ohlc_candles_1h', 'ohlc_candles_1d'] %}

{% for model_name in models %}

select
    '{{ model_name }}' as model_name,
    currency_pair,
    candle_timestamp,
    open_price,
    high_price,
    low_price,
    close_price
from {{ ref(model_name) }}
where
    low_price > open_price
    or low_price > high_price
    or low_price > close_price
    or high_price < open_price
    or high_price < close_price
    or open_price is null
    or high_price is null
    or low_price is null
    or close_price is null

{% if not loop.last %}
union all
{% endif %}

{% endfor %}
