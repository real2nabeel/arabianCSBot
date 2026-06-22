import os

import discord
from discord.ext import commands

from utils.constants import (
    TOKEN, GUILD_ID, DB_CONFIG_LIVE, DB_CONFIG_HISTORY, DB_CONFIG_BOT,
)
from utils.database import Database


class ArabianBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        # Members intent (privileged — enable "Server Members Intent" in the
        # Discord Developer Portal) is required so the leveling cog can resolve
        # members and assign level roles reliably. voice_states is on by default.
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        # Two schemas on the same MySQL server: the live (current) ranking and
        # the historical ranking. Each command has a live and a -history variant.
        self.db_live = Database(DB_CONFIG_LIVE)
        self.db_history = Database(DB_CONFIG_HISTORY)
        # Bot-owned schema for the Discord activity leveling system (XP, level
        # roles) — kept separate from the game ranking data.
        self.db_bot = Database(DB_CONFIG_BOT)
        # Default alias kept for any code that just wants "the" DB (live).
        self.db = self.db_live

    async def setup_hook(self):
        """Runs once before the bot connects. Opens the DB pools, loads cogs
        and syncs the slash-command tree."""
        await self.db_live.connect()
        await self.db_history.connect()
        await self.db_bot.ensure_database_exists()
        await self.db_bot.connect()
        await self.db_bot.ensure_leveling_schema()

        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                await self.load_extension(f"cogs.{filename[:-3]}")

        if GUILD_ID:
            # Scope every command to the single allowed guild. This makes the
            # commands appear only in that server and updates instantly.
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

    async def on_guild_join(self, guild: discord.Guild):
        """Leave any server that isn't the configured one."""
        if GUILD_ID and guild.id != GUILD_ID:
            await guild.leave()

    async def close(self):
        await self.db_live.close()
        await self.db_history.close()
        await self.db_bot.close()
        await super().close()


def main():
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    bot = ArabianBot()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
