"""One live dashboard and opt-in population alerts for the configured server."""
import asyncio
from datetime import timedelta
from io import BytesIO
import logging
import time

import a2s
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.constants import (
    GUILD_ID, SERVER_ADDRESS, DASHBOARD_CHANNEL_ID, ACTIVITY_ALERT_CHANNEL_ID,
    ACTIVITY_ALERT_ROLE_ID, SERVER_POLL_SECONDS, DASHBOARD_REFRESH_SECONDS,
    ACTIVITY_HUMAN_THRESHOLD, ACTIVITY_SUSTAIN_SECONDS, ACTIVITY_REARM_BELOW,
    ACTIVITY_REARM_SECONDS, ACTIVITY_COOLDOWN_SECONDS, AUTO_ROLE_IDS, LEADERBOARD_REFRESH_SECONDS,
    STAFF_ACTIVITY_CHANNEL_ID, ADMIN_FLAG, ACTIVITY_REFRESH_SECONDS, ACTIVITY_HISTORY_DAYS,
    ACTIVITY_UTC_OFFSET,
)
from utils.activity import (
    PERIOD_OPTIONS, AdminTracker, admin_rows, build_series, day_key, format_admin_table,
    format_player_months, month_key, month_readings, period_for, render_activity_graph, zone_label,
)
from utils.embeds import make_embed
from utils.server_management import log_code_block
from utils.leaderboard_image import render_leaderboard
from utils.server_monitor import ActivityWindow, human_count

logger = logging.getLogger(__name__)
SERVER_KEY = f"{SERVER_ADDRESS[0]}:{SERVER_ADDRESS[1]}"
PERIOD_SELECT_ID = "activity_graph:period"
PERIOD_KEYS = {key for key, _ in PERIOD_OPTIONS}
PLAYER_MONTHS_SECONDS = 600  # how often the rank table is counted for players per month


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
        self.admin_tracker = AdminTracker(max_gap=SERVER_POLL_SECONDS * 2 + 10)
        self.last_activity_post = None
        self.last_prune = None
        self.last_player_months = None
        self.graph_period = "24h"
        self.period_view = None

    async def cog_load(self):
        if not GUILD_ID:
            if DASHBOARD_CHANNEL_ID or ACTIVITY_ALERT_CHANNEL_ID or STAFF_ACTIVITY_CHANNEL_ID:
                raise ValueError("GUILD_ID is required for the server dashboard/alerts")
            return
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
        if ACTIVITY_REFRESH_SECONDS < SERVER_POLL_SECONDS:
            raise ValueError("Activity refresh must be >= polling interval")
        if ACTIVITY_HISTORY_DAYS < 2:
            raise ValueError("ACTIVITY_HISTORY_DAYS must be at least 2 for the 24-hour graph")
        if not -12 <= ACTIVITY_UTC_OFFSET <= 14:
            raise ValueError("ACTIVITY_UTC_OFFSET must be between -12 and 14")
        if len(ADMIN_FLAG) != 1 or not ADMIN_FLAG.isalpha() or not ADMIN_FLAG.islower():
            raise ValueError("ADMIN_FLAG must be a single lowercase AMX Mod X flag letter")
        await self.bot.db_bot.ensure_server_monitor_schema()
        await self.bot.db_bot.ensure_activity_schema()
        await self.bot.db_bot.ensure_player_months_schema()
        # Keep the graph's period dropdown working on messages posted before a restart.
        self.period_view = self.graph_view(self.graph_period)[0]
        self.bot.add_view(self.period_view)
        if DASHBOARD_CHANNEL_ID:
            await self.bot.db_bot.ensure_leaderboard_schema()
        self.poll.change_interval(seconds=SERVER_POLL_SECONDS)
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()
        if self.period_view is not None:
            self.period_view.stop()  # drop the restart handler with the cog

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

    # ---------------- activity recording ----------------
    async def record_players(self, info, wall):
        await self.bot.db_bot.add_activity_sample(SERVER_KEY, wall, human_count(info))

    async def record_admins(self, info, wall, now):
        if info is None:
            # Offline server: the rank table's Online flags can be stale.
            self.admin_tracker.observe(None, now)
            return
        try:
            admins = await self.bot.db_live.get_admins(ADMIN_FLAG)
        except Exception:
            self.admin_tracker.observe(None, now)
            raise
        online = [a for a in admins if a["online"]]
        seconds, credited = self.admin_tracker.observe({a["steam_id"] for a in online}, now)
        if credited:
            await self.bot.db_bot.credit_admin_time(
                SERVER_KEY, day_key(wall, ACTIVITY_UTC_OFFSET), seconds, sorted(credited))
        if online:
            await self.bot.db_bot.mark_admins_seen(
                SERVER_KEY, [(a["steam_id"], a["nick"]) for a in online], wall)

    async def prune_samples(self, wall, now):
        if self.last_prune is not None and now - self.last_prune < 3600:
            return
        self.last_prune = now
        await self.bot.db_bot.prune_activity_samples(SERVER_KEY, wall - ACTIVITY_HISTORY_DAYS * 86400)

    async def record_player_months(self, wall, now):
        if self.last_player_months is not None and now - self.last_player_months < PLAYER_MONTHS_SECONDS:
            return
        self.last_player_months = now
        first = await self.bot.db_live.count_players_by_month("First Login")
        last = await self.bot.db_live.count_players_by_month("Last Login")
        saved = await self.bot.db_bot.get_player_months(SERVER_KEY)
        rows = month_readings(first, last, saved, month_key(wall, ACTIVITY_UTC_OFFSET))
        await self.bot.db_bot.save_player_months(SERVER_KEY, rows)

    async def player_months_text(self):
        """The players-per-month table for the graph card, or None before anything is saved."""
        table = format_player_months(await self.bot.db_bot.get_player_months(SERVER_KEY))
        if table is None:
            return None
        rows, note = table
        return f"**Players per month**\n{log_code_block(rows)}\n-# {note}"

    async def safe_player_months_text(self):
        """Same, but a database hiccup only drops the table, never the graph."""
        try:
            return await self.player_months_text()
        except Exception:
            logger.exception("Could not read players per month")
            return None

    # ---------------- activity output ----------------
    async def activity_png(self, key):
        end = time.time()
        first = await self.bot.db_bot.get_first_activity_ts(SERVER_KEY)
        period = period_for(key, first, end)
        fetch = self.bot.db_bot.get_hourly_buckets if period.hourly else self.bot.db_bot.get_activity_buckets
        rows = await fetch(SERVER_KEY, end - period.seconds - period.bucket, period.bucket, ACTIVITY_UTC_OFFSET * 3600)
        start, points = build_series(rows, period, end, ACTIVITY_UTC_OFFSET)
        png = await asyncio.to_thread(render_activity_graph, points, start, period, discord.utils.utcnow(),
                                      ACTIVITY_UTC_OFFSET, first_ts=first)
        return png, period

    def graph_view(self, key, period=None, months_text=None):
        """The graph card: the image, a dropdown to change its time span, and players per month."""
        select = discord.ui.Select(
            custom_id=PERIOD_SELECT_ID, placeholder="Time span",
            options=[discord.SelectOption(label=label, value=value, default=value == key)
                     for value, label in PERIOD_OPTIONS],
        )
        select.callback = self.on_period_selected
        description = f"DD2 players, {period.label.lower()}: average and peak." if period else "DD2 players"
        items = [
            discord.ui.MediaGallery(discord.MediaGalleryItem("attachment://dd2-activity.png",
                                                             description=description)),
            discord.ui.ActionRow(select),
        ]
        if months_text:
            items += [discord.ui.Separator(), discord.ui.TextDisplay(months_text)]
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(discord.ui.Container(*items))
        return view, description

    def graph_file(self, png, description):
        return discord.File(BytesIO(png), filename="dd2-activity.png", description=description)

    async def on_period_selected(self, interaction: discord.Interaction):
        key = (interaction.data.get("values") or [None])[0]
        if key not in PERIOD_KEYS:
            await interaction.response.send_message("That time span is not available.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            png, period = await self.activity_png(key)
        except Exception:
            logger.exception("Could not draw the %s activity graph", key)
            await interaction.followup.send("Couldn't draw that graph. Try again shortly.", ephemeral=True)
            return
        self.graph_period = key  # the 10-minute refresh keeps the chosen span
        view, description = self.graph_view(key, period, await self.safe_player_months_text())
        file = self.graph_file(png, description)
        try:
            await interaction.edit_original_response(attachments=[file], view=view)
        finally:
            file.close()

    async def admin_activity_embed(self):
        admins = await self.bot.db_live.get_admins(ADMIN_FLAG)
        wall = time.time()
        today = day_key(wall, ACTIVITY_UTC_OFFSET)
        activity = await self.bot.db_bot.get_admin_activity(
            SERVER_KEY, today - timedelta(days=6), today - timedelta(days=29))
        rows = admin_rows(admins, activity, wall)
        online = sum(1 for row in rows if row["online"])
        embed = make_embed(
            section="Staff", title="🛡️ Admin activity",
            description=log_code_block(format_admin_table(rows)) if rows else "No admins found in the rank table.",
        )
        embed.add_field(name="Admins", value=str(len(rows)))
        embed.add_field(name="Online now", value=str(online))
        embed.set_footer(text=f"Hours on DD2 · days end at midnight {zone_label(ACTIVITY_UTC_OFFSET)} · "
                              "Season is rank system play time • Updated")
        return embed

    async def upsert_message(self, kind, channel, **payload):
        """Edit this bot's stored message of ``kind``, or post and remember a new one."""
        message_id = self.message_ids.get(kind) or await self.bot.db_bot.get_monitor_message_id(
            GUILD_ID, SERVER_KEY, kind)
        message = None
        if message_id:
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                pass
        if message is not None and message.author.id != self.bot.user.id:
            raise ValueError(f"Stored {kind} message is not owned by this bot")
        payload["allowed_mentions"] = discord.AllowedMentions.none()
        if message is None:
            if "file" in payload:
                payload["files"] = [payload.pop("file")]
            message = await channel.send(**payload)
            self.message_ids[kind] = message.id
            await self.bot.db_bot.set_monitor_message_id(GUILD_ID, SERVER_KEY, kind, message.id)
        else:
            if "file" in payload:
                payload["attachments"] = [payload.pop("file")]
            await message.edit(**payload)
            self.message_ids[kind] = message.id
        return message

    def staff_channel(self):
        channel = self.channel(STAFF_ACTIVITY_CHANNEL_ID)
        if channel.permissions_for(channel.guild.default_role).view_channel:
            raise ValueError("STAFF_ACTIVITY_CHANNEL_ID must be a private staff channel")
        return channel

    async def post_activity_graph(self):
        png, period = await self.activity_png(self.graph_period)
        view, description = self.graph_view(self.graph_period, period, await self.safe_player_months_text())
        file = self.graph_file(png, description)
        try:
            await self.upsert_message("activity_graph", self.staff_channel(), view=view, file=file)
        finally:
            file.close()

    async def post_admin_activity(self):
        await self.upsert_message("admin_activity", self.staff_channel(), embed=await self.admin_activity_embed())

    # ---------------- slash commands ----------------
    @app_commands.command(name="server-activity", description="[Admin] Players on the DD2 server over time")
    @app_commands.describe(period="Time span to show (default: last 24 hours)")
    @app_commands.choices(period=[app_commands.Choice(name=label, value=value) for value, label in PERIOD_OPTIONS])
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def server_activity(self, interaction: discord.Interaction,
                              period: app_commands.Choice[str] | None = None):
        key = period.value if period else "24h"
        await interaction.response.defer(ephemeral=True)
        png, _ = await self.activity_png(key)
        await interaction.followup.send(content=await self.safe_player_months_text(),
                                        file=discord.File(BytesIO(png), filename=f"dd2-activity-{key}.png"),
                                        ephemeral=True)

    @app_commands.command(name="admin-activity", description="[Admin] Hours each admin has spent on the DD2 server")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def admin_activity(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=await self.admin_activity_embed(), ephemeral=True)

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
            wall = time.time()
            for step in (self.record_players(info, wall), self.record_admins(info, wall, now),
                         self.prune_samples(wall, now), self.record_player_months(wall, now)):
                try:
                    await step
                except Exception:
                    logger.exception("Activity recording failed")
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
            if self.last_activity_post is None or now - self.last_activity_post >= ACTIVITY_REFRESH_SECONDS:
                self.last_activity_post = now
                if STAFF_ACTIVITY_CHANNEL_ID:
                    for post, what in ((self.post_activity_graph, "server activity graph"),
                                       (self.post_admin_activity, "admin activity table")):
                        try:
                            await post()
                        except Exception:
                            logger.exception("Could not refresh the %s", what)
        except Exception:
            self.window.high_since = self.window.low_since = None
            logger.exception("Server monitor iteration failed")

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(ServerMonitor(bot))
