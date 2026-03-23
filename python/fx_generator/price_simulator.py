"""
Price simulation engine using Geometric Brownian Motion (GBM)
Includes correlation, event impact, and business hour adjustments
"""
import random
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import numpy as np
from scipy import stats

from .models import CurrencyPair, EconomicEvent, EventType


class PriceSimulator:
    """
    Simulates realistic FX price movements using Geometric Brownian Motion
    with correlation between currency pairs and event impacts
    """

    def __init__(
        self,
        currency_pairs: List[CurrencyPair],
        time_acceleration: float = 1.0,
        random_seed: Optional[int] = None,
    ):
        """
        Initialize price simulator

        Args:
            currency_pairs: List of currency pair configurations
            time_acceleration: Time acceleration factor (60 = 1 hour in 1 minute)
            random_seed: Random seed for reproducibility
        """
        self.currency_pairs = {cp.name: cp for cp in currency_pairs}
        self.time_acceleration = time_acceleration

        # Initialize random state
        if random_seed is not None:
            np.random.seed(random_seed)
            random.seed(random_seed)

        # Current prices (initialize to base prices)
        self.current_prices = {cp.name: cp.base_price for cp in currency_pairs}

        # Price history for correlation calculation
        self.price_history: Dict[str, List[float]] = {
            cp.name: [cp.base_price] for cp in currency_pairs
        }

        # Build correlation matrix
        self.correlation_matrix = self._build_correlation_matrix()

        # Active events affecting prices
        self.active_events: List[EconomicEvent] = []

    def _build_correlation_matrix(self) -> np.ndarray:
        """Build correlation matrix from pair configurations"""
        pairs = list(self.currency_pairs.keys())
        n = len(pairs)
        corr_matrix = np.eye(n)  # Start with identity matrix

        for i, pair1 in enumerate(pairs):
            cp1 = self.currency_pairs[pair1]
            for j, pair2 in enumerate(pairs):
                if i != j and pair2 in cp1.correlation_with:
                    corr_matrix[i, j] = cp1.correlation_with[pair2]
                    corr_matrix[j, i] = cp1.correlation_with[pair2]  # Symmetric

        # Ensure matrix is positive semi-definite
        eigenvalues = np.linalg.eigvals(corr_matrix)
        if np.any(eigenvalues < 0):
            # Adjust to nearest positive semi-definite matrix
            min_eigenvalue = np.min(eigenvalues)
            corr_matrix += (abs(min_eigenvalue) + 0.01) * np.eye(n)

        return corr_matrix

    def generate_correlated_returns(
        self,
        dt: float,
        volume_multiplier: float = 1.0,
    ) -> Dict[str, float]:
        """
        Generate correlated returns for all currency pairs

        Args:
            dt: Time step in years (e.g., 1/252/24 for 1 hour)
            volume_multiplier: Multiplier for volatility based on volume

        Returns:
            Dictionary of returns for each currency pair
        """
        pairs = list(self.currency_pairs.keys())
        n = len(pairs)

        # Generate independent normal random variables
        independent_normals = np.random.standard_normal(n)

        # Apply Cholesky decomposition to correlate them
        try:
            L = np.linalg.cholesky(self.correlation_matrix)
            correlated_normals = L @ independent_normals
        except np.linalg.LinAlgError:
            # If Cholesky fails, use uncorrelated returns
            correlated_normals = independent_normals

        # Calculate returns for each pair
        returns = {}
        for i, pair in enumerate(pairs):
            cp = self.currency_pairs[pair]

            # Adjust volatility by volume and events
            volatility = cp.volatility * volume_multiplier
            volatility = self._apply_event_volatility(pair, volatility)

            # Geometric Brownian Motion: dS = mu * S * dt + sigma * S * dW
            # For FX, assume drift (mu) is 0 (no arbitrage)
            drift = 0.0
            diffusion = volatility * np.sqrt(dt) * correlated_normals[i]

            returns[pair] = drift * dt + diffusion

        return returns

    def _apply_event_volatility(self, pair: str, base_volatility: float) -> float:
        """Apply event-driven volatility multipliers"""
        volatility = base_volatility

        cp = self.currency_pairs[pair]
        base_currency = cp.base_currency
        quote_currency = cp.quote_currency

        for event in self.active_events:
            # Check if event affects this pair
            if event.affects_currency(base_currency) or event.affects_currency(quote_currency):
                volatility *= event.volatility_multiplier

        return volatility

    def apply_price_shock(self, pair: str, event: EconomicEvent):
        """Apply sudden price shock from event"""
        if event.price_shock_percent is None:
            return

        cp = self.currency_pairs[pair]
        if not (
            event.affects_currency(cp.base_currency)
            or event.affects_currency(cp.quote_currency)
        ):
            return

        # Determine direction (random for most events)
        direction = np.random.choice([-1, 1])

        # Apply shock
        shock_magnitude = event.price_shock_percent / 100.0
        self.current_prices[pair] *= (1 + direction * shock_magnitude)

    def update_prices(
        self,
        dt_real_seconds: float,
        volume_multiplier: float = 1.0,
    ) -> Dict[str, float]:
        """
        Update all prices using GBM with correlation

        Args:
            dt_real_seconds: Real time step in seconds
            volume_multiplier: Volume-based volatility adjustment

        Returns:
            Dictionary of new prices
        """
        # Convert real time to simulated time
        dt_sim_seconds = dt_real_seconds * self.time_acceleration

        # Convert to years (for annualized volatility)
        # Assume 252 trading days, 24 hours/day
        dt_years = dt_sim_seconds / (252 * 24 * 3600)

        # Generate correlated returns
        returns = self.generate_correlated_returns(dt_years, volume_multiplier)

        # Update prices
        for pair, ret in returns.items():
            self.current_prices[pair] *= (1 + ret)

            # Add to history (keep last 100 prices for stats)
            self.price_history[pair].append(self.current_prices[pair])
            if len(self.price_history[pair]) > 100:
                self.price_history[pair].pop(0)

        return self.current_prices.copy()

    def get_bid_ask_spread(
        self,
        pair: str,
        base_spread_bps: Optional[float] = None,
    ) -> tuple[Decimal, Decimal, Decimal]:
        """
        Calculate bid, ask, and mid prices with realistic spreads

        Args:
            pair: Currency pair name
            base_spread_bps: Base spread in basis points (uses config if None)

        Returns:
            Tuple of (bid_price, ask_price, mid_price)
        """
        cp = self.currency_pairs[pair]
        mid_price = self.current_prices[pair]

        # Determine spread
        if base_spread_bps is None:
            base_spread_bps = random.uniform(cp.min_spread_bps, cp.max_spread_bps)

        # Apply event-driven spread multipliers
        spread_multiplier = 1.0
        for event in self.active_events:
            if event.affects_currency(cp.base_currency) or event.affects_currency(
                cp.quote_currency
            ):
                spread_multiplier *= event.spread_multiplier

        spread_bps = base_spread_bps * spread_multiplier

        # Calculate bid/ask
        spread_fraction = spread_bps / 10000.0  # Convert bps to fraction
        half_spread = mid_price * spread_fraction / 2

        bid_price = Decimal(str(mid_price - half_spread)).quantize(Decimal('0.00000001'))
        ask_price = Decimal(str(mid_price + half_spread)).quantize(Decimal('0.00000001'))
        mid_price_decimal = Decimal(str(mid_price)).quantize(Decimal('0.00000001'))

        return bid_price, ask_price, mid_price_decimal

    def get_trade_price(
        self,
        pair: str,
        trader_type: str,
    ) -> Decimal:
        """
        Get trade execution price (between bid and ask)

        Args:
            pair: Currency pair name
            trader_type: Type of trader (affects price improvement)

        Returns:
            Trade price
        """
        bid, ask, mid = self.get_bid_ask_spread(pair)

        # Institutional traders get better prices (closer to mid)
        if trader_type == "institutional":
            # 80% chance of mid price
            if random.random() < 0.8:
                return mid
            # Otherwise random between bid and ask
            trade_price = random.uniform(float(bid), float(ask))
        elif trader_type == "government":
            # Always get mid price
            return mid
        else:
            # Retail and mining corp get prices between bid and ask
            trade_price = random.uniform(float(bid), float(ask))

        return Decimal(str(trade_price)).quantize(Decimal('0.00000001'))

    def get_trade_volume(
        self,
        pair: str,
        trader_type: str,
        volume_multiplier: float = 1.0,
    ) -> Decimal:
        """
        Generate realistic trade volume

        Args:
            pair: Currency pair name
            trader_type: Type of trader
            volume_multiplier: Event-driven volume adjustment

        Returns:
            Trade volume
        """
        cp = self.currency_pairs[pair]
        base_volume = cp.typical_trade_size

        # Trader type multipliers (from config in real implementation)
        type_multipliers = {
            "institutional": random.uniform(2.0, 5.0),
            "retail": random.uniform(0.1, 0.5),
            "mining_corp": random.uniform(3.0, 8.0),
            "government": random.uniform(5.0, 10.0),
        }

        type_mult = type_multipliers.get(trader_type, 1.0)

        # Apply event volume multipliers
        event_mult = 1.0
        for event in self.active_events:
            if event.affects_currency(cp.base_currency) or event.affects_currency(
                cp.quote_currency
            ):
                event_mult *= event.volume_multiplier

        total_volume = base_volume * type_mult * volume_multiplier * event_mult

        # Add some randomness
        total_volume *= random.uniform(0.8, 1.2)

        return Decimal(str(total_volume)).quantize(Decimal('0.00000001'))

    def add_event(self, event: EconomicEvent):
        """Add an active economic event"""
        self.active_events.append(event)

        # Apply initial price shock if applicable
        for pair in self.currency_pairs.keys():
            self.apply_price_shock(pair, event)

    def remove_event(self, event_id: str):
        """Remove an expired economic event"""
        self.active_events = [e for e in self.active_events if str(e.event_id) != event_id]

    def update_active_events(self, current_time: datetime):
        """Update list of active events based on current time"""
        self.active_events = [e for e in self.active_events if e.is_active(current_time)]

    def get_current_volatility(self, pair: str) -> float:
        """Calculate current realized volatility from price history"""
        if len(self.price_history[pair]) < 2:
            return self.currency_pairs[pair].volatility

        prices = np.array(self.price_history[pair])
        returns = np.diff(np.log(prices))
        return float(np.std(returns) * np.sqrt(252 * 24))  # Annualized

    def get_state(self) -> Dict[str, float]:
        """Get current state for checkpointing"""
        return self.current_prices.copy()

    def set_state(self, prices: Dict[str, float]):
        """Restore state from checkpoint"""
        self.current_prices = prices.copy()
        for pair, price in prices.items():
            self.price_history[pair] = [price]
