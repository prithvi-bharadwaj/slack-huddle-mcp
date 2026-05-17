"""Browser bookmarklet helper for option-2 setup.

The bookmarklet runs in any tab on ``app.slack.com`` and extracts ``xoxc`` from
``localStorage.localConfig_v2`` directly. It then prompts the user for ``xoxd``
(which is HttpOnly, so JS cannot read it) and copies a complete
``slack-huddle-mcp setup --xoxc ... --xoxd ...`` command to the clipboard.

We render the bookmarklet inside a tiny HTML helper page so users can drag it
to their bookmarks bar — most browsers refuse to install ``javascript:`` URLs
typed by hand into the bookmark dialog.
"""

from __future__ import annotations

import html
import logging
import tempfile
import webbrowser
from pathlib import Path
from urllib.parse import quote

logger = logging.getLogger(__name__)

_BOOKMARKLET_JS = r"""
(function(){
  try {
    var cfg = JSON.parse(localStorage.localConfig_v2 || '{}');
    var keys = Object.keys(cfg.teams || {});
    if (!keys.length) {
      alert('slack-huddle-mcp: no Slack workspaces in this tab. Open https://app.slack.com first.');
      return;
    }
    var xoxc = cfg.teams[keys[0]].token;
    if (!xoxc || xoxc.indexOf('xoxc-') !== 0) {
      alert('slack-huddle-mcp: xoxc token not found. Are you logged in?');
      return;
    }
    var xoxd = prompt(
      'slack-huddle-mcp: xoxc captured. Now paste the xoxd cookie value below.\n\n' +
      'DevTools -> Application -> Cookies -> https://app.slack.com -> d -> copy "Value".\n\n' +
      '(URL-encoded - do not decode.)'
    );
    if (!xoxd) { return; }
    var cmd = 'slack-huddle-mcp setup --xoxc ' + xoxc + ' --xoxd ' + xoxd;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(cmd).then(function(){
        alert('slack-huddle-mcp: setup command copied. Paste it into your terminal.');
      }, function(){
        prompt('slack-huddle-mcp: copy this command and run it in your terminal:', cmd);
      });
    } else {
      prompt('slack-huddle-mcp: copy this command and run it in your terminal:', cmd);
    }
  } catch(err) {
    alert('slack-huddle-mcp: bookmarklet failed — ' + err.message);
  }
})();
""".strip()


def bookmarklet_js() -> str:
    """Return the bookmarklet JavaScript (minified, single-line)."""
    return " ".join(_BOOKMARKLET_JS.split())


def bookmarklet_url() -> str:
    """Return the bookmarklet as a ``javascript:`` URL ready to drag to bookmarks."""
    # Quote everything except characters that must remain literal in JS.
    return "javascript:" + quote(bookmarklet_js(), safe="(){}[],;:.='\"+/-*?&|<>!@#$%^_`~")


def helper_html() -> str:
    """A small HTML page with the draggable bookmarklet + instructions."""
    href = html.escape(bookmarklet_url(), quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>slack-huddle-mcp · bookmarklet</title>
<style>
  body {{ font: 16px/1.55 -apple-system, system-ui, "Segoe UI", Helvetica, sans-serif; max-width: 680px; margin: 4em auto; padding: 0 1.5em; color: #1a1a1a; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  h2 {{ font-size: 18px; margin-top: 2em; }}
  .lede {{ color: #555; margin-top: 0; }}
  .bookmark {{ display: inline-block; padding: 12px 20px; background: #4a154b; color: #fff; border-radius: 8px; text-decoration: none; font-weight: 600; box-shadow: 0 2px 6px rgba(0,0,0,0.12); }}
  ol li {{ margin: 0.6em 0; }}
  code, kbd {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.95em; }}
  .fineprint {{ color: #777; font-size: 0.9em; margin-top: 2.5em; }}
</style>
</head>
<body>
<h1>slack-huddle-mcp bookmarklet</h1>
<p class="lede">One-click Slack token extraction. No DevTools console snippets.</p>

<p><strong>Drag this to your bookmarks bar:</strong></p>
<p><a class="bookmark" href="{href}">Slack Huddle setup</a></p>

<h2>How to use</h2>
<ol>
  <li>Drag the purple link above into your browser's bookmarks bar.</li>
  <li>Open <a href="https://app.slack.com" target="_blank" rel="noopener">https://app.slack.com</a> and log in.</li>
  <li>Click the <strong>Slack Huddle setup</strong> bookmark.</li>
  <li>When prompted, paste your <code>xoxd</code> cookie value. Get it from DevTools → Application → Cookies → <code>app.slack.com</code> → <code>d</code> → "Value" column.</li>
  <li>Paste the resulting command into your terminal. Done.</li>
</ol>

<p class="fineprint">
  If your browser refuses to drag a <code>javascript:</code> link to the bookmark bar (Firefox sometimes does this), copy the URL via right-click → "Copy Link Address" and create a new bookmark manually with that URL.
</p>
</body>
</html>
"""


def write_helper_page(target: Path | None = None) -> Path:
    """Write the helper HTML to disk and return its path."""
    if target is None:
        target = Path(tempfile.gettempdir()) / "slack-huddle-bookmarklet.html"
    target.write_text(helper_html(), encoding="utf-8")
    logger.info("bookmarklet: wrote helper page to %s", target)
    return target


def open_helper_in_browser(target: Path | None = None) -> Path:
    """Write the helper page and open it in the default browser."""
    path = write_helper_page(target)
    webbrowser.open(f"file://{path}")
    return path
