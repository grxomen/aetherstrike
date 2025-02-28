import discord
from discord.ext import commands, tasks
import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Set up SQLite database
conn = sqlite3.connect("activity_tracker.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_xp (
    user_id TEXT PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    total_voice_time INTEGER DEFAULT 0  -- Time in seconds
)
""")
conn.commit()

# Set up bot
intents = discord.Intents.default()
intents.messages = True
intents.voice_states = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Dictionary to track active users in voice channels
active_voice_users = {}
role_xp_multipliers = {  # Define XP multipliers for specific roles
    "VIP": 1.5,
    "Moderator": 2.0
}

@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    track_xp.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    user_id = str(message.author.id)
    add_xp(user_id, 5)  # Grant XP for sending a message
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    user_id = str(member.id)
    
    if after.channel:  # User joined a voice channel
        if user_id not in active_voice_users:
            active_voice_users[user_id] = {
                "start_time": datetime.utcnow(),
                "muted": after.self_mute or after.mute,
                "speaking_time": 0  # Track speaking time
            }
    elif before.channel and not after.channel:  # User left voice
        if user_id in active_voice_users:
            end_time = datetime.utcnow()
            time_diff = (end_time - active_voice_users[user_id]["start_time"]).total_seconds()
            add_voice_time(user_id, time_diff)
            del active_voice_users[user_id]

# Function to add XP and check for level up with role multipliers
def add_xp(user_id, amount, member=None):
    multiplier = 1.0
    if member:
        for role in member.roles:
            if role.name in role_xp_multipliers:
                multiplier = max(multiplier, role_xp_multipliers[role.name])
    amount = int(amount * multiplier)
    
    cursor.execute("SELECT xp, level FROM user_xp WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    xp, level = row if row else (0, 1)
    xp += amount
    
    # Level up logic
    required_xp = level * 100  # XP needed for next level
    if xp >= required_xp:
        xp -= required_xp
        level += 1
        logging.info(f"User {user_id} leveled up to {level}!")
    
    cursor.execute("INSERT INTO user_xp (user_id, xp, level) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET xp = ?, level = ?", (user_id, xp, level, xp, level))
    conn.commit()

# Function to track total voice time and speaking time
def add_voice_time(user_id, duration):
    cursor.execute("SELECT total_voice_time FROM user_xp WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    total_voice_time = row[0] if row else 0
    total_voice_time += int(duration)
    cursor.execute("INSERT INTO user_xp (user_id, total_voice_time) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET total_voice_time = ?", (user_id, total_voice_time, total_voice_time))
    conn.commit()

@tasks.loop(minutes=3)
async def track_xp():
    current_time = datetime.utcnow()
    for user_id, data in list(active_voice_users.items()):
        time_diff = (current_time - data["start_time"]).total_seconds()
        speaking_time = data.get("speaking_time", 0)
        if time_diff >= 180 and speaking_time > 0:  # Give XP based on speaking time
            xp_to_add = int((speaking_time / time_diff) * 10)  # Scale XP based on speaking proportion
            member = bot.get_user(int(user_id))
            add_xp(user_id, xp_to_add, member)
            active_voice_users[user_id]["start_time"] = current_time  # Reset timer
            active_voice_users[user_id]["speaking_time"] = 0  # Reset speaking time

@bot.command()
async def xp(ctx, member: discord.Member = None):
    member = member or ctx.author
    user_id = str(member.id)
    cursor.execute("SELECT xp, level, total_voice_time FROM user_xp WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    xp, level, total_voice_time = row if row else (0, 1, 0)
    total_time_str = str(timedelta(seconds=total_voice_time))  # Convert to HH:MM:SS format
    await ctx.send(f"{member.display_name} is Level {level} with {xp} XP and has spent {total_time_str} in voice channels.")

@bot.command()
async def leaderboard(ctx):
    cursor.execute("SELECT user_id, xp, level FROM user_xp ORDER BY xp DESC LIMIT 10")
    top_users = cursor.fetchall()
    leaderboard_message = "🏆 **XP Leaderboard** 🏆\n"
    for rank, (user_id, xp, level) in enumerate(top_users, start=1):
        member = ctx.guild.get_member(int(user_id))
        name = member.display_name if member else f"User {user_id}"
        leaderboard_message += f"{rank}. {name} - Level {level}, {xp} XP\n"
    await ctx.send(leaderboard_message)

bot.run("YOUR_DISCORD_BOT_TOKEN")
