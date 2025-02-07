import discord
from discord import app_commands
from discord.ext import commands

# Replace 'YOUR_BOT_TOKEN' with your bot's token
TOKEN = 'MTMzNzM0Mjk2NTcwOTkzNDYwNA.GJi-qK.PCpUaUKYQ2U63iEPdzPEtPRa6P9cl9bM-ghW2o'
# TOKEN = 'MTMzNzQ0OTQ5MjgwMjMxMDM0NA.GIi1v1.yHa0asvsTac3YW6hwFFyxeZ-W8OeX1yQMD4its'
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
@bot.tree.command(name="ip", description="Returns an Embed of the Arabian IP")
async def ip(interaction: discord.Interaction):
    # Create an embed
    embed = discord.Embed(
        title="arabian-servers.com",  # Title of the embed
        description="Have fun and enjoy your stay!",  # Description of the embed
        color=discord.Color.blue(),  # Color of the embed (optional)
        url="https://arabian-servers.com",

    )
    embed.set_author(name="151.80.47.182:27015")
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                                "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                                "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")
    # Set a footer (optional)
    embed.set_footer(text="Arabian Servers for CS 1.6 since 2013!"
                     , icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                                "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                                "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    # Send the embed as a response
    await interaction.response.send_message(embed=embed)

# Run the bot
bot.run(TOKEN)