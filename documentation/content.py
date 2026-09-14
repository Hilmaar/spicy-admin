import markdown
import nh3
from django.conf import settings

PAGES = {
    "code-of-conduct": ("Code of Conduct", "conduct/code-of-conduct.md"),
    "admin-cheat-sheet": ("Admin Cheat Sheet", "commands/admin-cheat-sheet.md"),
}


def render_markdown(source):
    html = markdown.markdown(source, extensions=["tables", "fenced_code"])
    return nh3.clean(
        html,
        tags={
            "p",
            "h1",
            "h2",
            "h3",
            "h4",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "a",
            "blockquote",
            "pre",
            "code",
            "hr",
            "br",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
        },
        attributes={"a": {"href", "title"}},
        url_schemes={"https", "http", "mailto"},
        link_rel="noopener noreferrer",
    )


def load_page(slug):
    # Only fixed, repository-controlled paths are reachable; user input never becomes a path.
    title, relative_path = PAGES[slug]
    source = (settings.BASE_DIR / "content" / relative_path).read_text(encoding="utf-8")
    return {"title": title, "body": render_markdown(source)}
