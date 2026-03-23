#!/usr/bin/env python3
"""
MarsFX Data Generator CLI
Main entry point for running the FX tick generator
"""
import sys
from pathlib import Path

import click
import structlog
import yaml
from confluent_kafka import Producer
from rich.console import Console
from rich.table import Table

from fx_generator import TickGenerator

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger()
console = Console()


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file"""
    if not config_path.exists():
        console.print(f"[red]Error: Config file not found: {config_path}[/red]")
        sys.exit(1)

    with open(config_path) as f:
        return yaml.safe_load(f)


def create_kafka_producer(config: dict) -> Producer:
    """Create Kafka producer from configuration"""
    kafka_config = config['kafka']

    producer_config = {
        'bootstrap.servers': kafka_config['bootstrap_servers'],
        **kafka_config.get('producer_config', {}),
    }

    try:
        producer = Producer(producer_config)
        logger.info("kafka_producer_created", servers=kafka_config['bootstrap_servers'])
        return producer
    except Exception as e:
        logger.error("kafka_producer_error", error=str(e))
        return None


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """MarsFX Data Generator - Simulate interplanetary FX markets"""
    pass


@cli.command()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    default='config/generator_config.yaml',
    help='Path to configuration file',
)
@click.option(
    '--duration',
    '-d',
    type=int,
    help='Run duration in seconds (default: run forever)',
)
@click.option(
    '--resume',
    '-r',
    is_flag=True,
    help='Resume from last checkpoint',
)
@click.option(
    '--no-kafka',
    is_flag=True,
    help='Disable Kafka output (Parquet only)',
)
@click.option(
    '--no-parquet',
    is_flag=True,
    help='Disable Parquet output (Kafka only)',
)
def run(config, duration, resume, no_kafka, no_parquet):
    """Run the FX tick data generator"""
    console.print("[bold blue]🪐 MarsFX Data Generator[/bold blue]")
    console.print("Starting interplanetary FX market simulation...\n")

    # Load configuration
    config_path = Path(config)
    config_dict = load_config(config_path)

    # Override output settings
    if no_kafka:
        config_dict['output']['kafka_enabled'] = False
    if no_parquet:
        config_dict['output']['parquet_enabled'] = False

    # Create Kafka producer if enabled
    kafka_producer = None
    if config_dict['output']['kafka_enabled']:
        kafka_producer = create_kafka_producer(config_dict)
        if not kafka_producer:
            console.print("[yellow]Warning: Kafka producer failed, disabling Kafka output[/yellow]")
            config_dict['output']['kafka_enabled'] = False

    # Initialize generator
    generator = TickGenerator(config=config_dict, kafka_producer=kafka_producer)

    # Load checkpoint if requested
    if resume:
        console.print("[cyan]Loading checkpoint...[/cyan]")
        if generator.load_checkpoint():
            console.print("[green]✓ Checkpoint loaded successfully[/green]\n")
        else:
            console.print("[yellow]⚠ No checkpoint found, starting fresh[/yellow]\n")

    # Display configuration
    display_config(config_dict, generator)

    # Run generator
    try:
        console.print("[bold green]Starting generator...[/bold green]")
        console.print("Press Ctrl+C to stop\n")

        generator.run(duration_seconds=duration)

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping generator...[/yellow]")

    finally:
        # Display final stats
        display_stats(generator.stats)

        # Flush Kafka producer
        if kafka_producer:
            console.print("Flushing Kafka messages...")
            kafka_producer.flush()

        console.print("[bold green]✓ Generator stopped[/bold green]")


@cli.command()
@click.option(
    '--config',
    '-c',
    type=click.Path(exists=True),
    default='config/generator_config.yaml',
    help='Path to configuration file',
)
def info(config):
    """Display generator configuration information"""
    config_path = Path(config)
    config_dict = load_config(config_path)

    console.print("[bold blue]📊 MarsFX Generator Configuration[/bold blue]\n")

    # Currency Pairs
    table = Table(title="Currency Pairs")
    table.add_column("Pair", style="cyan")
    table.add_column("Base Price", justify="right")
    table.add_column("Volatility", justify="right")
    table.add_column("Exchange", style="green")

    for pair in config_dict['currency_pairs']:
        table.add_row(
            pair['name'],
            f"{pair['base_price']:.4f}",
            f"{pair['volatility']*100:.1f}%",
            pair['primary_exchange'],
        )

    console.print(table)
    console.print()

    # Generator Settings
    table = Table(title="Generator Settings")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", justify="right")

    gen_config = config_dict['generator']
    table.add_row("Tick Rate", f"{gen_config['tick_rate_per_second']} ticks/sec/pair")
    table.add_row("Time Acceleration", f"{gen_config['time_acceleration_factor']}x")
    table.add_row("Event Probability", f"{gen_config['event_probability_per_minute']*100:.1f}%/min")
    table.add_row("Checkpoint Interval", f"{gen_config['checkpoint_interval_seconds']} seconds")

    console.print(table)
    console.print()

    # Event Types
    table = Table(title="Economic Event Types")
    table.add_column("Type", style="cyan")
    table.add_column("Probability", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Severity", justify="right")

    for event in config_dict['economic_events']:
        table.add_row(
            event['type'],
            f"{event['probability_weight']*100:.0f}%",
            f"{event['duration_minutes'][0]}-{event['duration_minutes'][1]} min",
            f"{event['severity_range'][0]}-{event['severity_range'][1]}",
        )

    console.print(table)


def display_config(config: dict, generator: TickGenerator):
    """Display current generator configuration"""
    table = Table(title="Active Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Currency Pairs", str(len(generator.currency_pairs)))
    table.add_row("Tick Rate", f"{generator.tick_rate} ticks/sec/pair")
    table.add_row("Time Acceleration", f"{generator.time_acceleration}x")
    table.add_row("Kafka Output", "✓" if config['output']['kafka_enabled'] else "✗")
    table.add_row("Parquet Output", "✓" if config['output']['parquet_enabled'] else "✗")
    table.add_row("Simulation Start", generator.simulation_start.isoformat())

    console.print(table)
    console.print()


def display_stats(stats):
    """Display generator statistics"""
    table = Table(title="Generation Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="green")

    table.add_row("Ticks Generated", f"{stats.ticks_generated:,}")
    table.add_row("Events Generated", f"{stats.events_generated:,}")
    table.add_row("Active Events", f"{stats.active_events}")
    table.add_row("Ticks/Second", f"{stats.ticks_per_second:.2f}")
    table.add_row("Kafka Messages Sent", f"{stats.kafka_messages_sent:,}")
    table.add_row("Kafka Errors", f"{stats.kafka_errors}")
    table.add_row("Parquet Files Written", f"{stats.parquet_files_written}")
    table.add_row("Parquet Rows Written", f"{stats.parquet_rows_written:,}")

    elapsed = stats.elapsed_real_seconds()
    table.add_row("Real Time Elapsed", f"{elapsed:.0f} seconds")

    sim_elapsed = stats.elapsed_simulation_seconds()
    table.add_row("Simulated Time Elapsed", f"{sim_elapsed/3600:.1f} hours")

    console.print(table)


@cli.command()
@click.option(
    '--checkpoint-path',
    '-p',
    type=click.Path(),
    default='data/checkpoints/generator_state.json',
    help='Path to checkpoint file',
)
def checkpoint_info(checkpoint_path):
    """Display information about a checkpoint file"""
    import json

    checkpoint_path = Path(checkpoint_path)

    if not checkpoint_path.exists():
        console.print(f"[red]Checkpoint file not found: {checkpoint_path}[/red]")
        return

    with open(checkpoint_path) as f:
        data = json.load(f)

    console.print("[bold blue]📍 Checkpoint Information[/bold blue]\n")

    table = Table()
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Checkpoint ID", data['checkpoint_id'])
    table.add_row("Checkpoint Time", data['checkpoint_timestamp'])
    table.add_row("Simulation Time", data['simulation_timestamp'])
    table.add_row("Ticks Generated", f"{data['ticks_generated']:,}")
    table.add_row("Events Generated", f"{data['events_generated']:,}")
    table.add_row("Active Events", f"{len(data['active_events'])}")

    console.print(table)
    console.print()

    # Currency pair prices
    table = Table(title="Current Prices")
    table.add_column("Pair", style="cyan")
    table.add_column("Price", justify="right", style="green")

    for pair, price in data['currency_pair_prices'].items():
        table.add_row(pair, f"{price:.4f}")

    console.print(table)


if __name__ == '__main__':
    cli()
