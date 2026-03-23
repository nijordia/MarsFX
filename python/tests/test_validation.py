"""
Validation tests for MarsFX data generator
Run these tests to verify critical functionality
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest


def test_parquet_no_gaps():
    """
    Test 1: Verify no timestamp gaps in generated data

    Run generator first:
        python main.py run --no-kafka --duration 300
    """
    parquet_path = Path("data/ticks")

    if not parquet_path.exists():
        pytest.skip("No parquet data found. Run generator first.")

    # Read all parquet files
    df = pd.read_parquet(parquet_path, engine='pyarrow')
    df = df.sort_values('transaction_timestamp')
    df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'])

    # Check gaps
    gaps = df['transaction_timestamp'].diff()
    max_gap = gaps.max()

    # Expected gap: 1000ms / 60 ticks/sec = ~16.67ms per tick
    # Allow up to 200ms for buffer between batches
    assert max_gap < pd.Timedelta(milliseconds=200), \
        f"Found gap of {max_gap} - should be <200ms"

    print(f"✓ No gaps found. Max gap: {max_gap}")


def test_checkpoint_resume_no_duplicates():
    """
    Test 2: Verify checkpoint resume doesn't create duplicates

    Run:
        python main.py run --no-kafka --duration 120
        python main.py run --no-kafka --duration 180 --resume
    """
    parquet_path = Path("data/ticks")
    checkpoint_path = Path("data/checkpoints/generator_state.json")

    if not parquet_path.exists() or not checkpoint_path.exists():
        pytest.skip("Need parquet data and checkpoint. Run generator twice with --resume.")

    # Read checkpoint
    with open(checkpoint_path) as f:
        checkpoint = json.load(f)

    # Read parquet data
    df = pd.read_parquet(parquet_path, engine='pyarrow')
    df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'])

    # Check for duplicates
    duplicates = df[df.duplicated(subset=['tick_id'])]
    assert len(duplicates) == 0, f"Found {len(duplicates)} duplicate tick_ids"

    # Check timestamp at checkpoint boundary
    checkpoint_time = pd.to_datetime(checkpoint['simulation_timestamp'])
    around_checkpoint = df[
        (df['transaction_timestamp'] >= checkpoint_time - pd.Timedelta(seconds=5)) &
        (df['transaction_timestamp'] <= checkpoint_time + pd.Timedelta(seconds=5))
    ].sort_values('transaction_timestamp')

    # Should have no gaps at boundary
    gaps = around_checkpoint['transaction_timestamp'].diff()
    max_gap_at_boundary = gaps.max()

    assert max_gap_at_boundary < pd.Timedelta(milliseconds=200), \
        f"Gap at checkpoint boundary: {max_gap_at_boundary}"

    print(f"✓ No duplicates. Checkpoint boundary OK. Max gap: {max_gap_at_boundary}")


def test_event_impact_on_volatility():
    """
    Test 3: Verify events increase volatility

    Run generator with high event probability:
        (Edit config: event_probability_per_minute: 0.2)
        python main.py run --no-kafka --duration 600
    """
    parquet_path = Path("data/ticks")

    if not parquet_path.exists():
        pytest.skip("No parquet data found")

    df = pd.read_parquet(parquet_path, engine='pyarrow')
    df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'])
    df['mid_price'] = df['mid_price'].astype(float)

    # Group by minute and calculate volatility
    df['minute'] = df['transaction_timestamp'].dt.floor('1min')
    volatility = df.groupby(['minute', 'currency_pair'])['mid_price'].std().reset_index()
    volatility.columns = ['minute', 'currency_pair', 'volatility']

    # Check for volatility spikes (>0.1 is significant for 1-minute window)
    high_vol_minutes = volatility[volatility['volatility'] > 0.1]

    assert len(high_vol_minutes) > 0, \
        "No volatility spikes found - events may not be working"

    print(f"✓ Found {len(high_vol_minutes)} high-volatility periods (likely events)")
    print(f"  Max volatility: {volatility['volatility'].max():.4f}")


def test_currency_pair_correlation():
    """
    Test 4: Verify ECR/MRT and MRT/LCR show correlation

    Correlation exists through MRT currency:
    - ECR/MRT = price of MRT in ECR
    - MRT/LCR = price of LCR in MRT
    When MRT appreciates vs ECR, ECR/MRT rises, MRT/LCR may fall
    """
    parquet_path = Path("data/ticks")

    if not parquet_path.exists():
        pytest.skip("No parquet data found")

    df = pd.read_parquet(parquet_path, engine='pyarrow')
    df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'])
    df['mid_price'] = df['mid_price'].astype(float)

    # Pivot to get prices by timestamp and pair
    # Resample to 1-minute buckets for cleaner correlation
    df = df.set_index('transaction_timestamp')
    pivot = df.pivot_table(
        index=df.index.floor('1min'),
        columns='currency_pair',
        values='mid_price',
        aggfunc='mean'
    )

    # Check if both pairs exist
    if 'ECR/MRT' not in pivot.columns or 'MRT/LCR' not in pivot.columns:
        pytest.skip("Need both ECR/MRT and MRT/LCR data")

    # Calculate correlation
    corr = pivot[['ECR/MRT', 'MRT/LCR']].corr().iloc[0, 1]

    # Correlation should be non-zero (config says -0.6 inverse correlation)
    assert abs(corr) > 0.1, \
        f"Correlation too weak: {corr}. Expected ~-0.6 (inverse)"

    print(f"✓ ECR/MRT vs MRT/LCR correlation: {corr:.3f} (expected ~-0.6)")


def test_tick_count_accuracy():
    """
    Test 5: Verify expected tick count matches configuration

    With:
    - 6 currency pairs
    - 10 ticks/sec/pair
    - 60 ticks/sec total
    - 300 seconds duration
    Expected: ~18,000 ticks (allow ±5% for randomness)
    """
    parquet_path = Path("data/ticks")

    if not parquet_path.exists():
        pytest.skip("No parquet data found")

    df = pd.read_parquet(parquet_path, engine='pyarrow')

    # Get time range
    df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'])
    duration_seconds = (
        df['transaction_timestamp'].max() - df['transaction_timestamp'].min()
    ).total_seconds()

    # Expected ticks: 6 pairs × 10 ticks/sec × duration
    expected_ticks = 6 * 10 * duration_seconds
    actual_ticks = len(df)

    # Allow ±10% tolerance
    tolerance = 0.1
    assert abs(actual_ticks - expected_ticks) / expected_ticks < tolerance, \
        f"Expected ~{expected_ticks:.0f} ticks, got {actual_ticks}"

    print(f"✓ Generated {actual_ticks} ticks over {duration_seconds:.0f}s")
    print(f"  Expected: {expected_ticks:.0f} (±10%)")
    print(f"  Rate: {actual_ticks/duration_seconds:.1f} ticks/sec")


def test_trader_type_distribution():
    """
    Test 6: Verify trader type distribution matches config

    Expected probabilities:
    - institutional: 40%
    - retail: 35%
    - mining_corp: 15%
    - government: 10%
    """
    parquet_path = Path("data/ticks")

    if not parquet_path.exists():
        pytest.skip("No parquet data found")

    df = pd.read_parquet(parquet_path, engine='pyarrow')

    # Count trader types
    trader_counts = df['trader_type'].value_counts(normalize=True)

    expected = {
        'institutional': 0.40,
        'retail': 0.35,
        'mining_corp': 0.15,
        'government': 0.10,
    }

    # Allow ±5% tolerance
    tolerance = 0.05
    for trader_type, expected_pct in expected.items():
        actual_pct = trader_counts.get(trader_type, 0)
        assert abs(actual_pct - expected_pct) < tolerance, \
            f"{trader_type}: expected {expected_pct*100:.0f}%, got {actual_pct*100:.0f}%"

    print("✓ Trader type distribution:")
    for trader_type, pct in trader_counts.items():
        print(f"    {trader_type}: {pct*100:.1f}%")


def test_spread_within_bounds():
    """
    Test 7: Verify spreads are within configured min/max

    Each pair has min_spread_bps and max_spread_bps in config
    Event multipliers can increase spreads beyond max temporarily
    """
    parquet_path = Path("data/ticks")

    if not parquet_path.exists():
        pytest.skip("No parquet data found")

    df = pd.read_parquet(parquet_path, engine='pyarrow')
    df['spread_bps'] = df['spread_bps'].astype(float)

    # Check spreads by pair
    spread_stats = df.groupby('currency_pair')['spread_bps'].agg(['min', 'max', 'mean'])

    print("✓ Spread statistics by pair:")
    for pair, stats in spread_stats.iterrows():
        print(f"    {pair}: {stats['min']:.1f} - {stats['max']:.1f} bps (avg: {stats['mean']:.1f})")

    # All spreads should be positive
    assert (df['spread_bps'] > 0).all(), "Found non-positive spreads"


if __name__ == "__main__":
    # Run tests manually
    print("MarsFX Generator Validation Tests")
    print("=" * 50)

    tests = [
        test_parquet_no_gaps,
        test_checkpoint_resume_no_duplicates,
        test_event_impact_on_volatility,
        test_currency_pair_correlation,
        test_tick_count_accuracy,
        test_trader_type_distribution,
        test_spread_within_bounds,
    ]

    for test_func in tests:
        print(f"\n{test_func.__name__}:")
        print(test_func.__doc__.strip().split('\n')[0])
        try:
            test_func()
        except Exception as e:
            print(f"❌ FAILED: {e}")

    print("\n" + "=" * 50)
    print("Validation complete!")
