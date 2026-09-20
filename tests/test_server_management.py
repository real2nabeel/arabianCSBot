"""Offline tests for logs, welcome formatting, and automatic role boundaries."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord.ext import commands

from cogs.server_management import ServerManagement
from utils.server_management import safe_auto_role, welcome_text


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
        self.assertIn("not cached", self.cog.send_log.call_args.args[2])


class RegistrationTests(IsolatedAsyncioTestCase):
    async def test_logging_extension_loads_without_moderation_commands(self):
        async with commands.Bot(command_prefix="!", intents=discord.Intents.none()) as bot:
            await bot.load_extension("cogs.server_management")
            self.assertIsNotNone(bot.get_cog("ServerManagement"))
            self.assertEqual(bot.tree.get_commands(), [])
