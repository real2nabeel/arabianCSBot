"""
This cog handles Counter-Strike server related commands and functionality.
"""
import a2s
import discord
from discord import app_commands
from discord.ext import commands

from utils.constants import SERVER_ADDRESS
from utils.player_stats import get_player_info_dict, get_top_players
from discord.ui import Button, View

class CsLogic(commands.Cog):
    """Contains commands for retrieving CS server information, player stats, and leaderboards."""
    def __init__(self, bot):
        self.bot = bot


    @app_commands.command(name="rankstats", description="Get stats for a player")
    async def rankstats(self, interaction: discord.Interaction, player_name: str):
        """
        Fetches and displays player statistics from rank.tornadosw.eu.

        Args:
            player_name (str): The name of the player to search for.

        Responds in two modes:
        - If a single player is found, displays their detailed statistics.
        - If multiple players are found with similar names, prompts the user to be more specific.
        """
        player_data, mode = get_player_info_dict(player_name)

        if not player_data:
            await interaction.response.send_message(
                f"Player '{player_name}' cannot be found. Please make sure you submit an actual player name.",
                ephemeral=True
            )
            return

        if mode == 0:
            embed = discord.Embed(title=f"**{player_data['Name']}'s Player Stats**", color=discord.Color.blue())

            embed.add_field(name="🏅 Rank", value=f"**{player_data['Rank Placement']} ({player_data['Rank']}**)",
                            inline=False)
            embed.add_field(name="▬" * 20, value="", inline=False)

            embed.add_field(name="🎯 K/D Ratio", value=f"**{player_data['K/D Ratio']}**", inline=True)
            embed.add_field(name="💀 Kills / Deaths", value=f"**{player_data['Kills']} / {player_data['Deaths']}**",
                            inline=True)
            embed.add_field(name="🩸 Headshots", value=f"**{player_data['Headshots']}**", inline=True)
            embed.add_field(name="🔫 Shots / Hits", value=f"**{player_data['Shots']} / {player_data['Hits']}**",
                            inline=True)
            embed.add_field(name="💥 Damage", value=f"**{player_data['Damage']}**", inline=True)

            embed.add_field(name="▬" * 20, value="", inline=False)
            embed.add_field(name="💣 C4 Stats",
                            value=f"Planted: **{player_data['C4 Planted']}** | Exploded: **{player_data['C4 Exploded']}** | Defused: **{player_data['C4 Defused']}**",
                            inline=False)

            embed.add_field(name="🏆 Most Valuable Player", value=f"**{player_data['Most Valuable Player']} Times MVP**",
                            inline=True)

            embed.add_field(name="▬" * 20, value="", inline=False)
            top_weapons = "\n".join(
                [f"{list(weapon.keys())[0]}: **{list(weapon.values())[0]}**" for weapon in player_data['Top Weapons']])
            embed.add_field(name="🔝 Top Weapons", value=top_weapons, inline=False)

            embed.add_field(name="▬" * 20, value="", inline=False)

            embed.add_field(name="⏱️ Total Played Time", value=f"**{player_data['Played Time']}**", inline=False)
            embed.add_field(name="📅 First Login", value=f"**{player_data['First Login']}**", inline=False)
            embed.add_field(name="📅 Last Login", value=f"**{player_data['Last Login']}**", inline=False)

            if interaction.response.is_done():
                await interaction.followup.send(embed=embed)
            else:
                await interaction.response.send_message(embed=embed)

        elif mode == 1:
            player_names = list(player_data.values())
            embed = discord.Embed(title="Too many players with similar username",
                                  description="",
                                  color=discord.Color.red())

            player_names_str = "`" + ", ".join(str(name) for name in player_names) + "`"
            embed.add_field(name=player_names_str, value="", inline=True)
            embed.add_field(name="", value="Please re-enter a more precise name (case-sensitive)", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ip", description="Returns an Embed of the Arabian IP")
    async def ip(self, interaction: discord.Interaction):
        """Displays the server IP, a welcome message, and some server stats."""
        embed = discord.Embed(
            title="**Welcome to Arabian Servers!**",
            description="Have fun and enjoy your stay! 🎮",
            color=discord.Color.orange(),
            url="https://arabian-servers.com",
        )

        embed.set_author(name="JOIN US!",
                         icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                                  "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                                  "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                                "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                                "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&")

        embed.add_field(name="🔥 **Server IP** 🔥", value="**`151.80.47.182:27015`**", inline=False)

        embed.add_field(name="📅 **Servers Running Since**", value="2013", inline=True)
        embed.add_field(name="🌍 **Join Now!**", value="[Click here to visit the website](https://arabian-servers.com)",
                        inline=True)

        info = a2s.info(SERVER_ADDRESS)
        embed.add_field(name="🎯 **Current Players**", value=f"• {info.player_count}/{info.max_players}", inline=False)

        embed.set_footer(
            text="Join the fun! 🕹️ | Arabian Servers for CS 1.6 since 2013",
            icon_url="https://cdn.discordapp.com/attachments/1098525304886153277/1336576486966038598/"
                     "arabian2016p1440.jpg?ex=67a44f5a&is=67a2fdda&hm="
                     "39a671b0c53cc993d4c606e0ce0309f450a318c264c3778f9b8efd21360edad4&"
        )

        await interaction.response.send_message(embed=embed)

    @staticmethod
    def top_logic(page: int):
        """
        Fetches and formats a page of the leaderboard data from rank.tornadosw.eu.

        Args:
            page (int): The page number of the leaderboard to fetch.

        Returns:
            str: A formatted string representing the leaderboard page.
                 The string is a code block containing a table with columns:
                 Rank, XP, Name, Kills, Headshots, Headshot %, Skill.
        """
        max_name_length = 15
        df = get_top_players(str(page))

        leaderboard_str = "```\n"
        leaderboard_str += "{:<5} {:<11} {:<20} {:<6} {:<10} {:<12} {:<6}\n".format("Rank", "XP", "Name", "Kills",
                                                                                    "Headshots", "Headshot %", "Skill")

        for index, row in df.iterrows():
            truncated_name = (row['Name'][:max_name_length] + '...') if len(row['Name']) > max_name_length else row[
                'Name']

            leaderboard_str += "{:<5} {:<11} {:<20} {:<6} {:<10} {:<12} {:<6}\n".format(
                row['Rank'], row['XP'], truncated_name, row['Kills'], row['Headshots'], row['Headshot Percentages'],
                row['Skills']
            )

        leaderboard_str += "```"

        return leaderboard_str

    @app_commands.command(name="top", description="Displays the current leaderboard")
    async def top(self, interaction: discord.Interaction, page: int = 1):
        """
        Displays a paginated leaderboard from rank.tornadosw.eu.

        Args:
            page (int, optional): The page number of the leaderboard to display. Defaults to 1.
        """
        if page < 1:
            await interaction.response.send_message(
                f"Page number must be higher than 1.",
                ephemeral=True
            )
            return

        leaderboard_str = self.top_logic(page)

        prev_button = Button(label="Previous Page", style=discord.ButtonStyle.secondary, disabled=True)
        next_button = Button(label="Next Page", style=discord.ButtonStyle.secondary)

        async def on_prev_button_click(interaction: discord.Interaction):
            """Handles the 'Previous Page' button click, loading and displaying the previous page of the leaderboard."""
            nonlocal page
            if page > 1:
                page -= 1
                leaderboard_str = self.top_logic(page)
                await interaction.response.edit_message(content=leaderboard_str, view=view)
            prev_button.disabled = (page == 1)
            # next_button.disabled = (page * ROWS_PER_PAGE >= len(df))
            await interaction.response.edit_message(view=view)

        async def on_next_button_click(interaction: discord.Interaction):
            """Handles the 'Next Page' button click, loading and displaying the next page of the leaderboard."""
            nonlocal page
            page += 1
            leaderboard_str = self.top_logic(page)
            await interaction.response.edit_message(content=leaderboard_str, view=view)
            prev_button.disabled = (page == 1)
            # next_button.disabled = (page * ROWS_PER_PAGE >= len(df))
            await interaction.response.edit_message(view=view)

        prev_button.callback = on_prev_button_click
        next_button.callback = on_next_button_click

        view = View()
        view.add_item(prev_button)
        view.add_item(next_button)

        await interaction.response.send_message(leaderboard_str, view=view)

    ####################### COMMAND DISABLED ###################################

    # The 'players' command is currently disabled.
    # @commands.command(name="players", description="Returns a table of the current players")
    # async def players(self, interaction: discord.Interaction):
    #     players_list = []
    #     players = a2s.players(SERVER_ADDRESS)
    #     if players:
    #         for player in players:
    #             players_list.append((player.name, player.score, player.duration))
    #         players_list.sort(key=lambda x: x[1], reverse=True)
    #
    #         message = "**🏆 Online Players Leaderboard:**\n"
    #         message += "```\n"
    #         message += f"{'Rank':<4} {'Player':<20} {'Score':<5} {'Time (m)':<8}\n"
    #         message += "-" * 42 + "\n"
    #         for idx, (name, score, time) in enumerate(players_list, start=1):
    #             message += f"{idx:<4} {clean_name(name[:18]):<20} {score:<5} {round(time / 60, 2):<8}\n"
    #         message += "```\n"
    #         await interaction.response.send_message(message)


async def setup(bot):
    await bot.add_cog(CsLogic(bot))
