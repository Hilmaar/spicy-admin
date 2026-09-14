from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from accounts.discord import Membership
from accounts.models import User

from .content import load_page, render_markdown


class MarkdownSafetyTests(SimpleTestCase):
    def test_scripts_event_handlers_and_unsafe_urls_are_removed(self):
        html = render_markdown(
            '<script>alert(1)</script><img src=x onerror="alert(1)">'
            '<a href="javascript:alert(1)" onclick="alert(1)">unsafe</a>'
            '<iframe src="https://evil.example"></iframe><svg onload="alert(1)"></svg>'
            '<form action="https://evil.example"><input name="secret"></form>'
        )
        for forbidden in (
            "<script",
            "<img",
            "javascript:",
            "onclick",
            "onerror",
            "<iframe",
            "<svg",
            "<form",
            "<input",
        ):
            self.assertNotIn(forbidden, html)

    def test_useful_markdown_survives(self):
        html = render_markdown(
            "## Heading\n\n**Bold** and `code`\n\n"
            "[Link](https://example.com)\n\n| A | B |\n|---|---|\n|1|2|"
        )
        for expected in ("<h2>", "<strong>", "<code>", "<table>", 'href="https://example.com"'):
            self.assertIn(expected, html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_unregistered_path_cannot_be_loaded(self):
        for slug in ("../../.env", "/etc/passwd", "pterodactyl", "missing"):
            with self.subTest(slug=slug), self.assertRaises(KeyError):
                load_page(slug)


class ContentPageTests(TestCase):
    @patch("accounts.permissions.fetch_membership", return_value=Membership(True, ("300",)))
    def test_pages_are_explicit_placeholders(self, membership):
        user = User.objects.create_user("123", username="Staff")
        self.client.force_login(user, backend="accounts.backends.DiscordSessionBackend")
        for slug in ("code-of-conduct", "admin-cheat-sheet"):
            response = self.client.get(f"/docs/{slug}/")
            self.assertContains(response, "placeholder")
            self.assertContains(response, "will be added later")
        self.assertEqual(self.client.get("/docs/missing/").status_code, 404)
