import re

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

@bot.tree.command(name="ip", description="Returns an Embed of the Arabian IP")
async def ip(interaction: discord.Interaction):
    # Create an embed
    embed = discord.Embed(
        title="**Welcome to Arabian Servers!**",  # Title with more emphasis
        description="Have fun and enjoy your stay! 🎮",
        color=discord.Color.orange(),  # Vibrant color to make it stand out
        url="https://arabian-servers.com",  # Link to website
    )

    embed.set_author(name="JOIN US!", icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                                                                 "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                                                                 "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                            "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                            "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    # Place the IP in its own large, emphasized field
    embed.add_field(name="🔥 **Server IP** 🔥", value="**`151.80.47.182:27015`**", inline=False)

    # Add fields with some cool icons and structured layout
    embed.add_field(name="📅 **Servers Running Since**", value="2013", inline=True)
    embed.add_field(name="🌍 **Join Now!**", value="[Click here to visit the website](https://arabian-servers.com)", inline=True)

    embed.add_field(name="🎯 **Server Features**", value="• Fast and reliable gameplay\n"
                                                          "• Friendly community\n"
                                                          "• Fun events & tournaments", inline=False)

    embed.add_field(name="📈 **Performance**", value="• Low ping\n"
                                                     "• Stable connection\n"
                                                     "• 24/7 availability", inline=False)

    # Footer with logo and a call to action
    embed.set_footer(
        text="Join the fun! 🕹️ | Arabian Servers for CS 1.6 since 2013",
        icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                 "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                 "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&"
    )

    # Send the embed as a response
    await interaction.response.send_message(embed=embed)


@bot.command(name="ip")
async def ip_prefix(ctx):
    # Create an embed
    embed = discord.Embed(
        title="**Welcome to Arabian Servers!**",  # Title with more emphasis
        description="Have fun and enjoy your stay! 🎮",
        color=discord.Color.orange(),  # Vibrant color to make it stand out
        url="https://arabian-servers.com",  # Link to website
    )

    embed.set_author(name="JOIN US!", icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                                                                 "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                                                                 "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                            "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                            "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    # Place the IP in its own large, emphasized field
    embed.add_field(name="🔥 **Server IP** 🔥", value="**`151.80.47.182:27015`**", inline=False)

    # Add fields with some cool icons and structured layout
    embed.add_field(name="📅 **Servers Running Since**", value="2013", inline=True)
    embed.add_field(name="🌍 **Join Now!**", value="[Click here to visit the website](https://arabian-servers.com)", inline=True)

    embed.add_field(name="🎯 **Server Features**", value="• Fast and reliable gameplay\n"
                                                          "• Friendly community\n"
                                                          "• Fun events & tournaments", inline=False)

    embed.add_field(name="📈 **Performance**", value="• Low ping\n"
                                                     "• Stable connection\n"
                                                     "• 24/7 availability", inline=False)

    # Footer with logo and a call to action
    embed.set_footer(
        text="Join the fun! 🕹️ | Arabian Servers for CS 1.6 since 2013",
        icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                 "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                 "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&"
    )
    await ctx.send(embed=embed)


@bot.tree.command(name="rankstats", description="Get stats for a player")
async def rankstats(interaction: discord.Interaction, player_name: str):
    player_data, mode = get_player_info_dict(player_name)

    if not player_data:
        await interaction.response.send_message(
            f"Player '{player_name}' cannot be found. Please make sure you submit an actual player name.",
            ephemeral=True
        )
        return  # Exit the function early

    if mode == 0:
        # Main Stats Section
        embed = discord.Embed(title=f"**{player_data['Name']}'s Player Stats**", color=discord.Color.blue())

        embed.add_field(name="🏅 Rank", value=f"**{player_data['Rank Placement']} ({player_data['Rank']}**)", inline=False)
        embed.add_field(name="▬" * 20, value="", inline=False)

        embed.add_field(name="🎯 K/D Ratio", value=f"**{player_data['K/D Ratio']}**", inline=True)
        embed.add_field(name="💀 Kills / Deaths", value=f"**{player_data['Kills']} / {player_data['Deaths']}**",
                        inline=True)
        embed.add_field(name="🩸 Headshots", value=f"**{player_data['Headshots']}**", inline=True)
        embed.add_field(name="🔫 Shots / Hits", value=f"**{player_data['Shots']} / {player_data['Hits']}**", inline=True)
        embed.add_field(name="💥 Damage", value=f"**{player_data['Damage']}**", inline=True)

        embed.add_field(name="▬" * 20, value="", inline=False)
        # C4 Stats Section
        embed.add_field(name="💣 C4 Stats",
                        value=f"Planted: **{player_data['C4 Planted']}** | Exploded: **{player_data['C4 Exploded']}** | Defused: **{player_data['C4 Defused']}**",
                        inline=False)

        # MVP Section
        embed.add_field(name="🏆 Most Valuable Player", value=f"**{player_data['Most Valuable Player']} Times MVP**", inline=True)

        embed.add_field(name="▬" * 20, value="", inline=False)
        # Top Weapons Section
        top_weapons = "\n".join(
            [f"{list(weapon.keys())[0]}: **{list(weapon.values())[0]}**" for weapon in player_data['Top Weapons']])
        embed.add_field(name="🔝 Top Weapons", value=top_weapons, inline=False)

        embed.add_field(name="▬" * 20, value="", inline=False)
        # Played Time and Login Section (with better spacing)
        embed.add_field(name="⏱️ Total Played Time", value=f"**{player_data['Played Time']}**", inline=False)
        embed.add_field(name="📅 First Login", value=f"**{player_data['First Login']}**", inline=False)
        embed.add_field(name="📅 Last Login", value=f"**{player_data['Last Login']}**", inline=False)

        # Send the embed message
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    elif mode == 1:
        player_names = list(player_data.values())  # Extract player names from the dictionary
        embed = discord.Embed(title="Too many players with similar username",
                              description="",
                              color=discord.Color.red())

        player_names_str = "`" + ", ".join(str(name) for name in player_names) + "`"
        embed.add_field(name=player_names_str, value="", inline=True)
        embed.add_field(name="", value="Please re-enter a more precise name (case-sensitive)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# Run the bot
bot.run(TOKEN)