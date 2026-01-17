"""
Stock Pricing Engine for Discord Stock Exchange.

Calculates stock prices based on user activity metrics, streaks, and market demand.
"""

from datetime import date, datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass


@dataclass
class ActivityMetrics:
    """User activity data for a single day."""
    messages: int = 0
    reactions_received: int = 0
    unique_reactors: int = 0
    voice_minutes: int = 0
    replies_received: int = 0
    mentions_received: int = 0


@dataclass 
class DemandData:
    """Market demand data for a stock."""
    buy_orders_24h: int = 0
    sell_orders_24h: int = 0
    total_shares: int = 1000


class PricingEngine:
    """
    Calculates stock prices using the formula:
    
    Price = Base × Activity Multiplier × Streak Bonus × Demand Modifier
    """
    
    # Configuration constants
    BASE_PRICE = 100.0
    
    # Activity multipliers (per unit)
    MESSAGE_MULTIPLIER = 0.005          # +0.5% per message
    MESSAGE_DIMINISH_THRESHOLD = 50     # Diminishing returns after this
    REACTION_MULTIPLIER = 0.02          # +2% per unique reactor
    VOICE_MULTIPLIER = 0.001            # +1% per 10 minutes (0.1% per minute)
    REPLY_MULTIPLIER = 0.03             # +3% per reply received
    MENTION_MULTIPLIER = 0.01           # +1% per mention received
    
    # Streak bonuses
    STREAK_BONUS_PER_DAY = 0.1          # +10% per consecutive day
    MAX_STREAK_BONUS = 2.0              # Cap at 2x
    
    # Demand modifiers
    DEMAND_IMPACT = 0.1                 # How much buy/sell ratio affects price
    
    # Decay
    INACTIVITY_DECAY_PER_DAY = 0.05     # -5% per day inactive
    
    def calculate_activity_multiplier(self, metrics: ActivityMetrics) -> float:
        """
        Calculate the activity-based price multiplier.
        Returns a multiplier >= 1.0
        """
        multiplier = 1.0
        
        # Messages with diminishing returns
        if metrics.messages <= self.MESSAGE_DIMINISH_THRESHOLD:
            multiplier += metrics.messages * self.MESSAGE_MULTIPLIER
        else:
            # Full value for first 50, then 50% effectiveness
            base_value = self.MESSAGE_DIMINISH_THRESHOLD * self.MESSAGE_MULTIPLIER
            excess = metrics.messages - self.MESSAGE_DIMINISH_THRESHOLD
            diminished = excess * self.MESSAGE_MULTIPLIER * 0.5
            multiplier += base_value + diminished
        
        # Reactions (quality engagement)
        multiplier += metrics.unique_reactors * self.REACTION_MULTIPLIER
        
        # Voice time
        multiplier += metrics.voice_minutes * self.VOICE_MULTIPLIER
        
        # Replies (people responding to you = influence)
        multiplier += metrics.replies_received * self.REPLY_MULTIPLIER
        
        # Mentions
        multiplier += metrics.mentions_received * self.MENTION_MULTIPLIER
        
        return max(1.0, multiplier)
    
    def calculate_streak_bonus(self, consecutive_days: int) -> float:
        """
        Calculate streak bonus multiplier.
        Returns multiplier between 1.0 and MAX_STREAK_BONUS.
        """
        bonus = 1.0 + (consecutive_days * self.STREAK_BONUS_PER_DAY)
        return min(bonus, self.MAX_STREAK_BONUS)
    
    def calculate_demand_modifier(self, demand: DemandData) -> float:
        """
        Calculate market demand modifier based on buy/sell ratio.
        Returns modifier around 1.0 (+/- based on demand).
        """
        if demand.total_shares == 0:
            return 1.0
        
        net_demand = demand.buy_orders_24h - demand.sell_orders_24h
        demand_ratio = net_demand / demand.total_shares
        
        # Clamp to reasonable bounds
        modifier = 1.0 + (demand_ratio * self.DEMAND_IMPACT)
        return max(0.5, min(1.5, modifier))  # Between 0.5x and 1.5x
    
    def calculate_inactivity_decay(self, days_inactive: int, current_price: float) -> float:
        """
        Calculate price after inactivity decay.
        Returns decayed price (never below 10.0)
        """
        if days_inactive <= 0:
            return current_price
        
        decay_multiplier = (1 - self.INACTIVITY_DECAY_PER_DAY) ** days_inactive
        new_price = current_price * decay_multiplier
        
        return max(10.0, new_price)  # Penny stock floor
    
    def calculate_price(
        self,
        base_price: float,
        metrics: ActivityMetrics,
        consecutive_days: int = 0,
        demand: Optional[DemandData] = None,
        days_inactive: int = 0
    ) -> float:
        """
        Calculate the full stock price.
        
        Price = Base × Activity × Streak × Demand - Decay
        """
        if demand is None:
            demand = DemandData()
        
        # Start with base
        price = base_price
        
        # Apply activity multiplier
        activity_mult = self.calculate_activity_multiplier(metrics)
        price *= activity_mult
        
        # Apply streak bonus
        streak_mult = self.calculate_streak_bonus(consecutive_days)
        price *= streak_mult
        
        # Apply demand modifier
        demand_mult = self.calculate_demand_modifier(demand)
        price *= demand_mult
        
        # Apply inactivity decay if needed
        if days_inactive > 0:
            decay_mult = (1 - self.INACTIVITY_DECAY_PER_DAY) ** days_inactive
            price *= decay_mult
        
        # Floor at penny stock level
        return max(10.0, round(price, 2))
    
    def calculate_trend(self, current: float, previous: float) -> str:
        """Return trend indicator emoji based on price change."""
        if previous == 0:
            return "🆕"
        
        change_pct = ((current - previous) / previous) * 100
        
        if change_pct >= 10:
            return "🚀"  # Moon
        elif change_pct >= 5:
            return "📈"  # Strong up
        elif change_pct >= 1:
            return "↗️"  # Up
        elif change_pct > -1:
            return "➡️"  # Flat
        elif change_pct > -5:
            return "↘️"  # Down
        elif change_pct > -10:
            return "📉"  # Strong down
        else:
            return "💀"  # Crash
    
    def format_price(self, price: float) -> str:
        """Format price for display."""
        if price >= 1000:
            return f"${price:,.0f}"
        elif price >= 100:
            return f"${price:.1f}"
        else:
            return f"${price:.2f}"
    
    def format_change(self, current: float, previous: float) -> str:
        """Format price change with color indicator."""
        if previous == 0:
            return "+0.00%"
        
        change = current - previous
        change_pct = (change / previous) * 100
        
        if change >= 0:
            return f"+{change_pct:.2f}%"
        else:
            return f"{change_pct:.2f}%"


# Singleton
pricing_engine = PricingEngine()
