"""
Discord Stock Exchange (DSX) Bot

A multiplayer stock trading game where users are tradable stocks.
"""

import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio

from db.database import db

# Load environment variables
load_dotenv()

# Bot configuration
COMMAND_PREFIX = "$"
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.reactions = True
INTENTS.voice_states = True

# Cogs to load
COGS = [
    "cogs.activity_tracker",
    "cogs.trading",
    "cogs.economy",
    "cogs.leaderboards",
    "cogs.advanced_trading",
]


class DSXBot(commands.Bot):
    """Discord Stock Exchange Bot."""
    
    def __init__(self):
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=INTENTS,
            help_command=None,  # Using custom help command in leaderboards cog
        )
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Connect to database
        await db.connect()
        
        # Load cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"[Bot] Loaded cog: {cog}")
            except Exception as e:
                print(f"[Bot] Failed to load cog {cog}: {e}")
    
    async def on_ready(self):
        """Called when the bot is fully connected."""
        print(f"\n{'='*50}")
        print(f"📈 Discord Stock Exchange (DSX) is ONLINE!")
        print(f"{'='*50}")
        print(f"Bot: {self.user.name}#{self.user.discriminator}")
        print(f"ID: {self.user.id}")
        print(f"Servers: {len(self.guilds)}")
        print(f"Command Prefix: {COMMAND_PREFIX}")
        print(f"{'='*50}\n")
        
        # Set presence
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="the stock market 📈"
            )
        )
    
    async def on_member_join(self, member: discord.Member):
        """Auto-register new members and announce their IPO."""
        if member.bot:
            return
        
        # Register the user
        await db.get_or_create_user(
            user_id=member.id,
            username=member.name,
            display_name=member.display_name,
            avatar_url=str(member.display_avatar.url) if member.display_avatar else None
        )
        
        # Find a channel to announce IPO
        # Try to find a general or trading channel
        announce_channel = None
        for channel in member.guild.text_channels:
            if any(name in channel.name.lower() for name in ['trading', 'stocks', 'market', 'general']):
                if channel.permissions_for(member.guild.me).send_messages:
                    announce_channel = channel
                    break
        
        if announce_channel:
            embed = discord.Embed(
                title="🔔 NEW IPO!",
                description=f"**${member.display_name}** just hit the market!",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="Starting Price",
                value="$100.00",
                inline=True
            )
            embed.add_field(
                name="Available Shares",
                value="1,000",
                inline=True
            )
            embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else None)
            embed.set_footer(text="📈 Invest early for maximum gains!")
            
            await announce_channel.send(embed=embed)
    
    async def on_command_error(self, ctx: commands.Context, error):
        """Handle command errors."""
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing argument: `{error.param.name}`")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("❌ User not found. Make sure to @mention them.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Invalid argument. Check your command format.")
        elif isinstance(error, commands.CommandNotFound):
            pass  # Ignore unknown commands
        else:
            print(f"[Error] {type(error).__name__}: {error}")
            await ctx.send("❌ An error occurred. Please try again.")
    
    async def close(self):
        """Clean up when bot shuts down."""
        await db.close()
        await super().close()


async def main():
    """Main entry point."""
    token = os.getenv("DISCORD_TOKEN")
    
    if not token:
        print("❌ Error: DISCORD_TOKEN not found in environment!")
        print("Create a .env file with: DISCORD_TOKEN=your_token_here")
        return
    
    bot = DSXBot()
    
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
