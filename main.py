import discord
from discord import app_commands
from discord.ext import commands

# Replace 'YOUR_BOT_TOKEN' with your bot's token
TOKEN = 'MTMzNzM0Mjk2NTcwOTkzNDYwNA.GJi-qK.PCpUaUKYQ2U63iEPdzPEtPRa6P9cl9bM-ghW2o'

# Intents are required for certain events and data
intents = discord.Intents.default()
intents.message_content = True

# Create a bot instance with a command prefix
bot = commands.Bot(command_prefix="!", intents=intents)

# Event that triggers when the bot is ready
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

# Define the /ip command
@bot.tree.command(name="ip", description="Get your IP address")
async def ip(interaction: discord.Interaction):
    await interaction.response.send_message("JOIN US! 151.80.47.182:27015")

# Run the bot
bot.run(TOKEN)