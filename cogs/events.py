"""
This cog handles various Discord server events.
"""
import discord
from discord.ext import commands
from utils.constants import LOGGING_CHANNEL_ID
class Events(commands.Cog):
    """Contains event listeners for bot events like command errors."""

    def __init__(self, bot):
        self.bot = bot

    ################ EVENT DISABLED ######################
    # The `on_member_join` event listener is currently disabled.
    # @commands.Cog.listener()
    # async def on_member_join(self, member):
    #     channel = member.guild.system_channel
    #     if channel:
    #         await channel.send(f"👋 Welcome, {member.mention}!")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """
        Logs command errors to a designated logging channel.

        Args:
            ctx: The context in which the command was invoked.
            error: The error that was raised.
        """
        channel = self.bot.get_channel(LOGGING_CHANNEL_ID)

        embed = discord.Embed(
            title="⚠️ Command Error",
            color=discord.Color.red()
        )
        embed.add_field(name="Command", value=ctx.command, inline=False)
        embed.add_field(name="Error", value=f"```{error}```", inline=False)
        embed.add_field(name="User", value=ctx.author.mention, inline=True)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.set_footer(text="Prefix Command Error Log")

        await channel.send(embed=embed)
        raise error

async def setup(bot):
    await bot.add_cog(Events(bot))