"""
Economy Cog for Discord Stock Exchange.

Handles dividends, daily bonuses, and financial operations.
"""

import discord
from discord.ext import commands, tasks
from datetime import datetime, date, timedelta
from typing import Optional

from db.database import db
from utils.pricing import pricing_engine, ActivityMetrics


class Economy(commands.Cog):
    """Economy system: dividends, daily bonuses, price updates."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_news_trigger = {} # user_id -> datetime
        
        # Start background tasks
        self.dividend_payout.start()
        self.price_update.start()
    
    def cog_unload(self):
        self.dividend_payout.cancel()
        self.price_update.cancel()
    
    async def _ensure_user(self, member: discord.Member) -> None:
        """Ensure user exists in database."""
        await db.get_or_create_user(
            user_id=member.id,
            username=member.name,
            display_name=member.display_name,
            avatar_url=str(member.display_avatar.url) if member.display_avatar else None
        )
    
    @tasks.loop(hours=1)
    async def dividend_payout(self):
        """Pay dividends to all stockholders every hour."""
        try:
            payouts = await db.pay_dividends()
            total_paid = sum(amount for _, amount in payouts)
            print(f"[Economy] Paid dividends to {len(payouts)} holders. Total: ${total_paid:.2f}")
        except Exception as e:
            print(f"[Economy] Dividend payout error: {e}")
    
    @dividend_payout.before_loop
    async def before_dividend(self):
        await self.bot.wait_until_ready()
    
    @tasks.loop(minutes=5)
    async def price_update(self):
        """
        Update all stock prices based on activity metrics.
        Runs every 5 minutes.
        """
        try:
            # Get all users with stocks
            cursor = await db.conn.execute("""
                SELECT u.user_id, u.opted_out, u.opt_out_date, s.base_price, s.current_price, w.daily_streak, w.last_active
                FROM users u
                JOIN stocks s ON u.user_id = s.user_id
                LEFT JOIN wallets w ON u.user_id = w.user_id
                WHERE u.is_active = 1
            """)
            users = await cursor.fetchall()
            
            for user in users:
                user_id = user['user_id']
                
                if user['opted_out']:
                    # Apply 25% daily decay
                    # Price update runs every 5 minutes (288 times/day)
                    # Decay multiplier per 5 mins: (0.75)^(1/288) ≈ 0.999002
                    # However, to be more precise and avoid floating point drift, 
                    # we can calculate it based on total time since opt out.
                    
                    # For simplicity in this bot, let's just apply a flat decay per 5 mins
                    # that roughly equals 25% per day. 
                    # 0.999 per 5 mins is about 0.749 (25.1% decay) per day.
                    new_price = user['current_price'] * 0.999
                    
                    if new_price < 0.01:
                        # User is removed completely
                        await db.remove_user_completely(user_id)
                        print(f"[Economy] Removed opted-out user {user_id} (price hit 0)")
                        continue
                    
                    await db.update_stock_price(user_id, new_price)
                    continue

                # Get today's activity
                activity_data = await db.get_activity(user_id, days=1)
                
                if activity_data:
                    metrics = ActivityMetrics(
                        messages=activity_data[0]['messages'],
                        reactions_received=activity_data[0]['reactions_received'],
                        voice_minutes=activity_data[0]['voice_minutes'],
                        replies_received=activity_data[0]['replies_received'],
                        mentions_received=activity_data[0]['mentions_received']
                    )
                else:
                    metrics = ActivityMetrics()
                
                # Calculate days inactive
                days_inactive = 0
                if user['last_active']:
                    last_active = datetime.strptime(user['last_active'], '%Y-%m-%d').date()
                    days_inactive = (date.today() - last_active).days
                
                # Calculate new price
                new_price = pricing_engine.calculate_price(
                    base_price=user['base_price'],
                    metrics=metrics,
                    consecutive_days=user['daily_streak'] or 0,
                    days_inactive=days_inactive
                )
                
                # Update the price
                await db.update_stock_price(user_id, new_price)

                # Check for dynamic news events
                await self._handle_potential_news(user_id, metrics)
            
            # Process limit orders after all prices updated
            await self._process_limit_orders()
            
            # Check for general achievements
            await self._check_global_achievements()
            
            print(f"[Economy] Updated prices for {len(users)} stocks")
        except Exception as e:
            print(f"[Economy] Price update error: {e}")

    async def _check_global_achievements(self):
        """Check for achievements across all users."""
        # We can use the get_richest leaderboard to check for top players
        top_players = await db.get_richest(50)
        for player in top_players:
            if player['net_worth'] >= 1000000:
                unlocked = await db.unlock_achievement(
                    player['user_id'],
                    "First Millionaire",
                    "Joined the seven-figure club by reaching $1,000,000 net worth."
                )
                if unlocked:
                    await self._announce_achievement(player['user_id'], "First Millionaire")

    async def _announce_achievement(self, user_id: int, achievement_name: str):
        """Announce achievement to the server."""
        user = await self.bot.fetch_user(user_id)
        if not user:
            return

        embed = discord.Embed(
            title="🌟 ACHIEVEMENT UNLOCKED!",
            description=f"{user.mention} just earned the **{achievement_name}** trophy!",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url="https://i.imgur.com/vHdfY9Y.png") # Trophy icon placeholder
        
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if any(name in channel.name.lower() for name in ['trading', 'stocks', 'market', 'general']):
                    if channel.permissions_for(guild.me).send_messages:
                        await channel.send(embed=embed)
                        break

    async def _process_limit_orders(self):
        """Check and execute pending limit orders."""
        orders = await db.get_pending_limit_orders()
        for order in orders:
            stock = await db.get_stock(order['stock_id'])
            if not stock:
                continue
            
            current_price = stock['current_price']
            triggered = False
            
            if order['order_type'] == 'buy_low' and current_price <= order['target_price']:
                triggered = True
                success, msg = await db.execute_buy(order['user_id'], order['stock_id'], order['shares'], current_price)
            elif order['order_type'] == 'sell_high' and current_price >= order['target_price']:
                triggered = True
                success, msg = await db.execute_sell(order['user_id'], order['stock_id'], order['shares'], current_price)
            
            if triggered:
                await db.delete_limit_order(order['id'])
                # Notify user
                try:
                    user = await self.bot.fetch_user(order['user_id'])
                    if user:
                        status = "✅ Success" if success else "❌ Failed"
                        await user.send(f"🤖 **Limit Order Triggered!**\nType: {order['order_type']}\nStock: ${order['stock_id']}\nResult: {status} - {msg}")
                except:
                    pass

    async def _handle_potential_news(self, user_id: int, metrics: ActivityMetrics):
        """Analyze metrics and potentially trigger news events."""
        now = datetime.now()
        
        # Cooldown: one news event per user every 4 hours
        if user_id in self._last_news_trigger:
            if now < self._last_news_trigger[user_id] + timedelta(hours=4):
                return

        news_event = None
        
        # Bullish: High Engagement
        if metrics.reactions_received >= 20:
            news_event = {
                'type': 'Viral Success',
                'desc': "is going viral! Engagement is at an all-time high.",
                'impact': 0.10 # +10%
            }
        elif metrics.replies_received >= 10:
            news_event = {
                'type': 'Community Favorite',
                'desc': "is leading the conversation today. Investors are bullish.",
                'impact': 0.05 # +5%
            }
        
        # Bearish: Long Inactivity (handled separately or here)
        # For now let's focus on bullish spikes as they are more "exciting"

        if news_event:
            self._last_news_trigger[user_id] = now
            await db.record_market_news(user_id, news_event['type'], news_event['desc'], news_event['impact'])
            
            # Announce news
            user = await self.bot.fetch_user(user_id)
            if user:
                await self._announce_news(user, news_event)

    async def _announce_news(self, user, event):
        """Announce news to relevant channels."""
        embed = discord.Embed(
            title=f"📰 BREAKING NEWS: ${user.display_name}",
            description=f"**{event['type']}**: {user.mention} {event['desc']}",
            color=discord.Color.green() if event['impact'] > 0 else discord.Color.red()
        )
        embed.add_field(name="Price Impact", value=f"{event['impact'] * 100:+.0f}%", inline=True)
        
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if any(name in channel.name.lower() for name in ['trading', 'stocks', 'market', 'general']):
                    if channel.permissions_for(guild.me).send_messages:
                        await channel.send(embed=embed)
                        return # Only send to one channel per guild
    
    @price_update.before_loop
    async def before_price_update(self):
        await self.bot.wait_until_ready()
    
    @commands.command(name='daily')
    async def claim_daily(self, ctx: commands.Context):
        """
        Claim your daily login bonus.
        
        Base: $500
        Streak bonus: +$50 per consecutive day (max 7 days = $850)
        """
        await self._ensure_user(ctx.author)
        
        wallet = await db.get_wallet(ctx.author.id)
        today = date.today()
        
        # Check if already claimed today
        if wallet['last_daily_claim']:
            last_claim = datetime.strptime(wallet['last_daily_claim'], '%Y-%m-%d').date()
            if last_claim == today:
                await ctx.send("❌ You've already claimed your daily bonus! Come back tomorrow.")
                return
            
            # Check for streak
            yesterday = today - timedelta(days=1)
            if last_claim == yesterday:
                new_streak = min(wallet['daily_streak'] + 1, 7)
            else:
                new_streak = 1
        else:
            new_streak = 1
        
        # Calculate bonus
        base_bonus = 500
        streak_bonus = (new_streak - 1) * 50  # +$50 per streak day
        total_bonus = base_bonus + streak_bonus
        
        # Update wallet
        async with db._lock:
            await db.conn.execute("""
                UPDATE wallets SET 
                    balance = balance + ?,
                    daily_streak = ?,
                    last_daily_claim = ?
                WHERE user_id = ?
            """, (total_bonus, new_streak, today.isoformat(), ctx.author.id))
            await db.conn.commit()
        
        # Get new balance
        new_wallet = await db.get_wallet(ctx.author.id)
        
        embed = discord.Embed(
            title="💰 Daily Bonus Claimed!",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="Base Bonus",
            value=f"${base_bonus}",
            inline=True
        )
        if streak_bonus > 0:
            embed.add_field(
                name="Streak Bonus",
                value=f"+${streak_bonus}",
                inline=True
            )
        embed.add_field(
            name="Total",
            value=f"**${total_bonus}**",
            inline=True
        )
        embed.add_field(
            name="New Balance",
            value=pricing_engine.format_price(new_wallet['balance']),
            inline=False
        )
        
        streak_display = "🔥" * new_streak
        embed.set_footer(text=f"Daily Streak: {new_streak}/7 {streak_display}")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='networth', aliases=['nw'])
    async def show_networth(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        """Show detailed net worth breakdown."""
        user = target or ctx.author
        await self._ensure_user(user)
        
        wallet = await db.get_wallet(user.id)
        holdings = await db.get_portfolio(user.id)
        
        # Calculate portfolio value
        portfolio_value = sum(h['shares'] * h['current_price'] for h in holdings)
        unrealized_gains = sum(
            (h['current_price'] - h['avg_buy_price']) * h['shares'] 
            for h in holdings
        )
        
        net_worth = wallet['balance'] + portfolio_value
        
        embed = discord.Embed(
            title=f"💎 {user.display_name}'s Net Worth",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="💵 Cash",
            value=pricing_engine.format_price(wallet['balance']),
            inline=True
        )
        embed.add_field(
            name="📈 Investments",
            value=pricing_engine.format_price(portfolio_value),
            inline=True
        )
        embed.add_field(
            name="💎 Net Worth",
            value=f"**{pricing_engine.format_price(net_worth)}**",
            inline=True
        )
        
        gains_emoji = "🟢" if unrealized_gains >= 0 else "🔴"
        embed.add_field(
            name=f"{gains_emoji} Unrealized P/L",
            value=f"${unrealized_gains:+,.2f}",
            inline=True
        )
        embed.add_field(
            name="📊 Lifetime Dividends",
            value=pricing_engine.format_price(wallet['lifetime_dividends']),
            inline=True
        )
        embed.add_field(
            name="💰 Lifetime Earnings",
            value=pricing_engine.format_price(wallet['lifetime_earnings']),
            inline=True
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='mystock', aliases=['me'])
    async def show_my_stock(self, ctx: commands.Context):
        """View your own stock information and value."""
        await self._ensure_user(ctx.author)
        
        stock = await db.get_stock(ctx.author.id)
        user = await db.get_user(ctx.author.id)
        shareholders = await db.get_shareholders(ctx.author.id)
        
        if not stock:
            await ctx.send("❌ Error loading your stock data.")
            return
        
        # Calculate change
        change_pct = 0
        if stock['previous_close'] > 0:
            change_pct = ((stock['current_price'] - stock['previous_close']) / stock['previous_close']) * 100
        
        trend = pricing_engine.calculate_trend(stock['current_price'], stock['previous_close'])
        color = discord.Color.green() if change_pct >= 0 else discord.Color.red()
        
        embed = discord.Embed(
            title=f"{trend} Your Stock: ${ctx.author.display_name}",
            description=f"Current Price: **{pricing_engine.format_price(stock['current_price'])}** ({change_pct:+.2f}%)",
            color=color
        )
        
        # Supply info
        shares_owned = user['total_shares'] - user['shares_available']
        embed.add_field(
            name="📊 Ownership",
            value=f"{shares_owned}/{user['total_shares']} shares owned by others\n{user['shares_available']} shares available",
            inline=False
        )
        
        # Price stats
        embed.add_field(
            name="📈 Today",
            value=f"High: {pricing_engine.format_price(stock['daily_high'])}\nLow: {pricing_engine.format_price(stock['daily_low'])}",
            inline=True
        )
        embed.add_field(
            name="🏆 All Time",
            value=f"High: {pricing_engine.format_price(stock['all_time_high'])}\nLow: {pricing_engine.format_price(stock['all_time_low'])}",
            inline=True
        )
        
        # Shareholders
        if shareholders:
            holder_text = "\n".join([
                f"• {h['display_name'] or h['username']}: {h['shares']} shares"
                for h in shareholders[:5]
            ])
            embed.add_field(
                name=f"👥 Your Investors ({len(shareholders)} total)",
                value=holder_text,
                inline=False
            )
        else:
            embed.add_field(
                name="👥 Your Investors",
                value="*No one has invested in you yet!*",
                inline=False
            )
        
        embed.set_thumbnail(url=ctx.author.display_avatar.url if ctx.author.display_avatar else None)
        embed.set_footer(text="💡 Tip: Be active to increase your stock price!")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
