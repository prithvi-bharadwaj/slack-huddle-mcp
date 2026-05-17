"""Tests for slack_huddle.bookmarklet."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from slack_huddle import bookmarklet


def test_bookmarklet_js_is_single_line() -> None:
    js = bookmarklet.bookmarklet_js()
    assert "\n" not in js
    assert js.startswith("(function(){")
    assert js.endswith("})();")


def test_bookmarklet_js_reads_localstorage() -> None:
    js = bookmarklet.bookmarklet_js()
    assert "localConfig_v2" in js
    assert "cfg.teams" in js
    assert "xoxc-" in js


def test_bookmarklet_js_copies_complete_setup_command() -> None:
    js = bookmarklet.bookmarklet_js()
    assert "slack-huddle-mcp setup --xoxc" in js
    assert "--xoxd" in js
    assert "navigator.clipboard" in js


def test_bookmarklet_url_is_javascript_scheme() -> None:
    url = bookmarklet.bookmarklet_url()
    assert url.startswith("javascript:")


def test_bookmarklet_url_decodes_to_original_js() -> None:
    url = bookmarklet.bookmarklet_url()
    decoded = unquote(url[len("javascript:") :])
    assert decoded == bookmarklet.bookmarklet_js()


def test_helper_html_contains_bookmarklet_link() -> None:
    html = bookmarklet.helper_html()
    assert "<!doctype html>" in html
    assert 'class="bookmark"' in html
    assert "javascript:" in html
    # The bookmarklet URL itself should be HTML-escaped (no raw & or " inside the href).
    assert "Slack Huddle setup" in html


def test_helper_html_has_usage_instructions() -> None:
    html = bookmarklet.helper_html()
    for fragment in (
        "Drag the purple link",
        "https://app.slack.com",
        "Application",
        "Cookies",
        "<code>d</code>",
    ):
        assert fragment in html


def test_write_helper_page_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.html"
    written = bookmarklet.write_helper_page(target)
    assert written == target
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_open_helper_in_browser_calls_webbrowser(
    tmp_path: Path, monkeypatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(bookmarklet.webbrowser, "open", lambda url: opened.append(url))
    target = tmp_path / "out.html"
    path = bookmarklet.open_helper_in_browser(target)
    assert path == target
    assert opened == [f"file://{target}"]
