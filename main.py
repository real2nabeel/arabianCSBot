import os
import traceback

import discord
from discord.ext import commands
import logging
import boto3
from discord.ui import Button, View

from player_stats import get_player_info_dict, get_top_players
from constants import LOGGING_CHANNEL_ID, SERVER_ADDRESS
import a2s

ENV = 'master'

if ENV == 'dev':
    token = os.environ['TOKEN_DEV']
else:
    token = 'MTMzNzM0Mjk2NTcwOTkzNDYwNA.GJi-qK.PCpUaUKYQ2U63iEPdzPEtPRa6P9cl9bM-ghW2o'


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


@bot.tree.command(name="ip2", description="Returns an Embed of the Arabian IP")
async def ip2(interaction: discord.Interaction):
    embed = discord.Embed(
        title="**Welcome to Arabian Servers!**",  # Title with more emphasis
        description="Have fun and enjoy your stay! 🎮",
        color=discord.Color.orange(),  # Vibrant color to make it stand out
        url="https://arabian-servers.com",  # Link to website
    )

    embed.set_author(name="JOIN US!",
                     icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                              "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                              "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                            "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                            "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

    # Place the IP in its own large, emphasized field
    embed.add_field(name="🔥 **Server IP** 🔥", value="**`151.80.47.182:27015`**", inline=False)

    # Add fields with some cool icons and structured layout
    embed.add_field(name="📅 **Servers Running Since**", value="2013", inline=True)
    embed.add_field(name="🌍 **Join Now!**", value="[Click here to visit the website](https://arabian-servers.com)",
                    inline=True)

    info = a2s.info(SERVER_ADDRESS)
    embed.add_field(name="🎯 **Current Players**", value=f"• {info.player_count}/{info.max_players}", inline=False)

    # Footer with logo and a call to action
    embed.set_footer(
        text="Join the fun! 🕹️ | Arabian Servers for CS 1.6 since 2013",
        icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                 "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                 "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&"
    )
    # Send the embed as a response
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="players", description="Returns a table of the current players")
async def players(interaction: discord.Interaction):
    players_list = []
    players = a2s.players(SERVER_ADDRESS)
    if players:
        for player in players:
            players_list.append((player.name, player.score, player.duration))
        players_list.sort(key=lambda x: x[1], reverse=True)

        # Format as a table with proper alignment
        message = "**🏆 Online Players Leaderboard:**\n"
        message += "```\n"  # Start code block for better formatting
        message += f"{'Rank':<4} {'Player':<20} {'Score':<5} {'Time (m)':<8}\n"
        message += "-" * 42 + "\n"  # Horizontal separator

        for idx, (name, score, time) in enumerate(players_list, start=1):
            message += f"{idx:<4} {clean_name(name[:18]):<20} {score:<5} {round(time / 60, 2):<8}\n"
        message += "```\n"  # end code block
        await interaction.response.send_message(message)

# Escape backticks in names
def clean_name(name):
    return name.replace("`", "´")


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

@bot.command(name="top15")
async def top_prefix(ctx):
    page = 1
    leaderboard_str = top_logic(page)
    await ctx.send(leaderboard_str)

def top_logic(page: int):
    max_name_length = 15
    df = get_top_players(str(page))

    leaderboard_str = "```\n"
    leaderboard_str += "{:<5} {:<11} {:<20} {:<6} {:<10} {:<12} {:<6}\n".format("Rank", "XP", "Name", "Kills",
                                                                                       "Headshots", "Headshot %", "Skill")

    for index, row in df.iterrows():
        # Truncate player names if they are too long
        truncated_name = (row['Name'][:max_name_length] + '...') if len(row['Name']) > max_name_length else row['Name']

        leaderboard_str += "{:<5} {:<11} {:<20} {:<6} {:<10} {:<12} {:<6}\n".format(
            row['Rank'], row['XP'], truncated_name, row['Kills'], row['Headshots'], row['Headshot Percentages'],
            row['Skills']
        )

    leaderboard_str += "```"

    return leaderboard_str

# Create the slash command
@bot.tree.command(name="top", description="Displays the current leaderboard")
async def top(interaction: discord.Interaction, page:int = 1):
    if page < 1:
        await interaction.response.send_message(
            f"Page number must be higher than 1.",
            ephemeral=True
        )
        return

    # Generate the first page
    leaderboard_str = top_logic(page)

    # Create the buttons (Previous and Next)
    prev_button = Button(label="Previous Page", style=discord.ButtonStyle.secondary, disabled=True)
    next_button = Button(label="Next Page", style=discord.ButtonStyle.secondary)

    # Define the button actions
    async def on_prev_button_click(interaction: discord.Interaction):
        nonlocal page
        if page > 1:
            page -= 1
            leaderboard_str = top_logic(page)
            await interaction.response.edit_message(content=leaderboard_str, view=view)
        prev_button.disabled = (page == 1)
        # next_button.disabled = (page * ROWS_PER_PAGE >= len(df))
        await interaction.response.edit_message(view=view)

    async def on_next_button_click(interaction: discord.Interaction):
        nonlocal page
        page += 1
        leaderboard_str = top_logic(page)
        await interaction.response.edit_message(content=leaderboard_str, view=view)
        prev_button.disabled = (page == 1)
        # next_button.disabled = (page * ROWS_PER_PAGE >= len(df))
        await interaction.response.edit_message(view=view)

    # Add the actions to the buttons
    prev_button.callback = on_prev_button_click
    next_button.callback = on_next_button_click

    # Create a view for the buttons
    view = View()
    view.add_item(prev_button)
    view.add_item(next_button)

    # Send the message with the leaderboard and buttons
    await interaction.response.send_message(leaderboard_str, view=view)


handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
bot.run(token, log_handler=handler)