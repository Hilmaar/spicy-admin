from unittest.mock import MagicMock, patch

import pymysql
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.discord import Membership
from accounts.models import User

from .repository import CoreProtectUnavailable, MariaDBCoreProtectRepository, World
from .services import connection_status, diagnostics


@override_settings(
    COREPROTECT_DB_NAME="external",
    COREPROTECT_DB_USER="reader",
    COREPROTECT_DB_PASSWORD="test-secret",
    COREPROTECT_DB_HOST="test-host",
)
class AdapterTests(SimpleTestCase):
    def setUp(self):
        self.patcher = patch("coreprotect.repository.pymysql.connect")
        self.connect = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.connection = self.connect.return_value
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.repository = MariaDBCoreProtectRepository()

    def test_connectivity_is_small_read_only_and_bounded(self):
        self.cursor.fetchone.return_value = (1,)
        self.assertTrue(self.repository.check_connection())
        args = self.connect.call_args.kwargs
        self.assertEqual(args["host"], "test-host")
        for timeout in ("connect_timeout", "read_timeout", "write_timeout"):
            self.assertEqual(args[timeout], 3)
        self.assertFalse(args["local_infile"])
        self.cursor.execute.assert_any_call("START TRANSACTION READ ONLY")
        self.cursor.execute.assert_any_call("SET SESSION max_statement_time = %s", (3,))
        self.cursor.execute.assert_any_call("SELECT 1")
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()

    def test_world_ids_come_from_mapping(self):
        self.cursor.fetchall.return_value = [(78, "resource_world"), (904, "archive_world")]
        self.assertEqual(
            self.repository.list_worlds(),
            [
                World(78, "resource_world"),
                World(904, "archive_world"),
            ],
        )
        self.cursor.fetchone.return_value = (904, "archive_world")
        self.assertEqual(
            self.repository.resolve_world("archive_world"), World(904, "archive_world")
        )
        self.assertEqual(self.cursor.execute.call_args.args[1], ("archive_world",))

    def test_material_resolution_uses_parameters_and_returns_id(self):
        self.cursor.fetchone.return_value = (9876,)
        self.assertEqual(self.repository.resolve_material("minecraft:diamond_ore"), 9876)
        sql, params = self.cursor.execute.call_args.args
        self.assertNotIn("minecraft:diamond_ore", sql)
        self.assertEqual(params, ("minecraft:diamond_ore",))
        malicious = "x'; DROP TABLE co_block; --"
        self.repository.resolve_material(malicious)
        sql, params = self.cursor.execute.call_args.args
        self.assertNotIn(malicious, sql)
        self.assertEqual(params, (malicious,))

    def test_missing_mappings_and_version(self):
        self.cursor.fetchone.return_value = None
        self.assertIsNone(self.repository.resolve_material("minecraft:missing"))
        self.assertIsNone(self.repository.resolve_world("missing_world"))
        self.assertIsNone(self.repository.get_version())

    def test_latest_recorded_version(self):
        self.cursor.fetchone.return_value = ("2.24.1",)
        self.assertEqual(self.repository.get_version(), "2.24.1")
        self.assertIn("ORDER BY rowid DESC LIMIT 1", self.cursor.execute.call_args.args[0])

    def test_connection_error_sanitized(self):
        self.connect.side_effect = pymysql.OperationalError(1045, "test-secret test-host")
        with self.assertRaises(CoreProtectUnavailable) as caught:
            self.repository.check_connection()
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertNotIn("test-host", str(caught.exception))

    def test_query_error_closes_and_rolls_back(self):
        self.cursor.execute.side_effect = [None, None, pymysql.OperationalError(3024, "timeout")]
        with self.assertRaises(CoreProtectUnavailable):
            self.repository.get_version()
        self.connection.rollback.assert_called_once()
        self.connection.close.assert_called_once()

    @override_settings(COREPROTECT_TABLE_PREFIX="custom_")
    def test_configurable_prefix(self):
        self.cursor.fetchone.return_value = (1,)
        MariaDBCoreProtectRepository().get_version()
        self.assertIn("`custom_version`", self.cursor.execute.call_args.args[0])

    @override_settings(COREPROTECT_TABLE_PREFIX="co_; DROP ")
    def test_prefix_injection_rejected_before_connecting(self):
        with self.assertRaises(CoreProtectUnavailable):
            MariaDBCoreProtectRepository()
        self.connect.assert_not_called()

    @override_settings(COREPROTECT_DB_PASSWORD="")
    def test_unconfigured_source_does_not_connect(self):
        with self.assertRaises(CoreProtectUnavailable):
            self.repository.check_connection()
        self.connect.assert_not_called()

    def test_diagnostic_world_result_limit(self):
        self.cursor.fetchall.return_value = [(1, "world")] * 1001
        with self.assertRaises(CoreProtectUnavailable):
            self.repository.list_worlds()


@override_settings(
    COREPROTECT_DB_NAME="external",
    COREPROTECT_DB_USER="reader",
    COREPROTECT_DB_PASSWORD="test-secret",
)
class FailureHandlingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        user = User.objects.create_user("123", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        membership = patch(
            "accounts.permissions.fetch_membership", return_value=Membership(True, ("200",))
        )
        membership.start()
        self.addCleanup(membership.stop)

    @patch("coreprotect.services.get_repository", side_effect=CoreProtectUnavailable("secret"))
    def test_failure_is_visible_but_portal_and_docs_survive(self, repository):
        self.assertContains(self.client.get("/"), "Unavailable")
        diagnostic = self.client.get("/diagnostics/")
        self.assertContains(diagnostic, "Connection unavailable")
        self.assertNotContains(diagnostic, "secret")
        repository.reset_mock()
        self.assertEqual(self.client.get("/docs/code-of-conduct/").status_code, 200)
        repository.assert_not_called()

    @patch("coreprotect.services.get_repository")
    def test_status_cached(self, factory):
        factory.return_value.check_connection.return_value = True
        self.assertEqual(connection_status()["label"], "Connected")
        connection_status()
        factory.return_value.check_connection.assert_called_once()

    @patch("coreprotect.services.get_repository")
    def test_diagnostics_and_world_table(self, factory):
        factory.return_value = MagicMock(
            get_version=lambda: "2.24.1",
            list_worlds=lambda: [World(79, "new_world")],
            resolve_material=lambda name: 905,
        )
        self.assertTrue(diagnostics()["available"])
        response = self.client.get("/diagnostics/")
        for text in ("new_world", "2.24.1", "905"):
            self.assertContains(response, text)
