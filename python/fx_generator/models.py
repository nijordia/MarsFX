"""
Data models for MarsFX tick generator
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator


class ExchangeLocation(str, Enum):
    """Exchange locations in the solar system"""
    EARTH_FX_HUB = "Earth_FX_Hub"
    MARS_CENTRAL_EXCHANGE = "Mars_Central_Exchange"
    LUNAR_TRADING_POST = "Lunar_Trading_Post"
    ASTEROID_BELT_HUB = "Asteroid_Belt_Hub"


class TraderType(str, Enum):
    """Types of market participants"""
    INSTITUTIONAL = "institutional"
    RETAIL = "retail"
    MINING_CORP = "mining_corp"
    GOVERNMENT = "government"


class EventType(str, Enum):
    """Economic event types affecting markets"""
    SOLAR_STORM = "SOLAR_STORM"
    TRADE_TARIFF = "TRADE_TARIFF"
    OXYGEN_CRISIS = "OXYGEN_CRISIS"
    MINING_STRIKE = "MINING_STRIKE"
    POLICY_CHANGE = "POLICY_CHANGE"
    SUPPLY_SHOCK = "SUPPLY_SHOCK"


class CurrencyPair(BaseModel):
    """Currency pair configuration"""
    name: str
    base_currency: str
    quote_currency: str
    base_price: float
    volatility: float
    min_spread_bps: int
    max_spread_bps: int
    typical_trade_size: float
    primary_exchange: str
    correlation_with: dict[str, float] = Field(default_factory=dict)

    @validator('name')
    def validate_name_format(cls, v):
        """Ensure name is in BASE/QUOTE format"""
        if '/' not in v:
            raise ValueError(f"Currency pair name must be in BASE/QUOTE format, got: {v}")
        return v


class FXTick(BaseModel):
    """Individual FX tick data point"""
    tick_id: UUID = Field(default_factory=uuid4)
    transaction_timestamp: datetime
    currency_pair: str
    bid_price: Decimal = Field(decimal_places=8)
    ask_price: Decimal = Field(decimal_places=8)
    mid_price: Decimal = Field(decimal_places=8)
    spread_bps: float
    trade_price: Decimal = Field(decimal_places=8)  # Actual execution price
    volume: Decimal = Field(decimal_places=8)
    exchange_location: ExchangeLocation
    trader_type: TraderType
    event_time: datetime  # Kafka event time
    processing_time: Optional[datetime] = None  # Set by processor

    class Config:
        json_encoders = {
            UUID: str,
            Decimal: str,
            datetime: lambda v: v.isoformat(),
        }

    @validator('spread_bps', always=True)
    def calculate_spread(cls, v, values):
        """Calculate spread in basis points"""
        if 'bid_price' in values and 'ask_price' in values and 'mid_price' in values:
            bid = values['bid_price']
            ask = values['ask_price']
            mid = values['mid_price']
            if mid > 0:
                spread = ((ask - bid) / mid) * 10000  # Convert to bps
                return float(spread)
        return v

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'tick_id': str(self.tick_id),
            'transaction_timestamp': self.transaction_timestamp.isoformat(),
            'currency_pair': self.currency_pair,
            'bid_price': str(self.bid_price),
            'ask_price': str(self.ask_price),
            'mid_price': str(self.mid_price),
            'spread_bps': self.spread_bps,
            'trade_price': str(self.trade_price),
            'volume': str(self.volume),
            'exchange_location': self.exchange_location.value,
            'trader_type': self.trader_type.value,
            'event_time': self.event_time.isoformat(),
            'processing_time': self.processing_time.isoformat() if self.processing_time else None,
        }


class EconomicEvent(BaseModel):
    """Economic event affecting market conditions"""
    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    event_timestamp: datetime
    start_timestamp: datetime
    end_timestamp: datetime
    duration_minutes: int
    severity: int = Field(ge=1, le=5)  # 1-5 scale
    affected_currencies: List[str]
    description: str
    expected_impact: str

    # Event effects
    spread_multiplier: float = Field(default=1.0)
    volatility_multiplier: float = Field(default=1.0)
    volume_multiplier: float = Field(default=1.0)
    price_shock_percent: Optional[float] = None

    class Config:
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat(),
        }

    @validator('duration_minutes', always=True)
    def calculate_duration(cls, v, values):
        """Calculate duration from start and end timestamps"""
        if 'start_timestamp' in values and 'end_timestamp' in values:
            duration = (values['end_timestamp'] - values['start_timestamp']).total_seconds() / 60
            return int(duration)
        return v

    def is_active(self, current_time: datetime) -> bool:
        """Check if event is currently active"""
        return self.start_timestamp <= current_time <= self.end_timestamp

    def affects_currency(self, currency: str) -> bool:
        """Check if event affects a specific currency"""
        return currency in self.affected_currencies

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'event_id': str(self.event_id),
            'event_type': self.event_type.value,
            'event_timestamp': self.event_timestamp.isoformat(),
            'start_timestamp': self.start_timestamp.isoformat(),
            'end_timestamp': self.end_timestamp.isoformat(),
            'duration_minutes': self.duration_minutes,
            'severity': self.severity,
            'affected_currencies': self.affected_currencies,
            'description': self.description,
            'expected_impact': self.expected_impact,
            'spread_multiplier': self.spread_multiplier,
            'volatility_multiplier': self.volatility_multiplier,
            'volume_multiplier': self.volume_multiplier,
            'price_shock_percent': self.price_shock_percent,
        }


class GeneratorState(BaseModel):
    """Checkpoint state for resumable generation"""
    checkpoint_id: UUID = Field(default_factory=uuid4)
    checkpoint_timestamp: datetime
    simulation_timestamp: datetime
    currency_pair_prices: dict[str, float]  # Current prices for each pair
    active_events: List[UUID] = Field(default_factory=list)
    ticks_generated: int = 0
    events_generated: int = 0
    random_state: Optional[dict] = None  # Serialized numpy random state

    class Config:
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat(),
        }

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization"""
        return {
            'checkpoint_id': str(self.checkpoint_id),
            'checkpoint_timestamp': self.checkpoint_timestamp.isoformat(),
            'simulation_timestamp': self.simulation_timestamp.isoformat(),
            'currency_pair_prices': self.currency_pair_prices,
            'active_events': [str(e) for e in self.active_events],
            'ticks_generated': self.ticks_generated,
            'events_generated': self.events_generated,
            'random_state': self.random_state,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GeneratorState":
        """Create from dictionary"""
        data = data.copy()
        data['checkpoint_timestamp'] = datetime.fromisoformat(data['checkpoint_timestamp'])
        data['simulation_timestamp'] = datetime.fromisoformat(data['simulation_timestamp'])
        data['active_events'] = [UUID(e) for e in data.get('active_events', [])]
        return cls(**data)


class GeneratorStats(BaseModel):
    """Runtime statistics for monitoring"""
    start_time: datetime
    current_time: datetime
    simulation_time: datetime
    ticks_generated: int = 0
    events_generated: int = 0
    active_events: int = 0
    ticks_per_second: float = 0.0
    time_acceleration_factor: float = 1.0

    # Output stats
    kafka_messages_sent: int = 0
    kafka_errors: int = 0
    parquet_files_written: int = 0
    parquet_rows_written: int = 0

    # Error tracking
    errors: List[str] = Field(default_factory=list)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    def elapsed_real_seconds(self) -> float:
        """Real elapsed time in seconds"""
        # Handle both timezone-aware and timezone-naive datetimes
        start = self.start_time.replace(tzinfo=None) if self.start_time.tzinfo else self.start_time
        current = self.current_time.replace(tzinfo=None) if self.current_time.tzinfo else self.current_time
        return (current - start).total_seconds()

    def elapsed_simulation_seconds(self) -> float:
        """Simulated elapsed time in seconds"""
        # Handle both timezone-aware and timezone-naive datetimes
        start = self.start_time.replace(tzinfo=None) if self.start_time.tzinfo else self.start_time
        sim = self.simulation_time.replace(tzinfo=None) if self.simulation_time.tzinfo else self.simulation_time
        return (sim - start).total_seconds()

    def update_ticks_per_second(self):
        """Calculate current tick generation rate"""
        elapsed = self.elapsed_real_seconds()
        if elapsed > 0:
            self.ticks_per_second = self.ticks_generated / elapsed
