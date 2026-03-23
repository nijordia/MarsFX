"""
Economic event generator for MarsFX
Creates realistic market events with impacts on currency prices
"""
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import uuid4

from .models import EconomicEvent, EventType


class EventGenerator:
    """Generates economic events that affect FX markets"""

    def __init__(
        self,
        event_config: Dict,
        event_probability_per_minute: float = 0.05,
        random_seed: Optional[int] = None,
    ):
        """
        Initialize event generator

        Args:
            event_config: Event configuration from YAML
            event_probability_per_minute: Probability of event per simulated minute
            random_seed: Random seed for reproducibility
        """
        self.event_config = event_config
        self.event_probability = event_probability_per_minute

        if random_seed is not None:
            random.seed(random_seed)

        # Build weighted event types
        self.event_types = []
        self.event_weights = []

        for event_def in event_config:
            self.event_types.append(event_def['type'])
            self.event_weights.append(event_def['probability_weight'])

        # Normalize weights
        total_weight = sum(self.event_weights)
        self.event_weights = [w / total_weight for w in self.event_weights]

        # Event descriptions by type
        self.event_descriptions = {
            "SOLAR_STORM": [
                "Major solar storm warning issued by Earth Space Weather Center",
                "Massive coronal mass ejection detected heading toward Mars",
                "Solar radiation storm disrupts Mars-Asteroid communications",
                "Severe geomagnetic storm impacts space-based trading systems",
            ],
            "TRADE_TARIFF": [
                "Earth Council announces new import tariffs on Mars goods",
                "Lunar government implements reciprocal trade barriers",
                "Mars Assembly votes to increase tariffs on Earth products",
                "Trade agreement renegotiation causes market uncertainty",
            ],
            "OXYGEN_CRISIS": [
                "Critical oxygen production failure at Mars Colony Alpha",
                "Life support system malfunction at Olympus Mons base",
                "Mars water ice mining disrupted by equipment failure",
                "Emergency oxygen shipment from Earth delayed",
            ],
            "MINING_STRIKE": [
                "Asteroid miners union calls for work stoppage over safety concerns",
                "Ceres mining operations halt due to labor dispute",
                "Major asteroid mining corp announces temporary shutdown",
                "Vesta mining workers protest working conditions",
            ],
            "POLICY_CHANGE": [
                "Earth Central Bank announces surprise interest rate decision",
                "Lunar Monetary Authority adjusts reserve requirements",
                "Mars Financial Regulator implements new trading rules",
                "Inter-planetary trade policy reform announced",
            ],
            "SUPPLY_SHOCK": [
                "Major water ice discovery on Mars boosts local economy",
                "Rare earth minerals found in new asteroid field",
                "Critical helium-3 shortage affects lunar operations",
                "Unexpected crop failure on Mars requires Earth imports",
            ],
        }

    def should_generate_event(self, dt_simulated_minutes: float) -> bool:
        """
        Determine if an event should be generated

        Args:
            dt_simulated_minutes: Time step in simulated minutes

        Returns:
            True if event should be generated
        """
        # Probability scales with time step
        probability = self.event_probability * dt_simulated_minutes
        return random.random() < probability

    def generate_event(self, current_time: datetime) -> Optional[EconomicEvent]:
        """
        Generate a new economic event

        Args:
            current_time: Current simulation timestamp

        Returns:
            New EconomicEvent or None
        """
        # Select event type based on weights
        event_type_str = random.choices(self.event_types, weights=self.event_weights)[0]
        event_type = EventType(event_type_str)

        # Get event configuration
        event_def = next(
            (e for e in self.event_config if e['type'] == event_type_str), None
        )
        if not event_def:
            return None

        # Generate duration
        duration_range = event_def['duration_minutes']
        duration_minutes = random.randint(duration_range[0], duration_range[1])

        # Generate severity
        severity_range = event_def['severity_range']
        severity = random.randint(severity_range[0], severity_range[1])

        # Calculate timestamps
        start_timestamp = current_time
        end_timestamp = current_time + timedelta(minutes=duration_minutes)

        # Get affected currencies
        affected_currencies = event_def['effects']['affected_currencies']

        # Generate event effects based on severity
        effects = event_def['effects']

        # Spread multiplier (optional)
        if 'spread_multiplier' in effects:
            spread_range = effects['spread_multiplier']
            spread_multiplier = random.uniform(spread_range[0], spread_range[1])
            # Scale by severity
            spread_multiplier = 1.0 + (spread_multiplier - 1.0) * (severity / 5.0)
        else:
            spread_multiplier = 1.0

        # Volatility multiplier
        vol_range = effects.get('volatility_multiplier', [1.0, 1.0])
        volatility_multiplier = random.uniform(vol_range[0], vol_range[1])
        volatility_multiplier = 1.0 + (volatility_multiplier - 1.0) * (severity / 5.0)

        # Volume multiplier (optional)
        volume_range = effects.get('volume_multiplier', [1.0, 1.0])
        volume_multiplier = random.uniform(volume_range[0], volume_range[1])

        # Price shock (if applicable)
        price_shock = None
        if 'price_shock_percent' in effects:
            shock_range = effects['price_shock_percent']
            price_shock = random.uniform(shock_range[0], shock_range[1])
            price_shock *= (severity / 5.0)  # Scale by severity

        # Generate description
        description = random.choice(self.event_descriptions[event_type_str])

        # Generate expected impact
        impact_descriptions = {
            1: "Minor market disruption expected",
            2: "Moderate volatility anticipated",
            3: "Significant market impact likely",
            4: "Major disruption to trading operations",
            5: "Critical event with severe market consequences",
        }
        expected_impact = impact_descriptions[severity]

        event = EconomicEvent(
            event_id=uuid4(),
            event_type=event_type,
            event_timestamp=current_time,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            duration_minutes=duration_minutes,
            severity=severity,
            affected_currencies=affected_currencies,
            description=description,
            expected_impact=expected_impact,
            spread_multiplier=spread_multiplier,
            volatility_multiplier=volatility_multiplier,
            volume_multiplier=volume_multiplier,
            price_shock_percent=price_shock,
        )

        return event

    def get_active_events(
        self,
        events: List[EconomicEvent],
        current_time: datetime,
    ) -> List[EconomicEvent]:
        """
        Filter events to get currently active ones

        Args:
            events: List of all events
            current_time: Current simulation time

        Returns:
            List of active events
        """
        return [e for e in events if e.is_active(current_time)]


class BusinessHoursModulator:
    """Modulates trading activity based on business hours"""

    def __init__(self, volume_by_hour: Dict[int, float]):
        """
        Initialize business hours modulator

        Args:
            volume_by_hour: Volume multipliers by UTC hour (0-23)
        """
        self.volume_by_hour = volume_by_hour

    def get_volume_multiplier(self, current_time: datetime) -> float:
        """
        Get volume multiplier for current time

        Args:
            current_time: Current timestamp

        Returns:
            Volume multiplier (0.2 - 1.5)
        """
        hour = current_time.hour
        return self.volume_by_hour.get(hour, 1.0)

    def is_peak_hours(self, current_time: datetime) -> bool:
        """Check if current time is peak trading hours"""
        multiplier = self.get_volume_multiplier(current_time)
        return multiplier >= 1.2
