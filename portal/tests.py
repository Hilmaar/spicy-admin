from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase


class DatabaseReadinessTests(SimpleTestCase):
    @patch("portal.management.commands.wait_for_db.time.sleep")
    @patch("portal.management.commands.wait_for_db.connection")
    def test_postgres_not_yet_ready_is_retried(self, connection, sleep):
        connection.cursor.side_effect = [OperationalError(), MagicMock()]
        call_command("wait_for_db", stdout=MagicMock())
        connection.close.assert_called_once()
        sleep.assert_called_once_with(2)

    @patch("portal.management.commands.wait_for_db.time.sleep")
    @patch("portal.management.commands.wait_for_db.connection")
    def test_startup_failure_is_bounded_and_sanitized(self, connection, sleep):
        connection.cursor.side_effect = OperationalError("credential-secret")
        with self.assertRaises(CommandError) as caught:
            call_command("wait_for_db")
        self.assertNotIn("credential-secret", str(caught.exception))
        self.assertEqual(connection.cursor.call_count, 30)
        self.assertEqual(sleep.call_count, 29)
