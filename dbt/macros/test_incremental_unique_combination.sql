{% macro test_incremental_unique_combination_of_columns(model, combination_of_columns, model_name) %}
  {#
    Custom generic test: validates uniqueness on only recent data.
    Uses get_incremental_test_bounds macro to limit scan to recent rows.

    Args:
      model: The model to test
      combination_of_columns: List of columns that should form a unique combination
      model_name: Model name to determine test window (e.g., 'ohlc_candles_1min')
  #}

  SELECT *
  FROM (
    SELECT
      {{ combination_of_columns | join(', ') }},
      COUNT(*) as occurrences
    FROM {{ model }}
    WHERE {{ get_incremental_test_bounds(model_name) }}
    GROUP BY {{ combination_of_columns | join(', ') }}
    HAVING COUNT(*) > 1
  )

{% endmacro %}
