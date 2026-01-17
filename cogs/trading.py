"""
Trading Cog for Discord Stock Exchange.

Implements buy/sell commands and portfolio management.
"""

import discord
from discord.ext import commands
from datetime import datetime
from typing import Optional

from db.database import db
from utils.pricing import pricing_engine


class Trading(commands.Cog):
    """Core trading commands for the stock exchange."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def _ensure_user(self, member: discord.Member) -> None:
        """Ensure user exists in database."""
        await db.get_or_create_user(
            user_id=member.id,
            username=member.name,
            display_name=member.display_name,
            avatar_url=str(member.display_avatar.url) if member.display_avatar else None
        )
    
    @commands.command(name='buy')
    async def buy_stock(self, ctx: commands.Context, target: discord.Member, shares: int):
        """
        Buy shares of a user's stock.
        
        Usage: $buy @user 10
        """
        if shares <= 0:
            await ctx.send("❌ Must buy at least 1 share.")
            return
        
        if target.bot:
            await ctx.send("❌ Can't buy stock in bots!")
            return
        
        if target.id == ctx.author.id:
            await ctx.send("❌ You can't buy your own stock!")
            return
        
        # Ensure both users exist
        await self._ensure_user(ctx.author)
        await self._ensure_user(target)
        
        # Get current price
        stock = await db.get_stock(target.id)
        if not stock:
            await ctx.send("❌ That user's stock isn't available yet.")
            return
        
        # Check if opted out
        user_data = await db.get_user(target.id)
        if user_data.get('opted_out'):
            await ctx.send(f"❌ **${target.display_name}** has opted out. Their stock is decaying and cannot be purchased.")
            return
        
        price = stock['current_price']
        total_cost = shares * price
        
        # Execute the trade
        success, message = await db.execute_buy(ctx.author.id, target.id, shares, price)
        
        if success:
            # Get updated balance
            wallet = await db.get_wallet(ctx.author.id)
            
            embed = discord.Embed(
                title="✅ Trade Executed!",
                description=f"Bought **{shares}** shares of **${target.display_name}**",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Price Per Share", 
                value=pricing_engine.format_price(price), 
                inline=True
            )
            embed.add_field(
                name="Total Cost", 
                value=pricing_engine.format_price(total_cost), 
                inline=True
            )
            embed.add_field(
                name="Remaining Balance", 
                value=pricing_engine.format_price(wallet['balance']), 
                inline=True
            )
            embed.set_footer(text="📝 Shares locked for 1 hour")
            
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ {message}")
    
    @commands.command(name='sell')
    async def sell_stock(self, ctx: commands.Context, target: discord.Member, shares: int):
        """
        Sell shares of a user's stock.
        
        Usage: $sell @user 5
        """
        if shares <= 0:
            await ctx.send("❌ Must sell at least 1 share.")
            return
        
        # Ensure user exists
        await self._ensure_user(ctx.author)
        
        # Get current price
        stock = await db.get_stock(target.id)
        if not stock:
            await ctx.send("❌ That stock doesn't exist.")
            return
        
        price = stock['current_price']
        total_value = shares * price
        
        # Execute the trade
        success, message = await db.execute_sell(ctx.author.id, target.id, shares, price)
        
        if success:
            wallet = await db.get_wallet(ctx.author.id)
            
            embed = discord.Embed(
                title="✅ Shares Sold!",
                description=f"Sold **{shares}** shares of **${target.display_name}**",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="Price Per Share", 
                value=pricing_engine.format_price(price), 
                inline=True
            )
            embed.add_field(
                name="Total Value", 
                value=pricing_engine.format_price(total_value), 
                inline=True
            )
            embed.add_field(
                name="New Balance", 
                value=pricing_engine.format_price(wallet['balance']), 
                inline=True
            )
            
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ {message}")
    
    @commands.command(name='portfolio', aliases=['pf', 'holdings'])
    async def show_portfolio(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        """
        View your portfolio or someone else's.
        
        Usage: $portfolio or $portfolio @user
        """
        user = target or ctx.author
        await self._ensure_user(user)
        
        holdings = await db.get_portfolio(user.id)
        wallet = await db.get_wallet(user.id)
        
        if not holdings and not wallet:
            await ctx.send("❌ User not registered. They need to chat first!")
            return
        
        # Calculate total portfolio value
        portfolio_value = sum(h['shares'] * h['current_price'] for h in holdings)
        net_worth = wallet['balance'] + portfolio_value
        
        embed = discord.Embed(
            title=f"📈 {user.display_name}'s Portfolio",
            color=discord.Color.blue()
        )
        
        # Cash section
        embed.add_field(
            name="💵 Cash Balance",
            value=pricing_engine.format_price(wallet['balance']),
            inline=True
        )
        embed.add_field(
            name="📊 Portfolio Value",
            value=pricing_engine.format_price(portfolio_value),
            inline=True
        )
        embed.add_field(
            name="💎 Net Worth",
            value=pricing_engine.format_price(net_worth),
            inline=True
        )
        
        # Holdings section
        if holdings:
            holdings_text = ""
            for h in holdings[:10]:  # Top 10 holdings
                value = h['shares'] * h['current_price']
                profit_pct = ((h['current_price'] - h['avg_buy_price']) / h['avg_buy_price'] * 100) if h['avg_buy_price'] > 0 else 0
                profit_emoji = "🟢" if profit_pct >= 0 else "🔴"
                
                display_name = h['display_name'] or h['username']
                holdings_text += f"{profit_emoji} **${display_name}**: {h['shares']} shares @ {pricing_engine.format_price(h['current_price'])} ({profit_pct:+.1f}%)\n"
            
            embed.add_field(
                name="📦 Holdings",
                value=holdings_text or "No holdings",
                inline=False
            )
        else:
            embed.add_field(
                name="📦 Holdings",
                value="*No stocks owned yet. Use `$buy @user <amount>` to invest!*",
                inline=False
            )
        
        embed.set_footer(text=f"Daily Streak: {wallet['daily_streak']} days 🔥")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='balance', aliases=['bal', 'cash'])
    async def show_balance(self, ctx: commands.Context):
        """Check your current balance."""
        await self._ensure_user(ctx.author)
        wallet = await db.get_wallet(ctx.author.id)
        
        await ctx.send(f"💵 **Balance:** {pricing_engine.format_price(wallet['balance'])}")
    
    @commands.command(name='ticker', aliases=['stock', 'price'])
    async def show_ticker(self, ctx: commands.Context, target: discord.Member):
        """
        View a user's stock information.
        
        Usage: $ticker @user
        """
        if target.bot:
            await ctx.send("❌ Bots don't have stocks!")
            return
        
        await self._ensure_user(target)
        
        stock = await db.get_stock(target.id)
        user = await db.get_user(target.id)
        shareholders = await db.get_shareholders(target.id)
        
        if not stock:
            await ctx.send("❌ User not registered yet.")
            return
        
        # Calculate change
        change_pct = 0
        if stock['previous_close'] > 0:
            change_pct = ((stock['current_price'] - stock['previous_close']) / stock['previous_close']) * 100
        
        trend = pricing_engine.calculate_trend(stock['current_price'], stock['previous_close'])
        color = discord.Color.green() if change_pct >= 0 else discord.Color.red()
        
        embed = discord.Embed(
            title=f"{trend} ${target.display_name}",
            description=f"**{pricing_engine.format_price(stock['current_price'])}** ({change_pct:+.2f}%)",
            color=color
        )
        
        embed.add_field(
            name="📊 Today",
            value=f"High: {pricing_engine.format_price(stock['daily_high'])}\nLow: {pricing_engine.format_price(stock['daily_low'])}",
            inline=True
        )
        embed.add_field(
            name="📈 All Time",
            value=f"High: {pricing_engine.format_price(stock['all_time_high'])}\nLow: {pricing_engine.format_price(stock['all_time_low'])}",
            inline=True
        )
        embed.add_field(
            name="📦 Volume",
            value=f"{stock['volume_today']} shares today",
            inline=True
        )
        
        # Shares info
        shares_owned = user['total_shares'] - user['shares_available']
        embed.add_field(
            name="💹 Supply",
            value=f"{shares_owned}/{user['total_shares']} shares owned\n{user['shares_available']} available",
            inline=True
        )
        
        # Top shareholders
        if shareholders:
            top_holders = shareholders[:3]
            holder_text = "\n".join([
                f"{i+1}. {h['display_name'] or h['username']}: {h['shares']} shares"
                for i, h in enumerate(top_holders)
            ])
            embed.add_field(
                name="👥 Top Shareholders",
                value=holder_text,
                inline=True
            )
        
        embed.set_thumbnail(url=target.display_avatar.url if target.display_avatar else None)
        embed.set_footer(text=f"Last updated: {stock['last_updated']}")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='shareholders', aliases=['holders', 'investors'])
    async def show_shareholders(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        """
        See who owns shares of a stock.
        
        Usage: $shareholders @user (or just $shareholders for yourself)
        """
        user = target or ctx.author
        
        if user.bot:
            await ctx.send("❌ Bots don't have stocks!")
            return
        
        await self._ensure_user(user)
        
        shareholders = await db.get_shareholders(user.id)
        
        if not shareholders:
            await ctx.send(f"📊 No one owns shares of **${user.display_name}** yet!")
            return
        
        embed = discord.Embed(
            title=f"👥 Shareholders of ${user.display_name}",
            color=discord.Color.blue()
        )
        
        total_owned = sum(h['shares'] for h in shareholders)
        
        for i, h in enumerate(shareholders[:10], 1):
            ownership_pct = (h['shares'] / 1000) * 100  # Assuming 1000 total shares
            name = h['display_name'] or h['username']
            embed.add_field(
                name=f"{i}. {name}",
                value=f"{h['shares']} shares ({ownership_pct:.1f}%)",
                inline=True
            )
        
        embed.set_footer(text=f"Total shares owned: {total_owned}/1000")
        
        await ctx.send(embed=embed)

    @commands.command(name='optout')
    async def opt_out(self, ctx: commands.Context):
        """
        Voluntarily opt out of the stock exchange.
        
        WARNING: This is permanent. Your activity will no longer be tracked,
        your stock price will decay 25% daily until it hits 0, at which point
        you will be removed from the game.
        """
        await self._ensure_user(ctx.author)
        
        if await db.is_opted_out(ctx.author.id):
            await ctx.send("❌ You have already opted out.")
            return

        embed = discord.Embed(
            title="⚠️ OPT OUT CONFIRMATION",
            description=(
                "Are you sure you want to opt out of the Discord Stock Exchange?\n\n"
                "**Consequences:**\n"
                "• All activity tracking ceases immediately.\n"
                "• Your stock price will **decay by 25% per day**.\n"
                "• When your price hits $0.00, you and your shares will be **permanently removed**.\n"
                "• You are advised to sell your holdings now!\n\n"
                "Type `confirm` to proceed or `cancel` to stay in the game."
            ),
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['confirm', 'cancel']

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=30.0)
            if msg.content.lower() == 'confirm':
                await db.opt_out_user(ctx.author.id)
                
                exit_embed = discord.Embed(
                    title="📉 OPTED OUT",
                    description=(
                        f"**{ctx.author.display_name}** has opted out of the exchange.\n\n"
                        "Activity tracking has stopped. Share prices will now begin to decay "
                        "at 25% per day. Holders should liquidate their positions immediately!"
                    ),
                    color=discord.Color.dark_grey()
                )
                await ctx.send(embed=exit_embed)
                
                # Global announcement
                for guild in self.bot.guilds:
                    for channel in guild.text_channels:
                        if any(name in channel.name.lower() for name in ['trading', 'stocks', 'market', 'general']):
                            if channel.permissions_for(guild.me).send_messages:
                                if channel.id != ctx.channel.id: # Don't send twice to same channel
                                    await channel.send(embed=exit_embed)
                                break
            else:
                await ctx.send("✅ Opt-out cancelled. Glad to have you stay!")
        except TimeoutError:
            await ctx.send("⏳ Confirmation timed out. Opt-out cancelled.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Trading(bot))
