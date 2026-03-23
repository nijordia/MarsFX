-- Custom test to verify OHLC logic across all candle models
-- Run with: dbt test --select test_type:singular

{% set models = ['ohlc_candles_1min', 'ohlc_candles_5min', 'ohlc_candles_1h', 'ohlc_candles_1d'] %}

{% for model_name in models %}

-- Test {{ model_name }}: Verify OHLC relationships
-- Low should be <= Open, High, Close
-- High should be >= Open, Low, Close
with validation as (
    select
        '{{ model_name }}' as model_name,
        currency_pair,
        candle_timestamp,
        open_price,
        high_price,
        low_price,
        close_price,

        -- Check violations
        case when low_price > open_price then 'low > open' end as violation_1,
        case when low_price > high_price then 'low > high' end as violation_2,
        case when low_price > close_price then 'low > close' end as violation_3,
        case when high_price < open_price then 'high < open' end as violation_4,
        case when high_price < low_price then 'high < low' end as violation_5,
        case when high_price < close_price then 'high < close' end as violation_6,

        -- Check nulls
        case when open_price is null then 'open is null' end as violation_7,
        case when high_price is null then 'high is null' end as violation_8,
        case when low_price is null then 'low is null' end as violation_9,
        case when close_price is null then 'close is null' end as violation_10

    from {{ ref(model_name) }}
)

select *
from validation
where
    violation_1 is not null
    or violation_2 is not null
    or violation_3 is not null
    or violation_4 is not null
    or violation_5 is not null
    or violation_6 is not null
    or violation_7 is not null
    or violation_8 is not null
    or violation_9 is not null
    or violation_10 is not null

{% if not loop.last %}
union all
{% endif %}

{% endfor %}
