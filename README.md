# slack-huddle-mcp

> **Slack already writes a transcript of every huddle. This MCP server gives it to your agent.** No Recall.ai, no Granola, no recorder bot in the meeting.

[![PyPI](https://img.shields.io/pypi/v/slack-huddle-mcp.svg)](https://pypi.org/project/slack-huddle-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/slack-huddle-mcp.svg)](https://pypi.org/project/slack-huddle-mcp/)
[![CI](https://github.com/prithvi-bharadwaj/slack-huddle-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/prithvi-bharadwaj/slack-huddle-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 1. The problem

Slack huddles are the default daily-standup tool for a huge number of teams. On Pro / Business+ workspaces, Slack automatically generates an AI transcript and a summary canvas after each huddle.

**But Slack's public Web API does not expose those transcripts.** Every existing guide tells you to run a third-party recorder bot (Recall.ai, Granola, Otter, Fireflies, Circleback).

There's an undocumented endpoint the Slack web client itself uses. This MCP server wraps it. Your transcripts become available to any MCP-aware agent — Claude Code, Claude Cowork, Cursor, Cline, Continue, Zed — in ~200 lines of Python.

### How it compares

|                                      | slack-huddle-mcp | Recall.ai / similar | Granola / Otter / Fireflies | Slack public API |
| ------------------------------------ | :--------------: | :-----------------: | :-------------------------: | :--------------: |
| Reads Slack's **own** AI transcript  |        ✅        |          ❌         |              ❌             |        ❌        |
| No recorder bot in the meeting       |        ✅        |          ❌         |              ❌             |        ✅        |
| No third-party server in data path   |        ✅        |          ❌         |              ❌             |        ✅        |
| Works on existing huddles (no setup) |        ✅        |          ❌         |              ❌             |        ❌        |
| Cost                                 |     **free**     |        $$$/mo        |          $$/seat/mo         |       free       |
| Setup time                           |     **2 min**    |         hours        |             hours            |        n/a       |

## 2. Quickstart

```bash
pipx install slack-huddle-mcp        # or: pip install slack-huddle-mcp
slack-huddle-mcp setup --auto        # macOS: auto-extract from the Slack desktop app
slack-huddle-mcp smoke-test          # end-to-end check on your latest huddle
```

Three ways to give the tool your tokens, in order of how much effort they take:

| Setup path | Effort | What you need |
| ---------- | ------ | ------------- |
| `setup --auto` *(macOS)* | **zero clicks** after one Keychain "Always Allow" | Slack desktop app installed and logged in |
| `bookmarklet` | one click on `app.slack.com`, paste `xoxd` once | Any modern browser |
| `setup` *(manual)* | DevTools console + cookies tab | Any browser |

After setup, paste the MCP config snippet that `setup` prints into your MCP client, restart it, and ask your agent:

> *"Summarize today's standup from #standups in three bullets and list any blockers by owner."*

## 3. Use cases

- **Daily-standup briefing** — pulled into your morning agent flow.
- **Action-item extraction** — across the last N huddles, by owner.
- **Async catch-up** — "I missed the design huddle, here's what I need to know."
- **Post-meeting drafting** — first-draft Slack follow-ups in your channel's voice.
- **Cross-meeting retros** — what did the team commit to last sprint, what slipped?

### Who this is for

Teams that already run their standups in Slack huddles and want their agents to *read* them — not transcribe them again with a separate bot, not pay per seat, not invite a stranger into every meeting.

## 4. Security model

Your `xoxc` token is functionally your Slack password. Read this section before installing.

- Tokens live in your **OS keychain** (macOS Keychain, Linux libsecret/KWallet, Windows Credential Manager) via [`keyring`](https://pypi.org/project/keyring/). They are not written to disk, not stored in env vars, and are **never logged**.
- All API calls go directly from your machine to `*.slack.com`. **No third-party servers. No telemetry. No analytics.** `grep -rE 'https?://[a-z0-9.-]+' src/` to verify.
- A `401`/`403` halts immediately with a remediation message. The tool will not loop on bad auth.
- ~600 LOC across `api.py`, `parser.py`, `keychain.py`, `workspace.py`, `mcp_server.py`. Audit it yourself in 15 minutes.

If you don't want any tool with your `xoxc` token on disk — fair. You can still copy transcripts out of Slack's web UI manually. This package is the automation layer.

## 5. How it works

Slack's web client posts `files.info` with `include_transcription=true` as `multipart/form-data`, with the user-session token (`xoxc`) in the form body and the session cookie (`xoxd`) in the `Cookie` header. The response includes a populated `huddle_transcription` object with `lines[]`, `blocks`, and `transcription_time_ranges`.

```
┌────────────────────┐    1. POST huddles.history (Cookie: d={xoxd}, token={xoxc})
│  huddles.history   │  ──────────────────────────────────────────────────────────►
└─────────┬──────────┘
          │ huddle.transcript_file_id  ← this is the CANVAS file id (counterintuitive)
          ▼
┌────────────────────┐    2. POST files.info?file={canvas_id}
│  files.info (canvas) │  ──────────────────────────────────────────────────────────►
└─────────┬──────────┘
          │ canvas.huddle_transcript_file_id  ← the raw transcript file id
          ▼
┌──────────────────────────┐    3. POST files.info?file={transcript_id}&include_transcription=true
│  files.info (transcript) │  ──────────────────────────────────────────────────────►
└─────────┬────────────────┘
          │ file.huddle_transcription.lines[]  ← {user_id, start_time_ms, contents}
          ▼
   parse + merge consecutive speakers → markdown / json / lines
```

Three calls. All `POST multipart/form-data`. `token=xoxc-...` in the form body, `Cookie: d=<xoxd>` in the headers.

### Example output

Given a 3-person huddle transcript, `get_huddle_transcript(huddle_id="H...", format="markdown", user_map={...})` returns:

```markdown
**Alice** [00:00]: Lorem ipsum dolor sit amet. Consectetur adipiscing elit.

**Bob** [00:09]: Sed do eiusmod tempor.

**Carol** [00:17]: Incididunt ut labore et dolore. Magna aliqua.

**Alice** [00:25]: Ut enim ad minim veniam.
```

Consecutive same-speaker lines are merged. Timestamps use the start of each turn.

## 6. Dead ends I hit (so you don't have to)

<details>
<summary><b>Things I tried that didn't work — saves contributors time. Click to expand.</b></summary>

- `files.info` **without** `include_transcription=true` — the field is recognized but `huddle_transcription` returns empty `{}`.
- Direct `GET https://files.slack.com/files-pri/{team}-{file}/huddle_transcript` with cookie + bearer — redirects to the Slack React app HTML shell. The content is loaded by a follow-up XHR (the one this tool uses).
- `files.sharedPublicURL` — returns `not_allowed` on most workspaces (admin policy).
- Public URL with `pub_secret=...` — only works after `files.sharedPublicURL` succeeds.
- Endpoint guesses that all returned `unknown_method`: `huddleSummary.*`, `huddleTranscript.*`, `huddles.transcript.*`, `huddles.summary.*`, `ml.huddles.*`, `transcripts.*`, `files.transcribe.*`, `files.preview.*`, `files.huddleTranscription`, `calls.summary`, `calls.transcript.get`, plus ~25 other variants.
- `assistant.search.context` and `calls.info` — exist but return `not_allowed_token_type` for `xoxc`.
- `canvases.*` family on `slack.com` — `not_allowed_token_type` for `xoxc`.
- Slack search modifier `from:<@USERID>` — returns 0 results. Use `from:username` instead (no angle-bracket wrap).

</details>

## 7. Token extraction guide

### Option A — auto-extract from the Slack desktop app (macOS)

```bash
slack-huddle-mcp setup --auto              # extract, validate, store
slack-huddle-mcp setup --auto --dry-run    # extract + validate without storing
slack-huddle-mcp -v setup --auto           # add DEBUG logs on stderr
```

Reads `xoxc` from `~/Library/Application Support/Slack/Local Storage/leveldb/` (regex-scanned) and decrypts `xoxd` from the Cookies SQLite via the macOS Keychain (PBKDF2-SHA1 → AES-128-CBC, the standard Chromium scheme).

The first run triggers a one-time macOS Keychain prompt asking permission to read `Slack Safe Storage`. Click **Always Allow**. After that, future runs are silent.

### Option B — one-click browser bookmarklet

```bash
slack-huddle-mcp bookmarklet               # writes + opens helper page in your browser
slack-huddle-mcp bookmarklet --no-open     # just write the helper file
slack-huddle-mcp bookmarklet --print-only  # print the bookmarklet URL
```

Drag the link from the helper page to your bookmarks bar. Click it from any tab on `app.slack.com`, paste your `xoxd` cookie when prompted, and a complete `slack-huddle-mcp setup --xoxc ... --xoxd ...` command lands on your clipboard.

(JavaScript cannot read `xoxd` directly because it's HttpOnly — that's the one manual step in this path.)

### Option C — manual (works everywhere)

Slack tokens come out of the browser. They are not part of any developer-facing API.

#### `xoxc` (user-session token, form body)

1. Open Slack in your browser (`https://app.slack.com`) and log in.
2. Open DevTools → Console.
3. Paste this and copy the result:

   ```js
   JSON.parse(localStorage.localConfig_v2).teams[
     Object.keys(JSON.parse(localStorage.localConfig_v2).teams)[0]
   ].token
   ```

   Format: `xoxc-{team_id}-{user_id}-{session_id}-{secret}`.

> ⚠️ The `xoxc` rotates **every time you log out** of Slack. When this tool returns a `401`, re-run `slack-huddle-mcp setup`.

### `xoxd` (session cookie, header)

1. DevTools → Application → Cookies → `https://app.slack.com`.
2. Find the cookie named `d` (HttpOnly).
3. Copy the **raw value** — it's URL-encoded as stored. Do not decode.

The `xoxd` lifetime is about a year.

## 8. MCP client config snippets

All clients use the same command. Pick whichever fits your setup.

### Claude Code / Claude Cowork (`~/.claude.json`)

```json
{
  "mcpServers": {
    "slack-huddle": {
      "command": "slack-huddle-mcp",
      "args": ["serve"]
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "slack-huddle": {
      "command": "slack-huddle-mcp",
      "args": ["serve"]
    }
  }
}
```

### Cline / Continue / Zed

Same as above — point the command at `slack-huddle-mcp serve`. If your MCP client doesn't see your shell's PATH (common with GUI launchers), use the absolute path: `~/.local/bin/slack-huddle-mcp`.

### Tools your agent will see

| Tool | What it does |
| ---- | ------------ |
| `list_huddles(channel_id?, after?, before?, limit?, workspace?)` | List recent huddles, optionally scoped to a channel or time range. |
| `get_huddle_transcript(huddle_id? \| transcript_file_id?, format="markdown"\|"json"\|"lines", merge_consecutive?, user_map?, workspace?)` | Fetch the AI transcript for one huddle. |
| `get_huddle_summary(canvas_id? \| huddle_id?, workspace?)` | Fetch the AI-generated summary canvas. |
| `list_workspaces()` | List workspaces with stored tokens on this machine. |

## 9. FAQ

**Q: Does this work on free Slack workspaces?**
No. Slack only generates huddle transcripts on Pro / Business+ workspaces. If your huddles don't get an automatic summary canvas, this tool has nothing to read.

**Q: Will my `xoxc` token leak through this?**
The token never leaves your machine except as a `POST` body to `*.slack.com`. It is stored in your OS keychain, never on disk in plaintext, and `grep -rE 'xox[abc]-[a-z0-9]+' src/` returns zero matches in shipping code. Audit it.

**Q: Will Slack ban me for using this?**
Same risk profile as using the Slack web client. The tool sends the same requests your browser does. No scraping, no rate-limit games, no fake user agents. Use sensible `limit` values.

**Q: My token stopped working.**
You logged out of Slack (the `xoxc` rotates on logout). Run `slack-huddle-mcp setup` again to refresh.

**Q: How do I use this with multiple workspaces?**
Run `slack-huddle-mcp setup --workspace <subdomain>` once per workspace. Tools take an optional `workspace` argument; without it, the tool defaults to the only configured workspace, or errors if there are several.

**Q: Why is `transcript_file_id` on the huddle actually pointing at a canvas, not the transcript?**
Slack's internal naming is a known historical quirk. The "transcript file id" on `huddles.history` is the AI-summary canvas; the canvas's `huddle_transcript_file_id` field is the raw transcript. The 3-step pipeline in section 5 walks both.

**Q: Will you support live (streaming) transcripts?**
On the roadmap, once the source endpoint stabilizes. Today the AI transcript is generated post-huddle.

## 10. Roadmap

- Huddle audio download (Slack stores the m4a behind the same file machinery).
- Async client (`httpx.AsyncClient`) for parallel canvas resolution.
- Streaming transcripts for live huddles.
- Better multi-workspace UX — env-variable overrides, profile switching.
- Native Slack endpoint when/if Slack publishes one — drop the web-client shim.

## 11. Contributing & license

PRs welcome — especially for new MCP clients in section 8, additional dead ends in section 6, and tighter parsers in `parser.py`.

```bash
git clone https://github.com/prithvi-bharadwaj/slack-huddle-mcp.git
cd slack-huddle-mcp
pip install -e ".[dev]"
pytest -q --cov
ruff check src/ tests/
mypy --strict src/
```

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). Be kind.

Licensed under the [MIT License](LICENSE).
