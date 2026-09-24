"""One live dashboard and opt-in population alerts for the configured server."""
import asyncio
from io import BytesIO
import logging
import time

import a2s
import discord
from discord.ext import commands, tasks

from utils.constants import (
    GUILD_ID, SERVER_ADDRESS, DASHBOARD_CHANNEL_ID, ACTIVITY_ALERT_CHANNEL_ID,
    ACTIVITY_ALERT_ROLE_ID, SERVER_POLL_SECONDS, DASHBOARD_REFRESH_SECONDS,
    ACTIVITY_HUMAN_THRESHOLD, ACTIVITY_SUSTAIN_SECONDS, ACTIVITY_REARM_BELOW,
    ACTIVITY_REARM_SECONDS, ACTIVITY_COOLDOWN_SECONDS, AUTO_ROLE_IDS, LEADERBOARD_REFRESH_SECONDS,
)
from utils.embeds import make_embed
from utils.server_management import log_code_block
from utils.leaderboard_image import render_leaderboard
from utils.server_monitor import ActivityWindow, human_count

logger = logging.getLogger(__name__)
SERVER_KEY = f"{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}"


class ServerMonitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.window = ActivityWindow(
            threshold=ACTIVITY_HUMAN_THRESHOLD, sustain=ACTIVITY_SUSTAIN_SECONDS,
            rearm_below=ACTIVITY_REARM_BELOW, rearm_seconds=ACTIVITY_REARM_SECONDS,
            cooldown=ACTIVITY_COOLDOWN_SECONDS, max_gap=SERVER_POLL_SECONDS * 2 + 10,
        )
        self.last_success = None
        self.last_dashboard = None
        self.message_ids = {}
        self.last_leaderboard = None
        self.leaderboard_rows = None
        self.leaderboard_png = None
        self.leaderboard_updated = None

    async def cog_load(self):
        if not (DASHBOARD_CHANNEL_ID or ACTIVITY_ALERT_CHANNEL_ID):
            return
        if not GUILD_ID:
            raise ValueError("GUILD_ID is required for the server dashboard/alerts")
        if SERVER_POLL_SECONDS < 10 or DASHBOARD_REFRESH_SECONDS < SERVER_POLL_SECONDS:
            raise ValueError("Use polling >=10 seconds and dashboard refresh >= polling")
        if not 0 < ACTIVITY_REARM_BELOW < ACTIVITY_HUMAN_THRESHOLD:
            raise ValueError("Alert threshold must exceed the positive re-arm threshold")
        if min(ACTIVITY_SUSTAIN_SECONDS, ACTIVITY_REARM_SECONDS, ACTIVITY_COOLDOWN_SECONDS) <= 0:
            raise ValueError("Activity timing settings must be positive")
        if ACTIVITY_ALERT_CHANNEL_ID and not ACTIVITY_ALERT_ROLE_ID:
            raise ValueError("ACTIVITY_ALERT_ROLE_ID is required when alerts are enabled")
        if ACTIVITY_ALERT_CHANNEL_ID and ACTIVITY_ALERT_ROLE_ID in AUTO_ROLE_IDS:
            raise ValueError("The opt-in activity role must not be in AUTO_ROLE_IDS")
        if LEADERBOARD_REFRESH_SECONDS < SERVER_POLL_SECONDS:
            raise ValueError("Leaderboard refresh must be >= polling interval")
        await self.bot.db_bot.ensure_server_monitor_schema()
        if DASHBOARD_CHANNEL_ID:
            await self.bot.db_bot.ensure_leaderboard_schema()
        self.poll.change_interval(seconds=SERVER_POLL_SECONDS)
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    def channel(self, channel_id):
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
            raise ValueError(f"Configured channel {channel_id} must be a text channel in GUILD_ID")
        return channel

    def dashboard_embed(self, info):
        online = info is not None
        embed = make_embed(
            section="Counter-Strike 1.6", title="🎮 DD2 Server",
            description="🟢 Online" if online else "🔴 Server unreachable · Retrying shortly",
            **({} if online else {"color": discord.Colour.red()}),
        )
        embed.add_field(name="🗺️ Current map", value=log_code_block(info.map_name) if online else "Unavailable")
        players = f"**{info.player_count} / {info.max_players}**" if online else "Unavailable"
        embed.add_field(name="👥 Players", value=players)
        embed.add_field(name="Join from your CS console", value=log_code_block(f"connect {SERVER_KEY}"), inline=False)
        embed.add_field(name="🌐 Website", value="[arabian-servers.com](https://arabian-servers.com)", inline=False)
        if not online and self.last_success is not None:
            embed.add_field(name="Last successful check", value=f"<t:{int(self.last_success)}:R>", inline=False)
        embed.set_footer(text=f"Refreshes every {DASHBOARD_REFRESH_SECONDS}s • Last checked")
        return embed

    async def remove_old_panel(self, row):
        if not row["panel_id"]:
            return
        # The old schema did not store channel_id; locate only this exact bot
        # message in configured channels. Never delete arbitrary channel history.
        found = False
        for channel_id in {ACTIVITY_ALERT_CHANNEL_ID, DASHBOARD_CHANNEL_ID} - {0}:
            channel = self.channel(channel_id)
            try:
                message = await channel.fetch_message(row["panel_id"])
            except discord.NotFound:
                continue
            if message.author.id != self.bot.user.id:
                raise ValueError("Stored subscription panel is not owned by this bot")
            await message.delete()
            found = True
            break
        if not found:
            logger.info("Old alert panel is missing or in a previously configured channel")
        await self.bot.db_bot.set_monitor_message(GUILD_ID, SERVER_KEY, "panel_id", None)

    async def update_leaderboard(self):
        channel = self.channel(DASHBOARD_CHANNEL_ID)
        saved = await self.bot.db_bot.get_leaderboard_message(GUILD_ID, SERVER_KEY)
        message_id = self.message_ids.get("leaderboard_id") or (saved["message_id"] if saved else None)
        message = None
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                pass
        players, _ = await self.bot.db_live.get_top_players(page=1, per_page=50)
        changed = players != self.leaderboard_rows or self.leaderboard_png is None
        if changed:
            updated = discord.utils.utcnow()
            png = await asyncio.to_thread(render_leaderboard, players, updated)
        else:
            updated, png = self.leaderboard_updated, self.leaderboard_png
        if message is not None and message.author.id != self.bot.user.id:
            raise ValueError("Stored leaderboard is not owned by this bot")
        if changed or message is None:
            # The artwork already contains the title and update time.
            view = discord.ui.LayoutView(timeout=None)
            view.add_item(discord.ui.Container(discord.ui.MediaGallery(
                discord.MediaGalleryItem(
                    "attachment://dd2-top-50.png",
                    description="DD2 season top 50: ranks, kills, deaths, headshots and player names.",
                ),
            )))
            file = discord.File(BytesIO(png), filename="dd2-top-50.png",
                                description="DD2 season top 50: ranks, kills, deaths, headshots and player names.")
            try:
                if message is None:
                    message = await channel.send(view=view, file=file,
                                                 allowed_mentions=discord.AllowedMentions.none())
                    self.message_ids["leaderboard_id"] = message.id
                else:
                    # Clear legacy text/embeds while converting the existing message to V2.
                    await message.edit(content=None, embed=None, attachments=[file], view=view,
                                       allowed_mentions=discord.AllowedMentions.none())
            finally:
                file.close()
            self.leaderboard_rows, self.leaderboard_png = players, png
            self.leaderboard_updated = updated
        if not saved or saved["message_id"] != message.id:
            await self.bot.db_bot.set_leaderboard_message(GUILD_ID, SERVER_KEY, message.id)

    async def update_message(self, row, field, channel_id, embed, *, view=None):
        channel = self.channel(channel_id)
        message_id = self.message_ids.get(field) or row[field]
        message = None
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                pass  # Deleted message or changed channel: create a replacement.
        if message is not None:
            if message.author.id != self.bot.user.id:
                raise ValueError("Stored monitor message is not owned by this bot")
            await message.edit(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        else:
            message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
            # Remember immediately, even if saving the ID temporarily fails.
            self.message_ids[field] = message.id
        if row[field] != message.id:
            await self.bot.db_bot.set_monitor_message(GUILD_ID, SERVER_KEY, field, message.id)
        if field == "dashboard_id" and not message.pinned and channel.permissions_for(channel.guild.me).manage_messages:
            try:
                await message.pin(reason="Live server dashboard")
            except discord.HTTPException:
                logger.exception("Could not pin server dashboard")

    async def activity(self, row, info, humans, now):
        action = self.window.observe(humans, now=now, wall_time=time.time(),
                                     armed=bool(row["armed"]), last_alert=row["last_alert"])
        if action == "rearm":
            await self.bot.db_bot.rearm_server_alert(GUILD_ID, SERVER_KEY)
        elif action == "alert":
            channel = self.channel(ACTIVITY_ALERT_CHANNEL_ID)
            guild = channel.guild
            role = guild.get_role(ACTIVITY_ALERT_ROLE_ID)
            if role is None or role.is_default():
                raise ValueError("Activity alert role is missing or is @everyone")
            permissions = channel.permissions_for(guild.me)
            if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
                raise ValueError("Missing permissions to send activity alerts")
            if not role.mentionable and not permissions.mention_everyone:
                raise ValueError("Bot needs Mention Everyone permission to ping the non-mentionable alert role")
            embed = make_embed(section="Server alerts", title="🎮 The server is getting active!",
                               description=f"**{humans} players in game!** Come join the match!")
            embed.add_field(name="🗺️ Current map", value=log_code_block(info.map_name))
            embed.add_field(name="Available slots", value=str(max(0, info.max_players - info.player_count)))
            embed.add_field(name="Join from your CS console", value=log_code_block(f"connect {SERVER_KEY}"), inline=False)
            if await self.bot.db_bot.claim_server_alert(GUILD_ID, SERVER_KEY, time.time(), ACTIVITY_COOLDOWN_SECONDS):
                await channel.send(content=role.mention, embed=embed, allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[role], replied_user=False,
                ))

    @tasks.loop(seconds=30)
    async def poll(self):
        try:
            row = await self.bot.db_bot.get_server_monitor(GUILD_ID, SERVER_KEY)
            try:
                await self.remove_old_panel(row)
            except Exception:
                logger.exception("Could not remove the old alert subscription panel")
            try:
                info = await a2s.ainfo(SERVER_ADDRESS, timeout=5)
                self.last_success = time.time()
            except Exception:
                info = None
            now = time.monotonic()
            if ACTIVITY_ALERT_CHANNEL_ID:
                try:
                    await self.activity(row, info, human_count(info), now)
                except Exception:
                    logger.exception("Activity alert update failed")
            if self.last_dashboard is None or now - self.last_dashboard >= DASHBOARD_REFRESH_SECONDS:
                self.last_dashboard = now
                if DASHBOARD_CHANNEL_ID:
                    try:
                        await self.update_message(row, "dashboard_id", DASHBOARD_CHANNEL_ID,
                                                  self.dashboard_embed(info))
                    except Exception:
                        logger.exception("Could not update dashboard")
            if DASHBOARD_CHANNEL_ID and (self.last_leaderboard is None or
                    now - self.last_leaderboard >= LEADERBOARD_REFRESH_SECONDS):
                self.last_leaderboard = now
                try:
                    await self.update_leaderboard()
                except Exception:
                    logger.exception("Could not refresh season leaderboard")
        except Exception:
            self.window.high_since = self.window.low_since = None
            logger.exception("Server monitor iteration failed")

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ServerMonitor(bot))
