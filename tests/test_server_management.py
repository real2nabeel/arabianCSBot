"""Offline tests for logs, welcome formatting, and automatic role boundaries."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from cogs.server_management import ServerManagement
from utils.server_management import safe_auto_role, welcome_text, log_code_block, message_log_embed


class FakeRole:
    def __init__(self, position, **permissions):
        self.position = position
        self.permissions = SimpleNamespace(**permissions)
        self.managed = False

    def __ge__(self, other):
        return self.position >= other.position

    def is_default(self):
        return False


class GuardTests(TestCase):
    def test_auto_role_rejects_privilege_and_hierarchy(self):
        me = SimpleNamespace(top_role=FakeRole(10))
        self.assertTrue(safe_auto_role(FakeRole(1), me))
        self.assertFalse(safe_auto_role(FakeRole(10), me))
        self.assertFalse(safe_auto_role(FakeRole(1, administrator=True), me))
        self.assertFalse(safe_auto_role(FakeRole(1, manage_roles=True), me))
        role = FakeRole(1)
        role.managed = True
        self.assertFalse(safe_auto_role(role, me))

    def test_welcome_tokens_are_not_recursively_interpreted(self):
        member = SimpleNamespace(mention="<@4>", display_name="{server}",
                                 guild=SimpleNamespace(name="Arabian", member_count=12))
        self.assertEqual(welcome_text("{user} {server} {count} {unknown}", member),
                         "{server} Arabian 12 {unknown}")
        self.assertEqual(len(welcome_text("a" * 3000, member)), 2000)


class EventTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.guild = SimpleNamespace(id=100, me=SimpleNamespace(top_role=FakeRole(10)),
                                     get_role=Mock(return_value=FakeRole(1)))
        self.bot = SimpleNamespace(get_guild=Mock(return_value=self.guild))
        self.cog = ServerManagement(self.bot)
        self.member = SimpleNamespace(guild=self.guild, bot=False, pending=True,
                                     roles=[], add_roles=AsyncMock(), id=20)

    async def test_screening_and_bot_guards(self):
        with patch("cogs.server_management.GUILD_ID", 100), patch("cogs.server_management.AUTO_ROLE_IDS", {9}):
            await self.cog.apply_auto_roles(self.member)
            self.member.add_roles.assert_not_awaited()
            self.member.pending = False
            await self.cog.apply_auto_roles(self.member)
            self.member.add_roles.assert_awaited_once()
            self.member.add_roles.reset_mock()
            self.member.bot = True
            await self.cog.apply_auto_roles(self.member)
            self.member.add_roles.assert_not_awaited()

    async def test_screening_completion_assigns_roles(self):
        self.cog.apply_auto_roles = AsyncMock()
        before = SimpleNamespace(pending=True, nick=None, roles=[], timed_out_until=None)
        after = SimpleNamespace(guild=self.guild, pending=False, nick=None, roles=[], timed_out_until=None)
        with patch("cogs.server_management.GUILD_ID", 100):
            await self.cog.on_member_update(before, after)
        self.cog.apply_auto_roles.assert_awaited_once_with(after)

    async def test_uncached_delete_and_excluded_threads(self):
        self.cog.send_log = AsyncMock()
        self.guild.get_channel_or_thread = Mock(return_value=SimpleNamespace(parent_id=9, category_id=None))
        payload = SimpleNamespace(guild_id=100, channel_id=8, message_id=7, cached_message=None)
        with patch("cogs.server_management.GUILD_ID", 100), patch("cogs.server_management.LOG_EXCLUDED_CHANNELS", {9}):
            await self.cog.on_raw_message_delete(payload)
            self.cog.send_log.assert_not_awaited()
        with patch("cogs.server_management.GUILD_ID", 100), patch("cogs.server_management.LOG_EXCLUDED_CHANNELS", set()):
            await self.cog.on_raw_message_delete(payload)
        self.assertIn("not cached", self.cog.send_log.call_args.kwargs["embed"].fields[2].value)

    async def test_cached_edit_and_delete_preserve_message_text(self):
        self.cog.send_log = AsyncMock()
        self.guild.get_channel_or_thread = Mock(return_value=None)
        message = SimpleNamespace(author=SimpleNamespace(id=20, bot=False),
                                  content="original text", attachments=[])
        payload = SimpleNamespace(guild_id=100, channel_id=8, message_id=7,
                                  cached_message=message, data={"content": "edited text"})
        with patch("cogs.server_management.GUILD_ID", 100), \
             patch("cogs.server_management.LOG_EXCLUDED_CHANNELS", set()), \
             patch("cogs.server_management.SERVER_LOG_CHANNEL_ID", 99), \
             patch("cogs.server_management.MOD_LOG_CHANNEL_ID", 99):
            await self.cog.on_raw_message_edit(payload)
            embed = self.cog.send_log.call_args.kwargs["embed"]
            self.assertEqual(embed.fields[0].value, "<@20>")
            self.assertEqual(embed.fields[2].value, "```\noriginal text\n```")
            self.assertEqual(embed.fields[3].value, "```\nedited text\n```")
            self.assertIn("https://discord.com/channels/100/8/7", embed.description)
            await self.cog.on_raw_message_delete(payload)
            self.assertIn("original text", self.cog.send_log.call_args.kwargs["embed"].fields[2].value)
            self.assertEqual(self.cog.send_log.await_count, 2)

    async def test_send_embed_suppresses_notifications(self):
        channel = SimpleNamespace(send=AsyncMock())
        self.guild.get_channel = Mock(return_value=channel)
        embed = message_log_embed(100, 8, 7, author_id=20)
        with patch("cogs.server_management.GUILD_ID", 100), \
             patch("cogs.server_management.SERVER_LOG_CHANNEL_ID", 99):
            await self.cog.send_log(self.guild, "Message edited", embed=embed)
        kwargs = channel.send.call_args.kwargs
        self.assertIs(kwargs["embed"], embed)
        self.assertEqual(kwargs["allowed_mentions"].to_dict()["parse"], [])



class RegistrationTests(IsolatedAsyncioTestCase):
    async def test_logging_extension_loads_without_moderation_commands(self):
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            await bot.load_extension("cogs.server_management")
            self.assertIsNotNone(bot.get_cog("ServerManagement"))
            self.assertEqual(bot.tree.get_commands(), [])
            self.assertNotIn("on_ready", dict(bot.get_cog("ServerManagement").get_listeners()))

class MessageLayoutTests(TestCase):
    def test_code_blocks_handle_long_text_backticks_and_empty_messages(self):
        for content in ("", "normal text", "`" * 2000, "a" * 4000):
            block = log_code_block(content)
            self.assertLessEqual(len(block), 1024)
            self.assertTrue(block.startswith("```\n"))
            self.assertTrue(block.endswith("\n```"))
            self.assertEqual(block.count("```"), 2)
        self.assertIn("truncated", log_code_block("a" * 4000))

    def test_links_and_unknown_author(self):
        edited = message_log_embed(100, 8, 7, author_id="20")
        deleted = message_log_embed(100, 8, 7, deleted=True)
        self.assertEqual(edited.fields[0].value, "<@20>")
        self.assertIn("/100/8/7", edited.description)
        self.assertIn("Open channel", deleted.description)
        self.assertNotIn("/100/8/7", deleted.description)
        self.assertIn("Unknown", deleted.fields[0].value)
        self.assertNotEqual(edited.colour, deleted.colour)
