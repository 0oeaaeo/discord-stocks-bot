"""
Async database manager for Discord Stock Exchange.
Handles all database operations with connection pooling and transaction safety.
"""

import aiosqlite
import asyncio
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple

DB_PATH = Path(__file__).parent / "dsx.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class Database:
    """Async SQLite database manager."""
    
    def __init__(self):
        self._connection: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()
    
    async def connect(self) -> None:
        """Initialize database connection and create tables."""
        self._connection = await aiosqlite.connect(DB_PATH)
        self._connection.row_factory = aiosqlite.Row
        
        # Enable foreign keys
        await self._connection.execute("PRAGMA foreign_keys = ON")
        
        # Run schema
        schema = SCHEMA_PATH.read_text()
        await self._connection.executescript(schema)
        await self._connection.commit()
        print(f"[DB] Connected to {DB_PATH}")
    
    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            print("[DB] Connection closed")
    
    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._connection:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    # ==================== User Operations ====================
    
    async def get_or_create_user(self, user_id: int, username: str, 
                                  display_name: str = None, avatar_url: str = None) -> Dict:
        """Get existing user or create new one with starting capital."""
        async with self._lock:
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                return dict(row)
            
            # Create new user
            await self.conn.execute("""
                INSERT INTO users (user_id, username, display_name, avatar_url)
                VALUES (?, ?, ?, ?)
            """, (user_id, username, display_name, avatar_url))
            
            # Create their stock entry
            await self.conn.execute("""
                INSERT INTO stocks (user_id) VALUES (?)
            """, (user_id,))
            
            # Create their wallet with starting capital
            await self.conn.execute("""
                INSERT INTO wallets (user_id) VALUES (?)
            """, (user_id,))
            
            await self.conn.commit()
            
            # Fetch the newly created user to return it
            cursor = await self.conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return dict(row)

    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get user data by ID."""
        cursor = await self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def remove_user_completely(self, user_id: int) -> None:
        """Permanently remove a user and all their shares from the game."""
        async with self._lock:
            # 1. Remove their stock
            await self.conn.execute("DELETE FROM stocks WHERE user_id = ?", (user_id,))
            # 2. Remove their portfolio (shares they own)
            await self.conn.execute("DELETE FROM portfolios WHERE holder_id = ?", (user_id,))
            # 3. Remove them as a stock (shares others own of them)
            await self.conn.execute("DELETE FROM portfolios WHERE stock_id = ?", (user_id,))
            # 4. Remove their wallet
            await self.conn.execute("DELETE FROM wallets WHERE user_id = ?", (user_id,))
            # 5. Remove activity metrics
            await self.conn.execute("DELETE FROM activity_metrics WHERE user_id = ?", (user_id,))
            # 6. Remove user record
            await self.conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            
            await self.conn.commit()

    # ==================== Wallet Operations ====================

    
    async def get_wallet(self, user_id: int) -> Optional[Dict]:
        """Get user's wallet."""
        cursor = await self.conn.execute(
            "SELECT * FROM wallets WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def update_balance(self, user_id: int, amount: float) -> float:
        """Add/subtract from user's balance. Returns new balance."""
        async with self._lock:
            cursor = await self.conn.execute(
                "SELECT balance FROM wallets WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"No wallet found for user {user_id}")
            
            new_balance = max(100.0, row['balance'] + amount)  # Bankruptcy protection
            
            await self.conn.execute(
                "UPDATE wallets SET balance = ? WHERE user_id = ?",
                (new_balance, user_id)
            )
            
            if amount > 0:
                await self.conn.execute("""
                    UPDATE wallets SET lifetime_earnings = lifetime_earnings + ?
                    WHERE user_id = ?
                """, (amount, user_id))
            
            await self.conn.commit()
            return new_balance

    # ==================== Stock Operations ====================
    
    async def get_stock(self, user_id: int) -> Optional[Dict]:
        """Get stock data for a user."""
        cursor = await self.conn.execute(
            "SELECT * FROM stocks WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def update_stock_price(self, user_id: int, new_price: float) -> None:
        """Update a stock's current price and track high/low."""
        async with self._lock:
            cursor = await self.conn.execute(
                "SELECT * FROM stocks WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return
            
            stock = dict(row)
            daily_high = max(stock['daily_high'], new_price)
            daily_low = min(stock['daily_low'], new_price)
            all_time_high = max(stock['all_time_high'], new_price)
            all_time_low = min(stock['all_time_low'], new_price)
            
            await self.conn.execute("""
                UPDATE stocks SET 
                    current_price = ?,
                    daily_high = ?,
                    daily_low = ?,
                    all_time_high = ?,
                    all_time_low = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (new_price, daily_high, daily_low, all_time_high, all_time_low, user_id))
            
            # Record price history
            await self.conn.execute("""
                INSERT INTO price_history (user_id, price) VALUES (?, ?)
            """, (user_id, new_price))
            
            await self.conn.commit()
    
    async def get_available_shares(self, stock_id: int) -> int:
        """Get number of shares available to buy."""
        cursor = await self.conn.execute(
            "SELECT shares_available FROM users WHERE user_id = ?", (stock_id,)
        )
        row = await cursor.fetchone()
        return row['shares_available'] if row else 0

    # ==================== Portfolio Operations ====================
    
    async def get_portfolio(self, holder_id: int) -> List[Dict]:
        """Get all stocks owned by a user."""
        cursor = await self.conn.execute("""
            SELECT p.*, s.current_price, u.username, u.display_name
            FROM portfolios p
            JOIN stocks s ON p.stock_id = s.user_id
            JOIN users u ON p.stock_id = u.user_id
            WHERE p.holder_id = ? AND p.shares > 0
            ORDER BY (p.shares * s.current_price) DESC
        """, (holder_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_holding(self, holder_id: int, stock_id: int) -> Optional[Dict]:
        """Get specific holding."""
        cursor = await self.conn.execute("""
            SELECT * FROM portfolios WHERE holder_id = ? AND stock_id = ?
        """, (holder_id, stock_id))
        row = await cursor.fetchone()
        return dict(row) if row else None
    
    async def get_shareholders(self, stock_id: int) -> List[Dict]:
        """Get all holders of a particular stock."""
        cursor = await self.conn.execute("""
            SELECT p.*, u.username, u.display_name
            FROM portfolios p
            JOIN users u ON p.holder_id = u.user_id
            WHERE p.stock_id = ? AND p.shares > 0
            ORDER BY p.shares DESC
        """, (stock_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ==================== Trading Operations ====================
    
    async def execute_buy(self, buyer_id: int, stock_id: int, shares: int, 
                          price_per_share: float) -> Tuple[bool, str]:
        """
        Execute a buy order. Returns (success, message).
        """
        async with self._lock:
            total_cost = shares * price_per_share
            
            # Check buyer's balance
            wallet = await self.get_wallet(buyer_id)
            if not wallet:
                return False, "You need to register first!"
            if wallet['balance'] < total_cost:
                return False, f"Insufficient funds. Need ${total_cost:.2f}, have ${wallet['balance']:.2f}"
            
            # Check available shares
            available = await self.get_available_shares(stock_id)
            if available < shares:
                return False, f"Only {available} shares available"
            
            # Check ownership limits (max 10%)
            cursor = await self.conn.execute(
                "SELECT total_shares FROM users WHERE user_id = ?", (stock_id,)
            )
            stock_user = await cursor.fetchone()
            max_ownership = int(stock_user['total_shares'] * 0.1)
            
            existing = await self.get_holding(buyer_id, stock_id)
            current_shares = existing['shares'] if existing else 0
            
            if current_shares + shares > max_ownership:
                return False, f"Max ownership is {max_ownership} shares (10%)"
            
            # Execute trade
            # 1. Deduct from buyer
            await self.conn.execute(
                "UPDATE wallets SET balance = balance - ? WHERE user_id = ?",
                (total_cost, buyer_id)
            )
            
            # 2. Reduce available shares
            await self.conn.execute(
                "UPDATE users SET shares_available = shares_available - ? WHERE user_id = ?",
                (shares, stock_id)
            )
            
            # 3. Update portfolio
            lockup_time = datetime.now().isoformat()
            if existing:
                # Update average buy price
                total_shares = current_shares + shares
                new_avg = ((current_shares * existing['avg_buy_price']) + (shares * price_per_share)) / total_shares
                await self.conn.execute("""
                    UPDATE portfolios SET 
                        shares = ?,
                        avg_buy_price = ?,
                        locked_until = datetime('now', '+1 hour'),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE holder_id = ? AND stock_id = ?
                """, (total_shares, new_avg, buyer_id, stock_id))
            else:
                await self.conn.execute("""
                    INSERT INTO portfolios (holder_id, stock_id, shares, avg_buy_price, locked_until)
                    VALUES (?, ?, ?, ?, datetime('now', '+1 hour'))
                """, (buyer_id, stock_id, shares, price_per_share))
            
            # 4. Record transaction
            await self.conn.execute("""
                INSERT INTO transactions (buyer_id, stock_id, shares, price_per_share, total_amount, transaction_type)
                VALUES (?, ?, ?, ?, ?, 'buy')
            """, (buyer_id, stock_id, shares, price_per_share, total_cost))
            
            # 5. Update volume
            await self.conn.execute(
                "UPDATE stocks SET volume_today = volume_today + ? WHERE user_id = ?",
                (shares, stock_id)
            )
            
            await self.conn.commit()
            return True, f"Bought {shares} shares at ${price_per_share:.2f} each. Total: ${total_cost:.2f}"
    
    async def execute_sell(self, seller_id: int, stock_id: int, shares: int,
                           price_per_share: float) -> Tuple[bool, str]:
        """Execute a sell order. Returns (success, message)."""
        async with self._lock:
            # Check holdings
            holding = await self.get_holding(seller_id, stock_id)
            if not holding or holding['shares'] < shares:
                owned = holding['shares'] if holding else 0
                return False, f"You only own {owned} shares"
            
            # Check lockup
            if holding['locked_until']:
                lockup = datetime.fromisoformat(holding['locked_until'])
                if datetime.now() < lockup:
                    remaining = (lockup - datetime.now()).seconds // 60
                    return False, f"Shares locked for {remaining} more minutes"
            
            total_value = shares * price_per_share
            
            # Execute trade
            # 1. Credit seller
            await self.conn.execute(
                "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
                (total_value, seller_id)
            )
            
            # 2. Return shares to available pool
            await self.conn.execute(
                "UPDATE users SET shares_available = shares_available + ? WHERE user_id = ?",
                (shares, stock_id)
            )
            
            # 3. Update portfolio
            new_shares = holding['shares'] - shares
            if new_shares == 0:
                await self.conn.execute(
                    "DELETE FROM portfolios WHERE holder_id = ? AND stock_id = ?",
                    (seller_id, stock_id)
                )
            else:
                await self.conn.execute(
                    "UPDATE portfolios SET shares = ?, updated_at = CURRENT_TIMESTAMP WHERE holder_id = ? AND stock_id = ?",
                    (new_shares, seller_id, stock_id)
                )
            
            # 4. Record transaction
            await self.conn.execute("""
                INSERT INTO transactions (seller_id, stock_id, shares, price_per_share, total_amount, transaction_type)
                VALUES (?, ?, ?, ?, ?, 'sell')
            """, (seller_id, stock_id, shares, price_per_share, total_value))
            
            # 5. Update volume
            await self.conn.execute(
                "UPDATE stocks SET volume_today = volume_today + ? WHERE user_id = ?",
                (shares, stock_id)
            )
            
            await self.conn.commit()
            
            profit = (price_per_share - holding['avg_buy_price']) * shares
            profit_str = f"Profit: ${profit:.2f}" if profit >= 0 else f"Loss: ${abs(profit):.2f}"
            return True, f"Sold {shares} shares at ${price_per_share:.2f}. Total: ${total_value:.2f}. {profit_str}"

    # ==================== Activity Tracking ====================
    
    async def is_opted_out(self, user_id: int) -> bool:
        """Check if user has opted out."""
        cursor = await self.conn.execute(
            "SELECT opted_out FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return bool(row['opted_out']) if row else False

    async def opt_out_user(self, user_id: int) -> None:
        """Mark user as opted out."""
        async with self._lock:
            await self.conn.execute("""
                UPDATE users SET 
                    opted_out = 1,
                    opt_out_date = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (user_id,))
            await self.conn.commit()

    async def record_activity(self, user_id: int, activity_type: str, count: int = 1) -> None:
        """Record user activity for price calculation."""
        # Check if opted out first
        if await self.is_opted_out(user_id):
            return

        today = date.today().isoformat()
        
        async with self._lock:
            # Ensure activity row exists
            await self.conn.execute("""
                INSERT OR IGNORE INTO activity_metrics (user_id, date)
                VALUES (?, ?)
            """, (user_id, today))
            
            # Update the specific metric
            column_map = {
                'message': 'messages',
                'reaction': 'reactions_received',
                'voice': 'voice_minutes',
                'reply': 'replies_received',
                'mention': 'mentions_received'
            }
            
            column = column_map.get(activity_type)
            if column:
                await self.conn.execute(f"""
                    UPDATE activity_metrics SET {column} = {column} + ?
                    WHERE user_id = ? AND date = ?
                """, (count, user_id, today))
            
            # Update last active
            await self.conn.execute(
                "UPDATE wallets SET last_active = ? WHERE user_id = ?",
                (today, user_id)
            )
            
            await self.conn.commit()
    
    async def get_activity(self, user_id: int, days: int = 1) -> List[Dict]:
        """Get activity metrics for a user over the past N days."""
        cursor = await self.conn.execute("""
            SELECT * FROM activity_metrics 
            WHERE user_id = ? AND date >= date('now', ?)
            ORDER BY date DESC
        """, (user_id, f'-{days} days'))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ==================== Leaderboard Queries ====================
    
    async def get_richest(self, limit: int = 10) -> List[Dict]:
        """Get richest players by portfolio value + cash."""
        cursor = await self.conn.execute("""
            SELECT 
                u.user_id, u.username, u.display_name,
                w.balance,
                COALESCE(SUM(p.shares * s.current_price), 0) as portfolio_value,
                w.balance + COALESCE(SUM(p.shares * s.current_price), 0) as net_worth
            FROM users u
            JOIN wallets w ON u.user_id = w.user_id
            LEFT JOIN portfolios p ON u.user_id = p.holder_id
            LEFT JOIN stocks s ON p.stock_id = s.user_id
            GROUP BY u.user_id
            ORDER BY net_worth DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_trending(self, limit: int = 10) -> List[Dict]:
        """Get stocks with biggest gains today."""
        cursor = await self.conn.execute("""
            SELECT 
                u.user_id, u.username, u.display_name,
                s.current_price, s.previous_close,
                ((s.current_price - s.previous_close) / s.previous_close * 100) as change_pct,
                s.volume_today
            FROM stocks s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.previous_close > 0
            ORDER BY change_pct DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    
    async def get_losers(self, limit: int = 10) -> List[Dict]:
        """Get stocks with biggest losses today."""
        cursor = await self.conn.execute("""
            SELECT 
                u.user_id, u.username, u.display_name,
                s.current_price, s.previous_close,
                ((s.current_price - s.previous_close) / s.previous_close * 100) as change_pct,
                s.volume_today
            FROM stocks s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.previous_close > 0
            ORDER BY change_pct ASC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ==================== Dividend Operations ====================
    
    async def pay_dividends(self) -> List[Tuple[int, float]]:
        """
        Pay dividends to all stockholders.
        Returns list of (user_id, amount_paid) tuples.
        """
        payouts = []
        
        async with self._lock:
            # Get all holdings
            cursor = await self.conn.execute("""
                SELECT p.holder_id, p.shares, s.current_price
                FROM portfolios p
                JOIN stocks s ON p.stock_id = s.user_id
                WHERE p.shares > 0
            """)
            holdings = await cursor.fetchall()
            
            for holding in holdings:
                # 2% daily dividend, paid hourly = ~0.083% per hour
                dividend_rate = 0.02 / 24  
                dividend = holding['shares'] * holding['current_price'] * dividend_rate
                
                if dividend > 0:
                    await self.conn.execute("""
                        UPDATE wallets SET 
                            balance = balance + ?,
                            lifetime_dividends = lifetime_dividends + ?
                        WHERE user_id = ?
                    """, (dividend, dividend, holding['holder_id']))
                    
                    payouts.append((holding['holder_id'], dividend))
            
            await self.conn.commit()
            return payouts

    async def record_market_news(self, user_id: int, news_type: str, description: str, impact: float) -> None:
        """Record a news event for a specific stock and apply price impact."""
        async with self._lock:
            await self.conn.execute("""
                INSERT INTO market_news (user_id, news_type, description, impact)
                VALUES (?, ?, ?, ?)
            """, (user_id, news_type, description, impact))
            
            # Apply immediate price impact
            await self.conn.execute("""
                UPDATE stocks SET 
                    current_price = current_price * (1 + ?)
                WHERE user_id = ?
            """, (impact, user_id))
            
            await self.conn.commit()

    async def create_limit_order(self, user_id: int, stock_id: int, shares: int, target_price: float, order_type: str) -> None:
        """Create a new limit order."""
        async with self._lock:
            await self.conn.execute("""
                INSERT INTO limit_orders (user_id, stock_id, shares, target_price, order_type)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, stock_id, shares, target_price, order_type))
            await self.conn.commit()

    async def get_pending_limit_orders(self) -> List[Dict]:
        """Get all pending limit orders."""
        cursor = await self.conn.execute("SELECT * FROM limit_orders")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_limit_order(self, order_id: int) -> None:
        """Delete a limit order."""
        async with self._lock:
            await self.conn.execute("DELETE FROM limit_orders WHERE id = ?", (order_id,))
            await self.conn.commit()

    async def unlock_achievement(self, user_id: int, name: str, desc: str) -> bool:
        """Unlock an achievement for a user. Returns True if newly unlocked."""
        async with self._lock:
            try:
                await self.conn.execute("""
                    INSERT INTO achievements (user_id, achievement_name, description)
                    VALUES (?, ?, ?)
                """, (user_id, name, desc))
                await self.conn.commit()
                return True
            except:
                return False

    async def get_achievements(self, user_id: int) -> List[Dict]:
        """Get all achievements for a user."""
        cursor = await self.conn.execute(
            "SELECT * FROM achievements WHERE user_id = ? ORDER BY unlocked_at DESC", (user_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ==================== Daily Reset Operations ====================

    
    async def daily_reset(self) -> None:
        """Reset daily metrics. Call at midnight."""
        async with self._lock:
            # Store current prices as previous close
            await self.conn.execute("""
                UPDATE stocks SET 
                    previous_close = current_price,
                    daily_high = current_price,
                    daily_low = current_price,
                    volume_today = 0
            """)
            await self.conn.commit()


# Singleton instance
db = Database()
