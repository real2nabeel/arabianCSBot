"""Highlight clips: review in Discord, then post to social media.

The host-side job (clips/nightly.py) writes finished clips into CLIPS_DIR/<clip id>/ with meta.json, discord.mp4
(small, for review) and hq.mp4 (for the platforms). Every CLIPS_CHECK_MINUTES this cog:

1. posts each new clip to the review channel with 👍 and ❌;
2. posts the oldest approved clip to each enabled platform when that platform is allowed to post (daily limit,
   gap between posts, posting hours), and adds the links to the review message.

Only 👍/❌ from members with a role in CLIPS_APPROVER_ROLE_IDS (or Administrator) count; a ❌ wins. A blank
CLIPS_REVIEW_CHANNEL_ID turns the cog off.
"""
import asyncio
import datetime as dt
import json
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import clips as logic
from utils import social
from utils.constants import (
    ACTIVITY_UTC_OFFSET, CLIPS_APPROVER_ROLE_IDS, CLIPS_CAPTION, CLIPS_CHECK_MINUTES, CLIPS_DIR, CLIPS_HASHTAGS,
    CLIPS_PLATFORMS, CLIPS_POST_GAP_MINUTES, CLIPS_POST_HOURS, CLIPS_POSTS_PER_DAY, CLIPS_REVIEW_CHANNEL_ID,
    CLIPS_SERVER_ADDRESS, GUILD_ID, META_GRAPH_VERSION, META_IG_ID, META_PAGE_ID, META_TOKEN, TIKTOK_CLIENT_FILE,
    TIKTOK_MODE, TIKTOK_TOKEN_FILE, YOUTUBE_PRIVACY, YOUTUBE_TOKEN_FILE,
)

PLATFORM_NAMES = {"facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube", "tiktok": "TikTok"}
MAX_ATTEMPTS = 3
COLORS = {"pending": 0xF1C40F, "approved": 0x2ECC71, "rejected": 0x95A5A6}


class Clips(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.hours = logic.parse_hours(CLIPS_POST_HOURS)
        self.uploaders = {}

    async def cog_load(self):
        if not CLIPS_REVIEW_CHANNEL_ID:
            return
        if not GUILD_ID:
            raise ValueError("GUILD_ID is required for clip reviews")
        unknown = set(CLIPS_PLATFORMS) - set(PLATFORM_NAMES)
        if unknown:
            raise ValueError(f"Unknown CLIPS_PLATFORMS: {', '.join(sorted(unknown))}")
        if {"facebook", "instagram"} & set(CLIPS_PLATFORMS):
            meta = social.Meta(META_TOKEN, META_PAGE_ID, META_IG_ID, META_GRAPH_VERSION)
            if "facebook" in CLIPS_PLATFORMS:
                if not (META_TOKEN and META_PAGE_ID):
                    raise ValueError("META_TOKEN and META_PAGE_ID are required to post to Facebook")
                self.uploaders["facebook"] = lambda c: meta.facebook_reel(c["hq"], c["caption"])
            if "instagram" in CLIPS_PLATFORMS:
                if not (META_TOKEN and META_IG_ID):
                    raise ValueError("META_TOKEN and META_IG_ID are required to post to Instagram")
                self.uploaders["instagram"] = lambda c: meta.instagram_reel(c["hq"], c["caption"])
        if "youtube" in CLIPS_PLATFORMS:
            yt = social.YouTube(YOUTUBE_TOKEN_FILE, YOUTUBE_PRIVACY)
            self.uploaders["youtube"] = lambda c: yt.short(c["hq"], logic.title(c["meta"]), c["caption"])
        if "tiktok" in CLIPS_PLATFORMS:
            tt = social.TikTok(TIKTOK_CLIENT_FILE, TIKTOK_TOKEN_FILE, TIKTOK_MODE)
            self.uploaders["tiktok"] = lambda c: tt.video(c["hq"], c["caption"])
        await self.bot.db_bot.ensure_clips_schema()
        self.check.change_interval(minutes=max(1, CLIPS_CHECK_MINUTES))
        self.check.start()

    def cog_unload(self):
        self.check.cancel()

    # ------------------------------------------------------------------ #
    # Loop
    # ------------------------------------------------------------------ #
    @tasks.loop(minutes=10)
    async def check(self):
        try:
            await self.post_new_clips()
        except Exception as e:
            print(f"[clips] posting new clips failed: {type(e).__name__}: {e}")
        try:
            await self.post_approved()
        except Exception as e:
            print(f"[clips] posting approved clips failed: {type(e).__name__}: {e}")

    @check.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    def _local_now(self):
        return dt.datetime.utcnow() + dt.timedelta(hours=ACTIVITY_UTC_OFFSET)

    async def _channel(self):
        return self.bot.get_channel(CLIPS_REVIEW_CHANNEL_ID) or await self.bot.fetch_channel(CLIPS_REVIEW_CHANNEL_ID)

    @staticmethod
    def _ready_clips():
        """{clip_id: meta} for finished clip folders (complete folders only; nightly.py renames them into place)."""
        out = {}
        if not os.path.isdir(CLIPS_DIR):
            return out
        for name in sorted(os.listdir(CLIPS_DIR)):
            folder = os.path.join(CLIPS_DIR, name)
            if name.endswith((".part", ".old")) or not os.path.isfile(os.path.join(folder, "discord.mp4")):
                continue
            try:
                out[name] = json.load(open(os.path.join(folder, "meta.json"), encoding="utf8"))
            except (OSError, ValueError):
                continue
        return out

    def _embed(self, meta, status, posts=()):
        embed = discord.Embed(title=f"🎬 {meta.get('player', '?')} – {meta.get('summary', '')}",
                              color=COLORS.get(status, COLORS["pending"]))
        when = meta.get("date", "")[:16]
        embed.description = (f"**{meta.get('map', '')}** · round {meta.get('round', '?')} · {when}\n"
                             f"Score {meta.get('score', '?')} · {meta.get('length', '?')} s")
        links = [f"[{PLATFORM_NAMES[p['platform']]}]({p['url']})" if p.get("url") else PLATFORM_NAMES[p["platform"]]
                 for p in posts if p["status"] == "posted"]
        if links:
            embed.add_field(name="Posted", value=" · ".join(links), inline=False)
        footer = {"pending": f"{logic.APPROVE} post it · {logic.REJECT} skip it",
                  "approved": "Approved: queued for posting", "rejected": "Rejected: won't be posted"}
        embed.set_footer(text=footer.get(status, ""))
        return embed

    async def post_new_clips(self):
        ready = await asyncio.get_running_loop().run_in_executor(None, self._ready_clips)
        if not ready:
            return
        known = await self.bot.db_bot.get_clip_ids()
        channel = None
        for clip_id, meta in ready.items():
            if clip_id in known:
                continue
            channel = channel or await self._channel()
            path = os.path.join(CLIPS_DIR, clip_id, "discord.mp4")
            msg = await channel.send(embed=self._embed(meta, "pending"), file=discord.File(path, filename=f"{clip_id}.mp4"))
            await msg.add_reaction(logic.APPROVE)
            await msg.add_reaction(logic.REJECT)
            await self.bot.db_bot.add_clip(clip_id, json.dumps(meta, ensure_ascii=False), channel.id, msg.id)

    async def post_approved(self):
        if not self.uploaders:
            return
        now = self._local_now()
        approved = await self.bot.db_bot.get_approved_clips()
        if not approved:
            return
        offset = dt.timedelta(hours=ACTIVITY_UTC_OFFSET)
        for platform, upload in self.uploaders.items():
            rows = await self.bot.db_bot.get_clip_posts(platform=platform)
            posted_times = [r["posted_at"] + offset for r in rows if r["status"] == "posted" and r["posted_at"]]
            if not logic.may_post(now, self.hours, posted_times, CLIPS_POSTS_PER_DAY, CLIPS_POST_GAP_MINUTES):
                continue
            finished = {r["clip_id"] for r in rows if r["status"] == "posted" or r["attempts"] >= MAX_ATTEMPTS}
            clip_id = logic.next_clip([(r["clip_id"], r["decided_at"]) for r in approved], finished)
            if not clip_id:
                continue
            row = next(r for r in approved if r["clip_id"] == clip_id)
            meta = json.loads(row["meta"])
            clip = {"meta": meta, "hq": os.path.join(CLIPS_DIR, clip_id, "hq.mp4"),
                    "caption": logic.caption(meta, CLIPS_CAPTION, CLIPS_SERVER_ADDRESS, CLIPS_HASHTAGS)}
            try:
                if not os.path.isfile(clip["hq"]):
                    raise social.PostError("the video file is gone")
                external_id, url = await upload(clip)
                await self.bot.db_bot.record_clip_post(clip_id, platform, "posted", external_id, url)
                print(f"[clips] posted {clip_id} to {platform}: {url}")
            except Exception as e:
                await self.bot.db_bot.record_clip_post(clip_id, platform, "failed", error=f"{type(e).__name__}: {e}")
                print(f"[clips] {platform} failed for {clip_id}: {type(e).__name__}: {e}")
            await self._refresh_message(row)

    async def _refresh_message(self, row):
        clip = await self.bot.db_bot.get_clip(row["clip_id"])
        if not clip or not clip["message_id"]:
            return
        posts = await self.bot.db_bot.get_clip_posts(clip_id=clip["clip_id"])
        try:
            channel = self.bot.get_channel(clip["channel_id"]) or await self.bot.fetch_channel(clip["channel_id"])
            msg = await channel.fetch_message(clip["message_id"])
            await msg.edit(embed=self._embed(json.loads(clip["meta"]), clip["status"], posts))
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------ #
    # Reviews
    # ------------------------------------------------------------------ #
    def _is_approver(self, member):
        if member is None or member.bot:
            return False
        if member.guild_permissions.administrator:
            return True
        return any(role.id in CLIPS_APPROVER_ROLE_IDS for role in member.roles)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._review(payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._review(payload)

    async def _review(self, payload):
        if not CLIPS_REVIEW_CHANNEL_ID or payload.channel_id != CLIPS_REVIEW_CHANNEL_ID:
            return
        if str(payload.emoji) not in (logic.APPROVE, logic.REJECT) or payload.user_id == self.bot.user.id:
            return
        clip = await self.bot.db_bot.get_clip_by_message(payload.message_id)
        if not clip:
            return
        channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
        msg = await channel.fetch_message(payload.message_id)
        guild = msg.guild
        reactions, approvers = {}, set()
        for reaction in msg.reactions:
            emoji = str(reaction.emoji)
            if emoji not in (logic.APPROVE, logic.REJECT):
                continue
            async for user in reaction.users():
                reactions.setdefault(emoji, set()).add(user.id)
                member = guild.get_member(user.id) if guild else None
                if self._is_approver(member):
                    approvers.add(user.id)
        status = logic.decision(reactions, approvers)
        if status != clip["status"]:
            await self.bot.db_bot.set_clip_status(clip["clip_id"], status, payload.user_id if status != "pending" else None)
            posts = await self.bot.db_bot.get_clip_posts(clip_id=clip["clip_id"])
            await msg.edit(embed=self._embed(json.loads(clip["meta"]), status, posts))

    # ------------------------------------------------------------------ #
    # Status command
    # ------------------------------------------------------------------ #
    @app_commands.command(name="clips", description="Highlight clips: waiting for review, queued and posted")
    @app_commands.default_permissions(manage_messages=True)
    async def clips_status(self, interaction: discord.Interaction):
        if not CLIPS_REVIEW_CHANNEL_ID:
            await interaction.response.send_message("Clips are turned off.", ephemeral=True)
            return
        approved = await self.bot.db_bot.get_approved_clips()
        today = self._local_now().date()
        offset = dt.timedelta(hours=ACTIVITY_UTC_OFFSET)
        lines = []
        for platform in self.uploaders:
            rows = await self.bot.db_bot.get_clip_posts(platform=platform)
            done = {r["clip_id"] for r in rows if r["status"] == "posted"}
            posted_today = sum(1 for r in rows if r["status"] == "posted" and r["posted_at"]
                               and (r["posted_at"] + offset).date() == today)
            waiting = sum(1 for r in approved if r["clip_id"] not in done)
            lines.append(f"{PLATFORM_NAMES[platform]:<10} {posted_today}/{CLIPS_POSTS_PER_DAY} today, {waiting} waiting")
        body = "\n".join(lines) or "No platforms enabled"
        await interaction.response.send_message(f"```\n{body}\n```", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Clips(bot))
