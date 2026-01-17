"""
Advanced Trading Cog for Discord Stock Exchange.

Implements short selling, margin calls, market events, hedge funds, and stock splits.
"""

import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from typing import Optional
import random

from db.database import db
from utils.pricing import pricing_engine


class AdvancedTrading(commands.Cog):
    """Advanced trading features: shorts, hedge funds, market events, splits."""
    
    # Short selling config
    MARGIN_REQUIREMENT = 1.5    # 150% collateral required
    MARGIN_CALL_THRESHOLD = 1.3 # 130% - warning issued
    LIQUIDATION_THRESHOLD = 1.1 # 110% - position force-closed
    
    # Market event config
    CRASH_PROBABILITY = 0.02    # 2% chance per hour
    BOOM_PROBABILITY = 0.02     # 2% chance per hour
    
    # Stock split config
    SPLIT_THRESHOLD = 10000.0   # Stock price that triggers split eligibility
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.margin_check.start()
        self.market_event_roller.start()
        self.split_checker.start()
    
    def cog_unload(self):
        self.margin_check.cancel()
        self.market_event_roller.cancel()
        self.split_checker.cancel()

    # ==================== SHORT SELLING ====================
    
    @commands.command(name='short')
    async def open_short(self, ctx: commands.Context, target: discord.Member, shares: int):
        """
        Open a short position - bet against a user's stock.
        
        You borrow shares and sell them, hoping to buy back cheaper.
        Requires 150% collateral. Liquidated if price rises too high.
        
        Usage: $short @user 10
        """
        if shares <= 0:
            await ctx.send("❌ Must short at least 1 share.")
            return
        
        if target.bot or target.id == ctx.author.id:
            await ctx.send("❌ Can't short bots or yourself!")
            return
        
        user_id = ctx.author.id
        stock_id = target.id
        
        # Get current price
        stock = await db.get_stock(stock_id)
        if not stock:
            await ctx.send("❌ That stock doesn't exist.")
            return
        
        price = stock['current_price']
        position_value = shares * price
        required_collateral = position_value * self.MARGIN_REQUIREMENT
        
        # Check balance
        wallet = await db.get_wallet(user_id)
        if not wallet or wallet['balance'] < required_collateral:
            await ctx.send(f"❌ Insufficient funds. Need ${required_collateral:.2f} collateral (150% of position).")
            return
        
        # Calculate margin call and liquidation prices
        margin_call_price = price * (1 + (self.MARGIN_REQUIREMENT - self.MARGIN_CALL_THRESHOLD))
        liquidation_price = price * (1 + (self.MARGIN_REQUIREMENT - self.LIQUIDATION_THRESHOLD))
        
        async with db._lock:
            # Lock collateral
            await db.conn.execute(
                "UPDATE wallets SET balance = balance - ? WHERE user_id = ?",
                (required_collateral, user_id)
            )
            
            # Credit the short sale proceeds to balance (they sold the borrowed shares)
            await db.conn.execute(
                "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
                (position_value, user_id)
            )
            
            # Create short position
            await db.conn.execute("""
                INSERT INTO short_positions 
                (holder_id, stock_id, shares, entry_price, collateral, margin_call_price, liquidation_price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, stock_id, shares, price, required_collateral, margin_call_price, liquidation_price))
            
            # Record transaction
            await db.conn.execute("""
                INSERT INTO transactions 
                (buyer_id, stock_id, shares, price_per_share, total_amount, transaction_type)
                VALUES (?, ?, ?, ?, ?, 'short')
            """, (user_id, stock_id, shares, price, position_value))
            
            await db.conn.commit()
        
        embed = discord.Embed(
            title="📉 Short Position Opened!",
            description=f"Shorting **{shares}** shares of **${target.display_name}**",
            color=discord.Color.red()
        )
        embed.add_field(name="Entry Price", value=pricing_engine.format_price(price), inline=True)
        embed.add_field(name="Position Value", value=pricing_engine.format_price(position_value), inline=True)
        embed.add_field(name="Collateral Locked", value=pricing_engine.format_price(required_collateral), inline=True)
        embed.add_field(name="⚠️ Margin Call At", value=pricing_engine.format_price(margin_call_price), inline=True)
        embed.add_field(name="💀 Liquidation At", value=pricing_engine.format_price(liquidation_price), inline=True)
        embed.set_footer(text="💡 Close with $cover @user <shares>")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='cover', aliases=['closeShort'])
    async def close_short(self, ctx: commands.Context, target: discord.Member, shares: int):
        """
        Close a short position by buying back shares.
        
        Usage: $cover @user 10
        """
        if shares <= 0:
            await ctx.send("❌ Must cover at least 1 share.")
            return
        
        user_id = ctx.author.id
        stock_id = target.id
        
        # Get short position
        cursor = await db.conn.execute("""
            SELECT * FROM short_positions 
            WHERE holder_id = ? AND stock_id = ?
        """, (user_id, stock_id))
        position = await cursor.fetchone()
        
        if not position:
            await ctx.send("❌ You don't have a short position in that stock.")
            return

        # Check lockup period (1 hour)
        created_at = datetime.fromisoformat(position['created_at'])
        if datetime.now() < created_at + timedelta(hours=1):
            remaining = (created_at + timedelta(hours=1) - datetime.now()).total_seconds()
            minutes = int(remaining // 60)
            seconds = int(remaining % 60)
            await ctx.send(f"❌ Short position is locked for another **{minutes}m {seconds}s**.")
            return
        
        if shares > position['shares']:
            await ctx.send(f"❌ You only have {position['shares']} shares shorted.")
            return
        
        # Get current price
        stock = await db.get_stock(stock_id)
        current_price = stock['current_price']
        entry_price = position['entry_price']
        
        # Calculate P/L
        cover_cost = shares * current_price
        original_proceeds = shares * entry_price
        profit = original_proceeds - cover_cost  # Positive if price dropped
        
        # Return proportional collateral
        collateral_return = (shares / position['shares']) * position['collateral']
        
        async with db._lock:
            # Pay for cover (buy back shares)
            await db.conn.execute(
                "UPDATE wallets SET balance = balance - ? WHERE user_id = ?",
                (cover_cost, user_id)
            )
            
            # Return collateral
            await db.conn.execute(
                "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
                (collateral_return, user_id)
            )
            
            # Update or delete position
            remaining = position['shares'] - shares
            if remaining == 0:
                await db.conn.execute(
                    "DELETE FROM short_positions WHERE id = ?",
                    (position['id'],)
                )
            else:
                new_collateral = position['collateral'] - collateral_return
                await db.conn.execute(
                    "UPDATE short_positions SET shares = ?, collateral = ? WHERE id = ?",
                    (remaining, new_collateral, position['id'])
                )
            
            # Record transaction
            await db.conn.execute("""
                INSERT INTO transactions 
                (buyer_id, stock_id, shares, price_per_share, total_amount, transaction_type)
                VALUES (?, ?, ?, ?, ?, 'short_cover')
            """, (user_id, stock_id, shares, current_price, cover_cost))
            
            await db.conn.commit()
        
        profit_emoji = "🟢" if profit >= 0 else "🔴"
        embed = discord.Embed(
            title="📈 Short Position Covered!",
            description=f"Closed **{shares}** shares of **${target.display_name}**",
            color=discord.Color.green() if profit >= 0 else discord.Color.red()
        )
        embed.add_field(name="Entry Price", value=pricing_engine.format_price(entry_price), inline=True)
        embed.add_field(name="Cover Price", value=pricing_engine.format_price(current_price), inline=True)
        embed.add_field(name=f"{profit_emoji} Profit/Loss", value=f"${profit:+,.2f}", inline=True)
        embed.add_field(name="Collateral Returned", value=pricing_engine.format_price(collateral_return), inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='shorts', aliases=['myshorts'])
    async def view_shorts(self, ctx: commands.Context):
        """View your open short positions."""
        user_id = ctx.author.id
        
        cursor = await db.conn.execute("""
            SELECT sp.*, u.username, u.display_name, s.current_price
            FROM short_positions sp
            JOIN users u ON sp.stock_id = u.user_id
            JOIN stocks s ON sp.stock_id = s.user_id
            WHERE sp.holder_id = ?
        """, (user_id,))
        positions = await cursor.fetchall()
        
        if not positions:
            await ctx.send("📉 You have no open short positions.")
            return
        
        embed = discord.Embed(
            title="📉 Your Short Positions",
            color=discord.Color.orange()
        )
        
        total_pnl = 0
        for pos in positions:
            name = pos['display_name'] or pos['username']
            current = pos['current_price']
            entry = pos['entry_price']
            shares = pos['shares']
            pnl = (entry - current) * shares
            total_pnl += pnl
            
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            status = []
            if current >= pos['liquidation_price']:
                status.append("💀 LIQUIDATION")
            elif current >= pos['margin_call_price']:
                status.append("⚠️ MARGIN CALL")
            
            # Check lockup
            created_at = datetime.fromisoformat(pos['created_at'])
            if datetime.now() < created_at + timedelta(hours=1):
                remaining = (created_at + timedelta(hours=1) - datetime.now()).total_seconds()
                status.append(f"🔒 {int(remaining // 60)}m")
            
            status_str = " | ".join(status)
            if status_str:
                status_str = f"({status_str})"
            
            embed.add_field(
                name=f"${name} {status_str}",
                value=f"{shares} shares @ ${entry:.2f}\nNow: ${current:.2f}\n{pnl_emoji} P/L: ${pnl:+,.2f}",
                inline=True
            )
        
        pnl_color = "🟢" if total_pnl >= 0 else "🔴"
        embed.set_footer(text=f"{pnl_color} Total Unrealized P/L: ${total_pnl:+,.2f}")
        
        await ctx.send(embed=embed)
    
    @tasks.loop(minutes=5)
    async def margin_check(self):
        """Check all short positions for margin calls and liquidations."""
        try:
            cursor = await db.conn.execute("""
                SELECT sp.*, u.username, s.current_price
                FROM short_positions sp
                JOIN users u ON sp.stock_id = u.user_id
                JOIN stocks s ON sp.stock_id = s.user_id
            """)
            positions = await cursor.fetchall()
            
            for pos in positions:
                current_price = pos['current_price']
                
                # Check for liquidation
                if current_price >= pos['liquidation_price']:
                    await self._liquidate_short(pos)
                    print(f"[AdvancedTrading] Liquidated short: {pos['holder_id']} on {pos['stock_id']}")
        except Exception as e:
            print(f"[AdvancedTrading] Margin check error: {e}")
    
    async def _liquidate_short(self, position: dict):
        """Force close a short position."""
        user_id = position['holder_id']
        stock_id = position['stock_id']
        shares = position['shares']
        current_price = position['current_price']
        entry_price = position['entry_price']
        
        cover_cost = shares * current_price
        loss = cover_cost - (shares * entry_price)
        
        async with db._lock:
            # Use collateral to cover (may not be enough)
            remaining_collateral = max(0, position['collateral'] - cover_cost)
            
            # Return whatever's left
            await db.conn.execute(
                "UPDATE wallets SET balance = balance + ? WHERE user_id = ?",
                (remaining_collateral, user_id)
            )
            
            # Delete position
            await db.conn.execute(
                "DELETE FROM short_positions WHERE id = ?",
                (position['id'],)
            )
            
            await db.conn.commit()
    
    @margin_check.before_loop
    async def before_margin_check(self):
        await self.bot.wait_until_ready()

    # ==================== HEDGE FUNDS ====================
    
    @commands.group(name='fund', aliases=['hf', 'hedge'])
    async def hedge_fund(self, ctx: commands.Context):
        """Hedge fund commands. Use $fund help for details."""
        if ctx.invoked_subcommand is None:
            await ctx.send("📊 Use `$fund create <name>`, `$fund join <name>`, `$fund deposit <amount>`, `$fund info`")
    
    @hedge_fund.command(name='create')
    async def fund_create(self, ctx: commands.Context, *, name: str):
        """Create a new hedge fund. Cost: $1,000"""
        user_id = ctx.author.id
        creation_cost = 1000.0
        
        if len(name) > 32:
            await ctx.send("❌ Fund name too long (max 32 characters).")
            return
        
        wallet = await db.get_wallet(user_id)
        if not wallet or wallet['balance'] < creation_cost:
            await ctx.send(f"❌ Need ${creation_cost} to create a fund.")
            return
        
        async with db._lock:
            # Check if name taken
            cursor = await db.conn.execute(
                "SELECT id FROM hedge_funds WHERE name = ?", (name,)
            )
            if await cursor.fetchone():
                await ctx.send("❌ That fund name is already taken.")
                return
            
            # Deduct cost
            await db.conn.execute(
                "UPDATE wallets SET balance = balance - ? WHERE user_id = ?",
                (creation_cost, user_id)
            )
            
            # Create fund
            cursor = await db.conn.execute("""
                INSERT INTO hedge_funds (name, founder_id, treasury)
                VALUES (?, ?, ?)
            """, (name, user_id, 0))
            fund_id = cursor.lastrowid
            
            # Add founder as member
            await db.conn.execute("""
                INSERT INTO hedge_fund_members (fund_id, user_id, role, share_pct)
                VALUES (?, ?, 'founder', 100.0)
            """, (fund_id, user_id))
            
            await db.conn.commit()
        
        embed = discord.Embed(
            title="🏦 Hedge Fund Created!",
            description=f"**{name}** is now open for business!",
            color=discord.Color.gold()
        )
        embed.add_field(name="Founder", value=ctx.author.display_name, inline=True)
        embed.add_field(name="Treasury", value="$0.00", inline=True)
        embed.set_footer(text="Use $fund deposit <amount> to add funds")
        
        await ctx.send(embed=embed)
    
    @hedge_fund.command(name='deposit')
    async def fund_deposit(self, ctx: commands.Context, amount: float):
        """Deposit money into your hedge fund."""
        user_id = ctx.author.id
        
        if amount <= 0:
            await ctx.send("❌ Must deposit a positive amount.")
            return
        
        # Find user's fund
        cursor = await db.conn.execute("""
            SELECT hf.* FROM hedge_funds hf
            JOIN hedge_fund_members hfm ON hf.id = hfm.fund_id
            WHERE hfm.user_id = ?
        """, (user_id,))
        fund = await cursor.fetchone()
        
        if not fund:
            await ctx.send("❌ You're not in a hedge fund. Use `$fund create <name>` or `$fund join <name>`.")
            return
        
        wallet = await db.get_wallet(user_id)
        if not wallet or wallet['balance'] < amount:
            await ctx.send("❌ Insufficient funds.")
            return
        
        async with db._lock:
            # Deduct from wallet
            await db.conn.execute(
                "UPDATE wallets SET balance = balance - ? WHERE user_id = ?",
                (amount, user_id)
            )
            
            # Add to fund treasury
            await db.conn.execute(
                "UPDATE hedge_funds SET treasury = treasury + ? WHERE id = ?",
                (amount, fund['id'])
            )
            
            # Update member contribution
            await db.conn.execute("""
                UPDATE hedge_fund_members 
                SET contribution = contribution + ?
                WHERE fund_id = ? AND user_id = ?
            """, (amount, fund['id'], user_id))
            
            await db.conn.commit()
        
        # Recalculate ownership percentages
        await self._recalculate_fund_shares(fund['id'])
        
        await ctx.send(f"💰 Deposited **${amount:,.2f}** into **{fund['name']}**!")
    
    @hedge_fund.command(name='info')
    async def fund_info(self, ctx: commands.Context, *, name: str = None):
        """View hedge fund information."""
        if name:
            cursor = await db.conn.execute(
                "SELECT * FROM hedge_funds WHERE name = ?", (name,)
            )
        else:
            # Show user's fund
            cursor = await db.conn.execute("""
                SELECT hf.* FROM hedge_funds hf
                JOIN hedge_fund_members hfm ON hf.id = hfm.fund_id
                WHERE hfm.user_id = ?
            """, (ctx.author.id,))
        
        fund = await cursor.fetchone()
        
        if not fund:
            await ctx.send("❌ Fund not found.")
            return
        
        # Get members
        cursor = await db.conn.execute("""
            SELECT hfm.*, u.username, u.display_name
            FROM hedge_fund_members hfm
            JOIN users u ON hfm.user_id = u.user_id
            WHERE hfm.fund_id = ?
            ORDER BY hfm.share_pct DESC
        """, (fund['id'],))
        members = await cursor.fetchall()
        
        embed = discord.Embed(
            title=f"🏦 {fund['name']}",
            color=discord.Color.blue()
        )
        embed.add_field(name="💰 Treasury", value=f"${fund['treasury']:,.2f}", inline=True)
        embed.add_field(name="👥 Members", value=str(fund['member_count']), inline=True)
        
        member_text = ""
        for m in members[:5]:
            name = m['display_name'] or m['username']
            role_emoji = "👑" if m['role'] == 'founder' else "💼" if m['role'] == 'manager' else "👤"
            member_text += f"{role_emoji} {name}: {m['share_pct']:.1f}%\n"
        
        embed.add_field(name="Members", value=member_text or "No members", inline=False)
        
        await ctx.send(embed=embed)
    
    async def _recalculate_fund_shares(self, fund_id: int):
        """Recalculate ownership percentages based on contributions."""
        cursor = await db.conn.execute(
            "SELECT SUM(contribution) as total FROM hedge_fund_members WHERE fund_id = ?",
            (fund_id,)
        )
        result = await cursor.fetchone()
        total = result['total'] or 0
        
        if total > 0:
            await db.conn.execute("""
                UPDATE hedge_fund_members 
                SET share_pct = (contribution / ?) * 100
                WHERE fund_id = ?
            """, (total, fund_id))
            await db.conn.commit()

    # ==================== MARKET EVENTS ====================
    
    @tasks.loop(hours=1)
    async def market_event_roller(self):
        """Randomly trigger market events."""
        try:
            roll = random.random()
            
            if roll < self.CRASH_PROBABILITY:
                await self._trigger_market_event('crash')
            elif roll < self.CRASH_PROBABILITY + self.BOOM_PROBABILITY:
                await self._trigger_market_event('boom')
        except Exception as e:
            print(f"[AdvancedTrading] Market event error: {e}")
    
    async def _trigger_market_event(self, event_type: str):
        """Trigger a market-wide event."""
        if event_type == 'crash':
            magnitude = random.uniform(0.7, 0.9)  # 10-30% drop
            description = "📉 **MARKET CRASH!** All stocks dropped!"
            emoji = "💥"
        else:  # boom
            magnitude = random.uniform(1.1, 1.3)  # 10-30% rise
            description = "🚀 **MARKET BOOM!** All stocks surging!"
            emoji = "📈"
        
        # Apply to all stocks
        async with db._lock:
            await db.conn.execute("""
                UPDATE stocks SET 
                    current_price = current_price * ?,
                    daily_high = CASE WHEN current_price * ? > daily_high THEN current_price * ? ELSE daily_high END,
                    daily_low = CASE WHEN current_price * ? < daily_low THEN current_price * ? ELSE daily_low END
            """, (magnitude, magnitude, magnitude, magnitude, magnitude))
            
            # Record event
            await db.conn.execute("""
                INSERT INTO market_events (event_type, magnitude, description, active_until)
                VALUES (?, ?, ?, datetime('now', '+1 hour'))
            """, (event_type, magnitude, description))
            
            await db.conn.commit()
        
        # Announce in all guilds
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if any(name in channel.name.lower() for name in ['trading', 'stocks', 'market', 'general']):
                    if channel.permissions_for(guild.me).send_messages:
                        change_pct = (magnitude - 1) * 100
                        embed = discord.Embed(
                            title=f"{emoji} MARKET EVENT",
                            description=description,
                            color=discord.Color.red() if event_type == 'crash' else discord.Color.green()
                        )
                        embed.add_field(
                            name="Impact",
                            value=f"All stocks {'+' if change_pct >= 0 else ''}{change_pct:.1f}%",
                            inline=True
                        )
                        await channel.send(embed=embed)
                        break
        
        print(f"[AdvancedTrading] Market event: {event_type} ({magnitude:.2f}x)")
    
    @market_event_roller.before_loop
    async def before_market_event(self):
        await self.bot.wait_until_ready()
    
    @commands.command(name='crash')
    @commands.is_owner()
    async def force_crash(self, ctx: commands.Context):
        """[Owner] Force a market crash."""
        await self._trigger_market_event('crash')
        await ctx.send("💥 Market crash triggered!")
    
    @commands.command(name='boom')
    @commands.is_owner()
    async def force_boom(self, ctx: commands.Context):
        """[Owner] Force a market boom."""
        await self._trigger_market_event('boom')
        await ctx.send("🚀 Market boom triggered!")

    # ==================== STOCK SPLITS ====================
    
    @tasks.loop(hours=6)
    async def split_checker(self):
        """Check for stocks eligible for splits."""
        try:
            cursor = await db.conn.execute("""
                SELECT s.*, u.username, u.display_name
                FROM stocks s
                JOIN users u ON s.user_id = u.user_id
                WHERE s.current_price >= ?
            """, (self.SPLIT_THRESHOLD,))
            
            eligible = await cursor.fetchall()
            
            for stock in eligible:
                # Auto-split high-value stocks 2:1
                await self._execute_split(stock['user_id'], 2)
                print(f"[AdvancedTrading] Auto-split for {stock['username']}")
        except Exception as e:
            print(f"[AdvancedTrading] Split checker error: {e}")
    
    @split_checker.before_loop
    async def before_split_checker(self):
        await self.bot.wait_until_ready()
    
    async def _execute_split(self, user_id: int, ratio: int):
        """Execute a stock split."""
        stock = await db.get_stock(user_id)
        user = await db.get_user(user_id)
        
        if not stock or not user:
            return
        
        old_price = stock['current_price']
        new_price = old_price / ratio
        old_shares = user['total_shares']
        new_shares = old_shares * ratio
        
        async with db._lock:
            # Update stock price
            await db.conn.execute("""
                UPDATE stocks SET 
                    current_price = ?,
                    base_price = base_price / ?,
                    previous_close = previous_close / ?,
                    daily_high = daily_high / ?,
                    daily_low = daily_low / ?
                WHERE user_id = ?
            """, (new_price, ratio, ratio, ratio, ratio, user_id))
            
            # Update user shares
            await db.conn.execute("""
                UPDATE users SET 
                    total_shares = ?,
                    shares_available = shares_available * ?
                WHERE user_id = ?
            """, (new_shares, ratio, user_id))
            
            # Update all portfolios holding this stock
            await db.conn.execute("""
                UPDATE portfolios SET 
                    shares = shares * ?,
                    avg_buy_price = avg_buy_price / ?
                WHERE stock_id = ?
            """, (ratio, ratio, user_id))
            
            # Record split
            await db.conn.execute("""
                INSERT INTO stock_splits 
                (user_id, old_shares, new_shares, split_ratio, old_price, new_price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, old_shares, new_shares, f"{ratio}:1", old_price, new_price))
            
            await db.conn.commit()
        
        # Announce split
        for guild in self.bot.guilds:
            member = guild.get_member(user_id)
            if member:
                for channel in guild.text_channels:
                    if any(name in channel.name.lower() for name in ['trading', 'stocks', 'market', 'general']):
                        if channel.permissions_for(guild.me).send_messages:
                            embed = discord.Embed(
                                title="📊 STOCK SPLIT!",
                                description=f"**${member.display_name}** just split {ratio}:1!",
                                color=discord.Color.blue()
                            )
                            embed.add_field(name="Old Price", value=pricing_engine.format_price(old_price), inline=True)
                            embed.add_field(name="New Price", value=pricing_engine.format_price(new_price), inline=True)
                            embed.add_field(name="New Total Shares", value=f"{new_shares:,}", inline=True)
                            embed.set_footer(text="Your share count was automatically adjusted!")
                            await channel.send(embed=embed)
                            break
                break
    
    @commands.command(name='split')
    @commands.is_owner()
    async def force_split(self, ctx: commands.Context, target: discord.Member, ratio: int = 2):
        """[Owner] Force a stock split."""
        if ratio < 2 or ratio > 10:
            await ctx.send("❌ Ratio must be between 2 and 10.")
            return
        
        await self._execute_split(target.id, ratio)
        await ctx.send(f"📊 Forced {ratio}:1 split on **${target.display_name}**!")

    # ==================== LIMIT ORDERS ====================

    @commands.group(name='limit')
    async def limit_order(self, ctx: commands.Context):
        """Limit order commands. Use $limit buy or $limit sell."""
        if ctx.invoked_subcommand is None:
            await ctx.send("📉 Use `$limit buy @user <shares> <price>` or `$limit sell @user <shares> <price>`")

    @limit_order.command(name='buy')
    async def limit_buy(self, ctx: commands.Context, target: discord.Member, shares: int, price: float):
        """Set a 'buy low' limit order."""
        if shares <= 0 or price <= 0:
            await ctx.send("❌ Shares and price must be positive.")
            return
        
        # Basic check to see if target stock exists
        stock = await db.get_stock(target.id)
        if not stock:
            await ctx.send("❌ That stock doesn't exist.")
            return

        await db.create_limit_order(ctx.author.id, target.id, shares, price, 'buy_low')
        await ctx.send(f"✅ Limit Order set: Buy **{shares}** of **${target.display_name}** if price hits **${price:.2f}** or lower.")

    @limit_order.command(name='sell')
    async def limit_sell(self, ctx: commands.Context, target: discord.Member, shares: int, price: float):
        """Set a 'sell high' limit order."""
        if shares <= 0 or price <= 0:
            await ctx.send("❌ Shares and price must be positive.")
            return
        
        # Basic check to see if target stock exists
        stock = await db.get_stock(target.id)
        if not stock:
            await ctx.send("❌ That stock doesn't exist.")
            return

        await db.create_limit_order(ctx.author.id, target.id, shares, price, 'sell_high')
        await ctx.send(f"✅ Limit Order set: Sell **{shares}** of **${target.display_name}** if price hits **${price:.2f}** or higher.")


async def setup(bot: commands.Bot):
    await bot.add_cog(AdvancedTrading(bot))
