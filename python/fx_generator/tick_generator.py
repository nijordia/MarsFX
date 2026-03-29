"""
Main tick generator orchestrating price simulation, events, and output
"""
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import structlog

from .event_generator import BusinessHoursModulator, EventGenerator
from .models import (
    CurrencyPair,
    EconomicEvent,
    ExchangeLocation,
    FXTick,
    GeneratorState,
    GeneratorStats,
    TraderType,
)
from .price_simulator import PriceSimulator

logger = structlog.get_logger()


class TickGenerator:
    """
    Main FX tick generator
    Orchestrates price simulation, event generation, and data output
    """

    def __init__(
        self,
        config: Dict,
        kafka_producer=None,  # Will be KafkaProducer instance
    ):
        """
        Initialize tick generator

        Args:
            config: Configuration dictionary from YAML
            kafka_producer: Optional Kafka producer for streaming
        """
        self.config = config
        self.kafka_producer = kafka_producer

        # Parse configuration
        gen_config = config['generator']
        self.tick_rate = gen_config['tick_rate_per_second']
        self.time_acceleration = gen_config['time_acceleration_factor']
        self.event_probability = gen_config['event_probability_per_minute']
        self.checkpoint_interval = gen_config['checkpoint_interval_seconds']
        self.random_seed = gen_config.get('random_seed')

        # Parse currency pairs
        self.currency_pairs = [CurrencyPair(**cp) for cp in config['currency_pairs']]

        # Initialize price simulator
        self.price_simulator = PriceSimulator(
            currency_pairs=self.currency_pairs,
            time_acceleration=self.time_acceleration,
            random_seed=self.random_seed,
        )

        # Initialize event generator
        self.event_generator = EventGenerator(
            event_config=config['economic_events'],
            event_probability_per_minute=self.event_probability,
            random_seed=self.random_seed,
        )

        # Initialize business hours modulator
        self.business_hours = BusinessHoursModulator(
            volume_by_hour=config['business_hours']['volume_by_hour']
        )

        # Simulation state
        self.simulation_start = self._parse_simulation_start()
        self.simulation_time = self.simulation_start
        self.real_start_time = datetime.utcnow()
        self.last_checkpoint_time = datetime.utcnow()

        # Event tracking
        self.all_events: List[EconomicEvent] = []
        self.active_events: List[EconomicEvent] = []

        # Statistics
        self.stats = GeneratorStats(
            start_time=self.real_start_time,
            current_time=datetime.utcnow(),
            simulation_time=self.simulation_time,
            time_acceleration_factor=self.time_acceleration,
        )

        # Output configuration
        self.kafka_enabled = config['output']['kafka_enabled']
        self.parquet_enabled = config['output']['parquet_enabled']
        self.parquet_base_path = Path(config['output']['parquet_base_path'])
        self.checkpoint_path = Path(config['output']['checkpoint_path'])

        # Parquet buffer (write in batches)
        self.parquet_buffer: List[Dict] = []
        self.parquet_buffer_size = config['output'].get('parquet_row_group_size', 10000)

        # Trader type configuration
        self.trader_types = self._parse_trader_types()

        # Exchange configuration
        self.exchanges = self._parse_exchanges()

        logger.info(
            "tick_generator_initialized",
            currency_pairs=len(self.currency_pairs),
            tick_rate=self.tick_rate,
            time_acceleration=self.time_acceleration,
            simulation_start=self.simulation_start.isoformat(),
        )

    def _parse_simulation_start(self) -> datetime:
        """Parse simulation start date from config"""
        start_str = self.config['generator'].get('simulation_start_date')
        if start_str:
            return datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        return datetime.utcnow()

    def _parse_trader_types(self) -> List[Dict]:
        """Parse trader types from config"""
        return self.config.get('trader_types', [])

    def _parse_exchanges(self) -> List[Dict]:
        """Parse exchange info from config"""
        return self.config.get('exchanges', [])

    def _select_trader_type(self) -> TraderType:
        """Randomly select trader type based on probabilities"""
        types = []
        probs = []

        for trader in self.trader_types:
            types.append(trader['type'])
            probs.append(trader['probability'])

        # Normalize probabilities
        total_prob = sum(probs)
        probs = [p / total_prob for p in probs]

        selected = random.choices(types, weights=probs)[0]
        return TraderType(selected)

    def _select_exchange(self, pair: str) -> ExchangeLocation:
        """Select exchange based on pair's primary exchange and business hours"""
        # Get primary exchange from currency pair config
        cp = next((cp for cp in self.currency_pairs if cp.name == pair), None)
        if cp and hasattr(cp, 'primary_exchange'):
            try:
                return ExchangeLocation(cp.primary_exchange)
            except ValueError:
                pass

        # Random selection as fallback
        exchanges = list(ExchangeLocation)
        return random.choice(exchanges)

    def generate_tick(self, pair: str, current_time: datetime) -> FXTick:
        """
        Generate a single FX tick

        Args:
            pair: Currency pair name
            current_time: Current simulation timestamp

        Returns:
            FXTick instance
        """
        # Get trader type
        trader_type = self._select_trader_type()

        # Get exchange
        exchange = self._select_exchange(pair)

        # Get volume multiplier from business hours
        volume_mult = self.business_hours.get_volume_multiplier(current_time)

        # Get prices
        bid, ask, mid = self.price_simulator.get_bid_ask_spread(pair)
        trade_price = self.price_simulator.get_trade_price(pair, trader_type.value)

        # Get volume
        volume = self.price_simulator.get_trade_volume(
            pair, trader_type.value, volume_mult
        )

        # Calculate spread in bps
        spread_bps = float(((ask - bid) / mid) * 10000)

        # Create tick
        tick = FXTick(
            transaction_timestamp=current_time,
            currency_pair=pair,
            bid_price=bid,
            ask_price=ask,
            mid_price=mid,
            spread_bps=spread_bps,
            trade_price=trade_price,
            volume=volume,
            exchange_location=exchange,
            trader_type=trader_type,
            event_time=datetime.utcnow(),
        )

        return tick

    def generate_batch(self, dt_seconds: float) -> List[FXTick]:
        """
        Generate a batch of ticks for the given time step

        Args:
            dt_seconds: Time step in real seconds

        Returns:
            List of generated ticks
        """
        # Calculate how many ticks to generate
        ticks_per_pair = int(self.tick_rate * dt_seconds)
        if ticks_per_pair < 1:
            # Probabilistic generation for low tick rates
            if random.random() < (self.tick_rate * dt_seconds):
                ticks_per_pair = 1
            else:
                ticks_per_pair = 0

        # Update simulation time
        dt_sim_seconds = dt_seconds * self.time_acceleration
        self.simulation_time += timedelta(seconds=dt_sim_seconds)

        # Check for new events
        dt_sim_minutes = dt_sim_seconds / 60
        if self.event_generator.should_generate_event(dt_sim_minutes):
            event = self.event_generator.generate_event(self.simulation_time)
            if event:
                self.all_events.append(event)
                self.active_events.append(event)
                self.price_simulator.add_event(event)
                self.stats.events_generated += 1

                logger.info(
                    "event_generated",
                    event_type=event.event_type.value,
                    severity=event.severity,
                    affected_currencies=event.affected_currencies,
                    duration_minutes=event.duration_minutes,
                )

                # Output event to Kafka if enabled
                if self.kafka_enabled and self.kafka_producer:
                    self._send_event_to_kafka(event)

        # Update active events
        self.price_simulator.update_active_events(self.simulation_time)
        self.active_events = [e for e in self.active_events if e.is_active(self.simulation_time)]
        self.stats.active_events = len(self.active_events)

        # Update prices
        volume_mult = self.business_hours.get_volume_multiplier(self.simulation_time)
        self.price_simulator.update_prices(dt_seconds, volume_mult)

        # Generate ticks for all pairs
        ticks = []
        for pair in [cp.name for cp in self.currency_pairs]:
            for _ in range(ticks_per_pair):
                # Add small random offset to transaction time
                time_offset = timedelta(
                    milliseconds=random.uniform(0, dt_sim_seconds * 1000)
                )
                tick_time = self.simulation_time - timedelta(seconds=dt_sim_seconds) + time_offset

                tick = self.generate_tick(pair, tick_time)
                ticks.append(tick)
                self.stats.ticks_generated += 1

        return ticks

    def _send_event_to_kafka(self, event: EconomicEvent):
        """Send event to Kafka topic"""
        if not self.kafka_producer:
            return

        topic = self.config['kafka']['topics']['events']
        message = json.dumps(event.to_dict()).encode('utf-8')

        try:
            # confluent-kafka uses produce() not send()
            self.kafka_producer.produce(topic, value=message)
            self.kafka_producer.poll(0)  # Trigger any callbacks
            self.stats.kafka_messages_sent += 1
        except Exception as e:
            logger.error("kafka_send_error", error=str(e), event_id=str(event.event_id))
            self.stats.kafka_errors += 1

    def _send_ticks_to_kafka(self, ticks: List[FXTick]):
        """Send ticks to Kafka topic (partitioned by currency_pair)"""
        if not self.kafka_producer:
            return

        topic = self.config['kafka']['topics']['ticks']

        for tick in ticks:
            message = json.dumps(tick.to_dict()).encode('utf-8')
            key = tick.currency_pair.encode('utf-8')

            try:
                # confluent-kafka uses produce() not send()
                self.kafka_producer.produce(topic, value=message, key=key)
                self.stats.kafka_messages_sent += 1
            except Exception as e:
                logger.error("kafka_send_error", error=str(e), tick_id=str(tick.tick_id))
                self.stats.kafka_errors += 1

        # Poll to trigger delivery callbacks and send buffered messages
        self.kafka_producer.poll(0)

    def _write_ticks_to_parquet(self, ticks: List[FXTick]):
        """Buffer ticks and write to Parquet files when buffer is full"""
        if not self.parquet_enabled:
            return

        # Add to buffer
        for tick in ticks:
            self.parquet_buffer.append(tick.to_dict())

        # Write if buffer is full
        if len(self.parquet_buffer) >= self.parquet_buffer_size:
            self._flush_parquet_buffer()

    def _flush_parquet_buffer(self):
        """Write buffered ticks to Parquet file"""
        if not self.parquet_buffer:
            return

        # Group by date/hour for partitioning
        df = pd.DataFrame(self.parquet_buffer)
        df['transaction_timestamp'] = pd.to_datetime(df['transaction_timestamp'])

        # Partition by date
        df['date'] = df['transaction_timestamp'].dt.date
        df['hour'] = df['transaction_timestamp'].dt.hour

        for (date, hour), group in df.groupby(['date', 'hour']):
            # Create directory structure
            output_dir = self.parquet_base_path / str(date)
            output_dir.mkdir(parents=True, exist_ok=True)

            output_file = output_dir / f"{hour:02d}.parquet"

            # Write or append
            group_clean = group.drop(['date', 'hour'], axis=1)

            if output_file.exists():
                # Append to existing file
                existing_df = pd.read_parquet(output_file)
                combined_df = pd.concat([existing_df, group_clean], ignore_index=True)
                combined_df.to_parquet(output_file, index=False)
            else:
                # Write new file
                group_clean.to_parquet(output_file, index=False)

            self.stats.parquet_files_written += 1
            self.stats.parquet_rows_written += len(group_clean)

        logger.info(
            "parquet_written",
            rows=len(self.parquet_buffer),
            files=self.stats.parquet_files_written,
        )

        # Clear buffer
        self.parquet_buffer = []

    def save_checkpoint(self):
        """Save generator state to checkpoint file"""
        state = GeneratorState(
            checkpoint_timestamp=datetime.utcnow(),
            simulation_timestamp=self.simulation_time,
            currency_pair_prices=self.price_simulator.get_state(),
            active_events=[e.event_id for e in self.active_events],
            ticks_generated=self.stats.ticks_generated,
            events_generated=self.stats.events_generated,
        )

        # Create checkpoint directory
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        # Write checkpoint
        with open(self.checkpoint_path, 'w') as f:
            json.dump(state.to_dict(), f, indent=2)

        logger.info(
            "checkpoint_saved",
            ticks=state.ticks_generated,
            events=state.events_generated,
            sim_time=state.simulation_timestamp.isoformat(),
        )

    def load_checkpoint(self) -> bool:
        """
        Load generator state from checkpoint file

        Returns:
            True if checkpoint loaded successfully
        """
        if not self.checkpoint_path.exists():
            logger.info("no_checkpoint_found")
            return False

        try:
            with open(self.checkpoint_path, 'r') as f:
                data = json.load(f)

            state = GeneratorState.from_dict(data)

            # Restore state
            self.simulation_time = state.simulation_timestamp
            self.price_simulator.set_state(state.currency_pair_prices)
            self.stats.ticks_generated = state.ticks_generated
            self.stats.events_generated = state.events_generated

            logger.info(
                "checkpoint_loaded",
                ticks=state.ticks_generated,
                events=state.events_generated,
                sim_time=state.simulation_timestamp.isoformat(),
            )

            return True

        except Exception as e:
            logger.error("checkpoint_load_error", error=str(e))
            return False

    def run(self, duration_seconds: Optional[float] = None):
        """
        Run the tick generator

        Args:
            duration_seconds: How long to run (real time). None = run forever
        """
        logger.info("generator_starting", duration=duration_seconds)

        end_time = None
        if duration_seconds:
            end_time = datetime.utcnow() + timedelta(seconds=duration_seconds)

        try:
            while True:
                loop_start = time.time()

                # Generate batch of ticks
                dt = 1.0 / self.tick_rate  # Time step for target tick rate
                ticks = self.generate_batch(dt)

                # Output ticks
                if self.kafka_enabled and self.kafka_producer:
                    self._send_ticks_to_kafka(ticks)

                if self.parquet_enabled:
                    self._write_ticks_to_parquet(ticks)

                # Update statistics
                self.stats.current_time = datetime.utcnow()
                self.stats.simulation_time = self.simulation_time
                self.stats.update_ticks_per_second()

                # Checkpoint if needed
                if (datetime.utcnow() - self.last_checkpoint_time).total_seconds() >= self.checkpoint_interval:
                    self.save_checkpoint()
                    self.last_checkpoint_time = datetime.utcnow()

                # Log stats periodically
                if self.stats.ticks_generated % 1000 == 0:
                    logger.info(
                        "generator_stats",
                        ticks_generated=self.stats.ticks_generated,
                        events_generated=self.stats.events_generated,
                        active_events=self.stats.active_events,
                        ticks_per_second=round(self.stats.ticks_per_second, 2),
                        sim_time=self.simulation_time.isoformat(),
                    )

                # Check if should stop
                if end_time and datetime.utcnow() >= end_time:
                    logger.info("generator_stopping", reason="duration_reached")
                    break

                # Sleep to maintain tick rate
                loop_duration = time.time() - loop_start
                sleep_time = dt - loop_duration
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            logger.info("generator_stopping", reason="user_interrupt")

        finally:
            # Final checkpoint and flush
            self._flush_parquet_buffer()
            self.save_checkpoint()

            # Flush Kafka producer to ensure all messages are sent
            if self.kafka_producer:
                logger.info("flushing_kafka_producer")
                self.kafka_producer.flush()

            logger.info(
                "generator_stopped",
                total_ticks=self.stats.ticks_generated,
                total_events=self.stats.events_generated,
                kafka_messages=self.stats.kafka_messages_sent,
                parquet_rows=self.stats.parquet_rows_written,
            )
