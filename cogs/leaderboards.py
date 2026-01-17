"""
Leaderboards Cog for Discord Stock Exchange.

Displays various rankings and trending stocks.
"""

import discord
from discord.ext import commands
from typing import Optional

from db.database import db
from utils.pricing import pricing_engine


class Leaderboards(commands.Cog):
    """Leaderboard commands for competitive rankings."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @commands.command(name='leaderboard', aliases=['lb', 'top', 'rich'])
    async def show_leaderboard(self, ctx: commands.Context, limit: int = 10):
        """
        Show the richest players by net worth.
        
        Usage: $leaderboard or $lb 20
        """
        limit = min(limit, 25)  # Cap at 25
        
        richest = await db.get_richest(limit)
        
        if not richest:
            await ctx.send("📊 No players registered yet!")
            return
        
        embed = discord.Embed(
            title="💎 Richest Players",
            description="Ranked by net worth (cash + portfolio)",
            color=discord.Color.gold()
        )
        
        medals = ["🥇", "🥈", "🥉"]
        leaderboard_text = ""
        
        for i, player in enumerate(richest):
            medal = medals[i] if i < 3 else f"`{i+1}.`"
            name = player['display_name'] or player['username']
            net_worth = pricing_engine.format_price(player['net_worth'])
            
            leaderboard_text += f"{medal} **{name}** - {net_worth}\n"
        
        embed.add_field(
            name="Rankings",
            value=leaderboard_text or "No data",
            inline=False
        )
        
        embed.set_footer(text=f"💵 Be active and invest wisely!")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='trending', aliases=['hot', 'gainers'])
    async def show_trending(self, ctx: commands.Context, limit: int = 10):
        """
        Show stocks with the biggest gains today.
        
        Usage: $trending or $hot 15
        """
        limit = min(limit, 20)
        
        trending = await db.get_trending(limit)
        
        if not trending:
            await ctx.send("📈 No price data available yet!")
            return
        
        embed = discord.Embed(
            title="🚀 Trending Stocks",
            description="Biggest gainers today",
            color=discord.Color.green()
        )
        
        trending_text = ""
        for i, stock in enumerate(trending, 1):
            name = stock['display_name'] or stock['username']
            price = pricing_engine.format_price(stock['current_price'])
            change = stock['change_pct']
            
            if change >= 10:
                emoji = "🚀"
            elif change >= 5:
                emoji = "📈"
            elif change >= 0:
                emoji = "↗️"
            else:
                continue  # Skip negative changes for trending
            
            trending_text += f"{emoji} **${name}** - {price} (+{change:.2f}%)\n"
        
        if not trending_text:
            trending_text = "*No stocks with gains today*"
        
        embed.add_field(
            name="Top Gainers",
            value=trending_text,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='losers', aliases=['falling', 'dumps'])
    async def show_losers(self, ctx: commands.Context, limit: int = 10):
        """
        Show stocks with the biggest losses today.
        
        Usage: $losers or $falling 15
        """
        limit = min(limit, 20)
        
        losers = await db.get_losers(limit)
        
        if not losers:
            await ctx.send("📉 No price data available yet!")
            return
        
        embed = discord.Embed(
            title="📉 Falling Stocks",
            description="Biggest losers today",
            color=discord.Color.red()
        )
        
        loser_text = ""
        for i, stock in enumerate(losers, 1):
            name = stock['display_name'] or stock['username']
            price = pricing_engine.format_price(stock['current_price'])
            change = stock['change_pct']
            
            if change <= -10:
                emoji = "💀"
            elif change <= -5:
                emoji = "📉"
            elif change < 0:
                emoji = "↘️"
            else:
                continue  # Skip positive for losers
            
            loser_text += f"{emoji} **${name}** - {price} ({change:.2f}%)\n"
        
        if not loser_text:
            loser_text = "*No stocks with losses today*"
        
        embed.add_field(
            name="Top Losers",
            value=loser_text,
            inline=False
        )
        
        embed.set_footer(text="💡 Buy the dip?")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='volume', aliases=['active'])
    async def show_volume(self, ctx: commands.Context, limit: int = 10):
        """
        Show most traded stocks today.
        
        Usage: $volume or $active 15
        """
        limit = min(limit, 20)
        
        cursor = await db.conn.execute("""
            SELECT u.username, u.display_name, s.current_price, s.volume_today
            FROM stocks s
            JOIN users u ON s.user_id = u.user_id
            WHERE s.volume_today > 0
            ORDER BY s.volume_today DESC
            LIMIT ?
        """, (limit,))
        most_traded = await cursor.fetchall()
        
        if not most_traded:
            await ctx.send("📊 No trading activity today!")
            return
        
        embed = discord.Embed(
            title="📊 Most Active Stocks",
            description="Highest trading volume today",
            color=discord.Color.blue()
        )
        
        volume_text = ""
        for i, stock in enumerate(most_traded, 1):
            name = stock['display_name'] or stock['username']
            price = pricing_engine.format_price(stock['current_price'])
            volume = stock['volume_today']
            
            volume_text += f"`{i}.` **${name}** - {volume} shares traded ({price})\n"
        
        embed.add_field(
            name="Trading Volume",
            value=volume_text or "*No trading today*",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='achievements', aliases=['trophies', 'badges'])
    async def show_achievements(self, ctx: commands.Context, target: Optional[discord.Member] = None):
        """View your achievements or someone else's."""
        user = target or ctx.author
        achievements = await db.get_achievements(user.id)
        
        if not achievements:
            await ctx.send(f"🏆 **{user.display_name}** hasn't unlocked any achievements yet.")
            return
        
        embed = discord.Embed(
            title=f"🏆 {user.display_name}'s Trophy Cabinet",
            color=discord.Color.gold()
        )
        
        for ach in achievements:
            embed.add_field(
                name=f"🌟 {ach['achievement_name']}",
                value=ach['description'],
                inline=True
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='help', aliases=['commands', 'h'])
    async def show_help(self, ctx: commands.Context):
        """Show all available commands."""
        embed = discord.Embed(
            title="📈 Discord Stock Exchange - Commands",
            description="Trade shares of your fellow server members!",
            color=discord.Color.blue()
        )
        
        # Trading commands
        embed.add_field(
            name="💹 Trading",
            value=(
                "`$buy @user <shares>` - Buy shares\n"
                "`$sell @user <shares>` - Sell shares\n"
                "`$portfolio` - View your holdings\n"
                "`$ticker @user` - View stock info\n"
                "`$shareholders` - See who owns you"
            ),
            inline=False
        )
        
        # Advanced trading
        embed.add_field(
            name="📉 Advanced Trading",
            value=(
                "`$short @user <shares>` - Short a stock\n"
                "`$cover @user <shares>` - Close short\n"
                "`$shorts` - View your short positions\n"
                "`$limit buy @user <sh> <pr>` - Auto-buy at price\n"
                "`$limit sell @user <sh> <pr>` - Auto-sell at price"
            ),
            inline=False
        )
        
        # Hedge funds
        embed.add_field(
            name="🏦 Hedge Funds",
            value=(
                "`$fund create <name>` - Create fund ($1k)\n"
                "`$fund deposit <amount>` - Add funds\n"
                "`$fund info [name]` - View fund details"
            ),
            inline=False
        )
        
        # Economy commands
        embed.add_field(
            name="💰 Economy",
            value=(
                "`$daily` - Claim daily bonus\n"
                "`$balance` - Check your cash\n"
                "`$networth` - Detailed breakdown\n"
                "`$mystock` - Your stock info"
            ),
            inline=False
        )
        
        # Leaderboards
        embed.add_field(
            name="🏆 Leaderboards",
            value=(
                "`$leaderboard` - Richest players\n"
                "`$trending` - Biggest gainers\n"
                "`$losers` - Biggest drops\n"
                "`$volume` - Most traded"
            ),
            inline=False
        )
        
        # Info
        embed.add_field(
            name="📊 Stats",
            value=(
                "`$mystats` - Your activity today\n"
                "`$achievements` - Your trophy cabinet"
            ),
            inline=False
        )
        
        embed.set_footer(text="💡 Prices update every 5 min | Dividends hourly | Market events random!")
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboards(bot))
