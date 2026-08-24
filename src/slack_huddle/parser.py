"""Parse and format Slack huddle transcription payloads."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """One contiguous spoken segment by a single speaker."""

    speaker_id: str
    start_time_ms: int
    text: str

    def display_name(self, user_map: Mapping[str, str] | None = None) -> str:
        if user_map:
            return user_map.get(self.speaker_id, self.speaker_id)
        return self.speaker_id


def _coerce_line(raw: Any) -> tuple[str, int, str] | None:
    if not isinstance(raw, dict):
        return None
    user_id = raw.get("user_id") or raw.get("user") or "unknown"
    contents = raw.get("contents") or raw.get("text") or ""
    start_time_ms = raw.get("start_time_ms")
    if start_time_ms is None:
        start_time_ms = raw.get("start_time") or 0
    try:
        start_ms = int(start_time_ms)
    except (TypeError, ValueError):
        start_ms = 0
    if not isinstance(contents, str):
        return None
    text = contents.strip()
    if not text:
        return None
    return (str(user_id), start_ms, text)


def parse_transcription(
    huddle_transcription: Mapping[str, Any] | None,
    *,
    merge_consecutive: bool = True,
) -> list[SpeakerTurn]:
    """Turn a ``huddle_transcription`` payload into ordered ``SpeakerTurn`` instances.

    If ``merge_consecutive=True`` (default), adjacent lines from the same speaker
    are concatenated into a single turn with the earliest timestamp.
    """
    if not huddle_transcription:
        return []
    lines = huddle_transcription.get("lines")
    if not isinstance(lines, list):
        return []

    turns: list[SpeakerTurn] = []
    for raw in lines:
        coerced = _coerce_line(raw)
        if coerced is None:
            continue
        speaker_id, start_ms, text = coerced
        if merge_consecutive and turns and turns[-1].speaker_id == speaker_id:
            prev = turns[-1]
            turns[-1] = SpeakerTurn(
                speaker_id=prev.speaker_id,
                start_time_ms=prev.start_time_ms,
                text=f"{prev.text} {text}",
            )
        else:
            turns.append(SpeakerTurn(speaker_id, start_ms, text))
    return turns


def format_timestamp(ms: int) -> str:
    """Convert a millisecond offset to ``mm:ss`` (or ``h:mm:ss`` past one hour)."""
    if ms < 0:
        ms = 0
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_markdown(
    turns: Iterable[SpeakerTurn],
    user_map: Mapping[str, str] | None = None,
) -> str:
    """Render turns as ``**Speaker** [mm:ss]: content`` blocks."""
    chunks: list[str] = []
    for turn in turns:
        name = turn.display_name(user_map)
        ts = format_timestamp(turn.start_time_ms)
        chunks.append(f"**{name}** [{ts}]: {turn.text}")
    return "\n\n".join(chunks)


def format_lines(
    turns: Iterable[SpeakerTurn],
    user_map: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Render turns as a list of ``{speaker, time_ms, text}`` dicts."""
    return [
        {
            "speaker": turn.display_name(user_map),
            "time_ms": turn.start_time_ms,
            "text": turn.text,
        }
        for turn in turns
    ]


def canvas_html_to_markdown(html: str) -> str:
    """Convert Slack Quip canvas HTML to markdown-ish plain text.

    Slack renders huddle canvases as HTML (``files.slack.com/.../canvas``).
    This strips tags while preserving headings and line breaks, without
    external dependencies (stdlib only).
    """
    # strip script/style blocks first to avoid leaking JS/CSS into summary
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.I | re.S)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.I | re.S)
    # preserve block boundaries
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</h1>", "\n\n", html, flags=re.I)
    html = re.sub(r"</h2>", "\n\n", html, flags=re.I)
    html = re.sub(r"</p>", "\n\n", html, flags=re.I)
    html = re.sub(r"</li>", "\n", html, flags=re.I)
    html = re.sub(r"</ul>", "\n", html, flags=re.I)
    html = re.sub(r"</ol>", "\n", html, flags=re.I)
    # strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # decode entities
    html = (
        html.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    # collapse whitespace
    html = re.sub(r"\n{3,}", "\n\n", html)
    html = re.sub(r"[ \t]{2,}", " ", html)
    return html.strip()


def _extract_sections(md: str) -> dict[str, list[str]]:
    """Split a canvas summary into ``{section_name: [lines]}`` by emoji header.

    Huddle canvases use headers like ``:handshake: Participantes`` and
    ``:white_check_mark: Itens de ação``. Unknown sections are ignored.
    """
    sections: dict[str, list[str]] = {}
    current = ""
    # AI-disclaimer footer always trails the last section; never part of it
    footer_prefixes = ("esta ferramenta usa ia", "this tool uses ai")
    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(footer_prefixes) or stripped.startswith("File ID:"):
            break
        match = re.match(r":\w+:?\s+(.+)$", stripped)
        if match:
            current = match.group(1).strip().lower()
            sections.setdefault(current, [])
        elif current:
            sections[current].append(stripped)
    return sections


def extract_summary_from_canvas(
    canvas: Mapping[str, Any],
    *,
    summary_md_override: str | None = None,
) -> dict[str, Any]:
    """Extract a structured summary from a huddle's AI-summary canvas file dict.

    Returns ``{summary_md, action_items, attendees, canvas_url}``. Missing fields
    fall back to empty strings/lists.

    Note: ``files.info`` for canvas files no longer returns ``plain_text`` with
    the AI summary (only ``title``). Callers that need the full summary should
    fetch the canvas HTML via ``SlackHuddleClient.fetch_canvas_html``, convert it
    with ``canvas_html_to_markdown``, and pass it as ``summary_md_override`` —
    structured sections are parsed from it like any other summary source.
    """
    summary_md = ""
    if summary_md_override:
        summary_md = summary_md_override
    elif isinstance(canvas.get("plain_text"), str) and canvas["plain_text"].strip():
        # files.info used to return the full summary here. Real prod canvases
        # now only carry the title in plain_text — treat that as metadata-only.
        plain = canvas["plain_text"].strip()
        if plain != canvas.get("title"):
            summary_md = plain
    elif isinstance(canvas.get("preview"), str):
        summary_md = canvas["preview"]
    elif isinstance(canvas.get("title"), str):
        summary_md = canvas["title"]

    # parse ":handshake: Participantes" / ":white_check_mark: Itens de ação"
    # sections from the rendered markdown; upgrade to users.info lookup
    # if user IDs aren't enough
    attendees: list[str] = []
    raw_attendees = canvas.get("attendees")
    if isinstance(raw_attendees, list):
        attendees = [str(a) for a in raw_attendees if isinstance(a, (str, int))]
    else:
        attendee_lines = _extract_sections(summary_md).get("participantes") or _extract_sections(
            summary_md
        ).get("attendees", [])
        if len(attendee_lines) == 1:
            attendees = [
                part.strip().lstrip("@").strip()
                for part in re.split(r",| e ", attendee_lines[0])
                if part.strip()
            ]

    action_items: list[dict[str, str]] = []
    sections = _extract_sections(summary_md)
    for header in ("itens de ação", "action items"):
        for line in sections.get(header, []):
            owner_match = re.match(r"@(\S+)", line)
            ts_match = re.search(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", line)
            text = re.sub(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", "", line).strip()
            action_items.append(
                {
                    "owner": owner_match.group(1) if owner_match else "",
                    "text": text,
                    "timestamp": ts_match.group(1) if ts_match else "",
                }
            )

    blocks = (
        canvas.get("canvas_template", {}) if isinstance(canvas.get("canvas_template"), dict) else {}
    )
    raw_actions = canvas.get("action_items")
    if not isinstance(raw_actions, list):
        raw_actions = blocks.get("action_items") if isinstance(blocks, dict) else None
    if isinstance(raw_actions, list):
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            action_items.append(
                {
                    "owner": str(item.get("owner") or item.get("assignee") or ""),
                    "text": str(item.get("text") or item.get("content") or ""),
                    "timestamp": str(item.get("timestamp") or item.get("time_ms") or ""),
                }
            )

    canvas_url = ""
    for key in ("permalink", "url_private", "url_private_download"):
        value = canvas.get(key)
        if isinstance(value, str) and value:
            canvas_url = value
            break

    return {
        "summary_md": summary_md,
        "action_items": action_items,
        "attendees": attendees,
        "canvas_url": canvas_url,
    }
