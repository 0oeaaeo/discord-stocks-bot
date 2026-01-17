"""
Activity Tracker Cog for Discord Stock Exchange.

Monitors user activity (messages, reactions, voice time) and updates metrics
used for stock price calculations.
"""

import discord
from discord.ext import commands, tasks
from datetime import datetime, date
from typing import Dict, Set
import asyncio

from db.database import db


class ActivityTracker(commands.Cog):
    """Tracks user activity for stock price calculations."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
        # In-memory tracking for voice time
        self._voice_sessions: Dict[int, datetime] = {}  # user_id -> join_time
        
        # Debouncing: track recent messages to prevent spam inflation
        self._recent_messages: Dict[int, datetime] = {}  # user_id -> last_message_time
        self.MESSAGE_COOLDOWN = 5  # seconds between counted messages
        
        # Track unique reactors per user per day
        self._daily_reactors: Dict[int, Set[int]] = {}  # target_user -> set of reactor_ids
        
        # Start background tasks
        self.voice_tracker.start()
        self.daily_reset_task.start()
    
    def cog_unload(self):
        """Clean up when cog is unloaded."""
        self.voice_tracker.cancel()
        self.daily_reset_task.cancel()
    
    async def _ensure_user(self, member: discord.Member) -> None:
        """Ensure user exists in database."""
        if member.bot:
            return
        
        await db.get_or_create_user(
            user_id=member.id,
            username=member.name,
            display_name=member.display_name,
            avatar_url=str(member.display_avatar.url) if member.display_avatar else None
        )
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track messages sent by users."""
        if message.author.bot:
            return
        if not message.guild:
            return
        
        user_id = message.author.id
        now = datetime.now()
        
        # Debounce: only count if enough time has passed
        last_msg = self._recent_messages.get(user_id)
        if last_msg and (now - last_msg).total_seconds() < self.MESSAGE_COOLDOWN:
            return
        
        self._recent_messages[user_id] = now
        
        # Ensure user is registered
        await self._ensure_user(message.author)
        
        # Record message activity
        await db.record_activity(user_id, 'message')
        
        # Check if this is a reply to someone
        if message.reference and message.reference.message_id:
            try:
                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                if ref_msg.author and not ref_msg.author.bot:
                    await self._ensure_user(ref_msg.author)
                    await db.record_activity(ref_msg.author.id, 'reply')
            except (discord.NotFound, discord.Forbidden):
                pass
        
        # Check for mentions
        for mentioned in message.mentions:
            if not mentioned.bot and mentioned.id != user_id:
                await self._ensure_user(mentioned)
                await db.record_activity(mentioned.id, 'mention')
    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Track reactions received by users."""
        if user.bot:
            return
        
        message = reaction.message
        if message.author.bot:
            return
        if message.author.id == user.id:
            return  # Don't count self-reactions
        
        target_id = message.author.id
        reactor_id = user.id
        
        # Track unique reactors per target per day
        if target_id not in self._daily_reactors:
            self._daily_reactors[target_id] = set()
        
        # Only count if this is a new reactor for today
        if reactor_id not in self._daily_reactors[target_id]:
            self._daily_reactors[target_id].add(reactor_id)
            
            # Ensure target exists
            if isinstance(message.author, discord.Member):
                await self._ensure_user(message.author)
            
            await db.record_activity(target_id, 'reaction')
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, 
        member: discord.Member, 
        before: discord.VoiceState, 
        after: discord.VoiceState
    ):
        """Track voice channel time."""
        if member.bot:
            return
        
        user_id = member.id
        
        # User joined a voice channel
        if before.channel is None and after.channel is not None:
            self._voice_sessions[user_id] = datetime.now()
            await self._ensure_user(member)
        
        # User left voice channel
        elif before.channel is not None and after.channel is None:
            if user_id in self._voice_sessions:
                join_time = self._voice_sessions.pop(user_id)
                duration = (datetime.now() - join_time).total_seconds()
                minutes = int(duration // 60)
                
                if minutes > 0:
                    await db.record_activity(user_id, 'voice', minutes)
    
    @tasks.loop(minutes=5)
    async def voice_tracker(self):
        """
        Periodically update voice time for active sessions.
        This ensures voice time is tracked even for very long sessions.
        """
        now = datetime.now()
        for user_id, join_time in list(self._voice_sessions.items()):
            duration = (now - join_time).total_seconds()
            minutes = int(duration // 60)
            
            if minutes >= 5:
                await db.record_activity(user_id, 'voice', 5)
                # Reset join time to avoid double counting
                self._voice_sessions[user_id] = now
    
    @voice_tracker.before_loop
    async def before_voice_tracker(self):
        await self.bot.wait_until_ready()
    
    @tasks.loop(hours=24)
    async def daily_reset_task(self):
        """Reset daily tracking at midnight."""
        self._daily_reactors.clear()
        await db.daily_reset()
        print("[ActivityTracker] Daily reset complete")
    
    @daily_reset_task.before_loop
    async def before_daily_reset(self):
        await self.bot.wait_until_ready()
        
        # Wait until next midnight
        now = datetime.now()
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if tomorrow <= now:
            from datetime import timedelta
            tomorrow += timedelta(days=1)
        
        wait_seconds = (tomorrow - now).total_seconds()
        await asyncio.sleep(wait_seconds)
    
    @commands.command(name='mystats')
    async def show_my_stats(self, ctx: commands.Context):
        """Show your activity stats for today."""
        user_id = ctx.author.id
        await self._ensure_user(ctx.author)
        
        activity = await db.get_activity(user_id, days=1)
        
        if not activity:
            await ctx.send("📊 No activity recorded today yet. Start chatting!")
            return
        
        today = activity[0]
        
        embed = discord.Embed(
            title=f"📊 {ctx.author.display_name}'s Activity Today",
            color=discord.Color.blue()
        )
        embed.add_field(name="💬 Messages", value=str(today['messages']), inline=True)
        embed.add_field(name="❤️ Reactions Received", value=str(today['reactions_received']), inline=True)
        embed.add_field(name="🎤 Voice Minutes", value=str(today['voice_minutes']), inline=True)
        embed.add_field(name="💬 Replies Received", value=str(today['replies_received']), inline=True)
        embed.add_field(name="📢 Mentions", value=str(today['mentions_received']), inline=True)
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityTracker(bot))
