{% macro test_incremental_expression_is_true(model, expression, model_name) %}
  {#
    Custom generic test: validates an expression on only recent data.
    Uses get_incremental_test_bounds macro to limit scan to recent rows.

    Args:
      model: The model to test
      expression: SQL boolean expression to validate (e.g., "low_price <= high_price")
      model_name: Model name to determine test window (e.g., 'ohlc_candles_1min')
  #}

  SELECT *
  FROM {{ model }}
  WHERE NOT ({{ expression }})
  AND {{ get_incremental_test_bounds(model_name) }}

{% endmacro %}
