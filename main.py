import discord
from discord.ext import commands

from player_stats import get_player_info_dict

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


@bot.tree.command(name="stats", description="Get stats for a player")
async def stats(interaction: discord.Interaction, player_name: str):
    # Fetch player data (replace this with your actual logic)
    player_data = get_player_info_dict(player_name)

    # Check if player_data is empty
    if not player_data:  # This checks if the dictionary is empty
        await interaction.response.send_message(
            f"Player '{player_name}' cannot be found. Please make sure you submit an actual player name.",
            ephemeral=True  # Only the user who invoked the command will see this message
        )
        return  # Exit the function early

    # Create the embed (only if player_data is not empty)
    embed = discord.Embed(title=f"Player Stats for {player_data['name']}", color=discord.Color.blue())

    # Add fields to the embed
    embed.add_field(name="Rank", value=player_data['rank'], inline=True)
    embed.add_field(name="Current XP", value=player_data['current_xp'], inline=True)
    embed.add_field(name="Progress", value=player_data['progress'], inline=True)
    embed.add_field(name="MVP", value=player_data['mvp'], inline=True)
    embed.add_field(name="Rounds Won", value=player_data['rounds_won'], inline=True)
    embed.add_field(name="C4 Planted", value=player_data['c4_planted'], inline=True)
    embed.add_field(name="C4 Exploded", value=player_data['c4_exploded'], inline=True)
    embed.add_field(name="C4 Defused", value=player_data['c4_defused'], inline=True)
    embed.add_field(name="Kills", value=player_data['kills'], inline=True)
    embed.add_field(name="Deaths", value=player_data['deaths'], inline=True)
    embed.add_field(name="Assists", value=player_data['assists'], inline=True)
    embed.add_field(name="Headshots", value=player_data['headshots'], inline=True)
    embed.add_field(name="KD Ratio", value=player_data['kd_ratio'], inline=True)
    embed.add_field(name="Shots", value=player_data['shots'], inline=True)
    embed.add_field(name="Hits", value=player_data['hits'], inline=True)
    embed.add_field(name="Damage", value=player_data['damage'], inline=True)
    embed.add_field(name="Accuracy", value=player_data['accuracy'], inline=True)
    embed.add_field(name="First Login", value=player_data['first_login'], inline=True)
    embed.add_field(name="Last Login", value=player_data['last_login'], inline=True)
    embed.add_field(name="Played Time", value=player_data['played_time'], inline=True)

    # Add top weapons field
    top_weapons = "\n".join([f"{list(weapon.keys())[0]}: {list(weapon.values())[0]}" for weapon in player_data['top_weapons']])
    embed.add_field(name="Top Weapons", value=top_weapons, inline=False)

    # Send the embed as a response to the interaction
    await interaction.response.send_message(embed=embed)

# Run the bot
bot.run(TOKEN)