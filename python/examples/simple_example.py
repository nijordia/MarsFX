#!/usr/bin/env python3
"""
Simple example of using the MarsFX data generator
Generates 5 minutes of tick data without Kafka
"""
import yaml
from pathlib import Path

from fx_generator import TickGenerator

def main():
    print("🪐 MarsFX Data Generator - Simple Example")
    print("=" * 50)

    # Load configuration
    config_path = Path(__file__).parent.parent / "config" / "generator_config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Override settings for this example
    config['output']['kafka_enabled'] = False  # No Kafka needed
    config['output']['parquet_enabled'] = True  # Write to Parquet
    config['generator']['time_acceleration_factor'] = 60  # 60x speed
    config['generator']['tick_rate_per_second'] = 5  # Lower rate for demo

    print(f"\nConfiguration:")
    print(f"  Currency Pairs: {len(config['currency_pairs'])}")
    print(f"  Tick Rate: {config['generator']['tick_rate_per_second']} ticks/sec/pair")
    print(f"  Time Acceleration: {config['generator']['time_acceleration_factor']}x")
    print(f"  Output: Parquet files in data/ticks/")

    # Create generator
    generator = TickGenerator(config=config)

    print(f"\nSimulation Start: {generator.simulation_start.isoformat()}")
    print("\nGenerating 5 minutes of data (press Ctrl+C to stop early)...")
    print("-" * 50)

    try:
        # Run for 5 minutes
        generator.run(duration_seconds=300)

    except KeyboardInterrupt:
        print("\n\nStopped by user")

    finally:
        # Show results
        stats = generator.stats
        print("\n" + "=" * 50)
        print("Generation Complete!")
        print("=" * 50)
        print(f"\nStatistics:")
        print(f"  Ticks Generated: {stats.ticks_generated:,}")
        print(f"  Events Generated: {stats.events_generated}")
        print(f"  Parquet Files Written: {stats.parquet_files_written}")
        print(f"  Parquet Rows: {stats.parquet_rows_written:,}")
        print(f"  Real Time: {stats.elapsed_real_seconds():.0f} seconds")
        print(f"  Simulated Time: {stats.elapsed_simulation_seconds()/3600:.2f} hours")
        print(f"  Ticks/Second: {stats.ticks_per_second:.2f}")

        print(f"\n📁 Output Location:")
        print(f"  data/ticks/")
        print(f"\n💾 Checkpoint Saved:")
        print(f"  data/checkpoints/generator_state.json")


if __name__ == "__main__":
    main()
