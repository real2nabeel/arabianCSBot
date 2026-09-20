import discord
from discord.ext import commands
from utils.constants import LOGGING_CHANNEL_ID
from utils.embeds import make_embed
from utils.server_management import log_code_block
class Events(commands.Cog):
    """Handles server events"""

    def __init__(self, bot):
        self.bot = bot

    ################ EVENT DISABLED ######################
    # @commands.Cog.listener()
    # async def on_member_join(self, member):
    #     channel = member.guild.system_channel
    #     if channel:
    #         await channel.send(f"👋 Welcome, {member.mention}!")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        channel = self.bot.get_channel(LOGGING_CHANNEL_ID)

        embed = make_embed(section="Staff logs",
            title="⚠️ Command Error",
            color=discord.Color.red()
        )
        embed.add_field(name="Command", value=str(ctx.command or "Unknown command"), inline=False)
        embed.add_field(name="Error", value=log_code_block(str(error)), inline=False)
        embed.add_field(name="User", value=ctx.author.mention, inline=True)
        embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
        embed.set_footer(text="Prefix Command Error Log")

        if channel is not None:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        raise error

async def setup(bot):
    await bot.add_cog(Events(bot))
