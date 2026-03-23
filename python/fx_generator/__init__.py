"""
MarsFX Data Generator
Generates realistic interplanetary FX tick data with economic events
"""

__version__ = "1.0.0"

from .event_generator import BusinessHoursModulator, EventGenerator
from .models import (
    CurrencyPair,
    EconomicEvent,
    EventType,
    ExchangeLocation,
    FXTick,
    GeneratorState,
    GeneratorStats,
    TraderType,
)
from .price_simulator import PriceSimulator
from .tick_generator import TickGenerator

__all__ = [
    "TickGenerator",
    "PriceSimulator",
    "EventGenerator",
    "BusinessHoursModulator",
    "FXTick",
    "EconomicEvent",
    "CurrencyPair",
    "GeneratorState",
    "GeneratorStats",
    "EventType",
    "ExchangeLocation",
    "TraderType",
]
