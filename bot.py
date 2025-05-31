"""
Main entry point for the Arabian Servers Discord Bot.
Handles bot initialization, cog loading, and basic event handling.
"""
import discord
from discord.ext import commands
import asyncio
import os
from utils.constants import TOKEN


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_cogs():
    """Dynamically loads all cogs from the './cogs' directory."""
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")

@bot.event
async def on_ready():
    """
    Called when the bot is successfully logged in and ready.
    Loads cogs and syncs application commands.
    """
    await load_cogs() # load cogs
    await bot.tree.sync()  # sync commands
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
