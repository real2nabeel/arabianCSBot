import discord
from discord.ext import commands

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    ####################### COMMAND DISABLED ###################################

    # @commands.command()
    # @commands.has_permissions(ban_members=True)
    # async def ban(self, ctx, member: discord.Member, *, reason=None):
    #     await member.ban(reason=reason)
    #     await ctx.send(f'Banned {member}')


    ####################### COMMAND DISABLED ###################################

    # @commands.command()
    # @commands.has_permissions(kick_members=True)
    # async def kick(self, ctx, member: discord.Member, *, reason=None):
    #     await member.kick(reason=reason)
    #     await ctx.send(f'Kicked {member}')


async def setup(bot):
    await bot.add_cog(Moderation(bot))
    