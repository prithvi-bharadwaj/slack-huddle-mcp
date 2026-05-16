"""Tests for slack_huddle.parser."""

from __future__ import annotations

from typing import Any

from slack_huddle.parser import (
    SpeakerTurn,
    extract_summary_from_canvas,
    format_lines,
    format_markdown,
    format_timestamp,
    parse_transcription,
)


def test_parse_transcription_merges_consecutive(transcript_payload: dict[str, Any]) -> None:
    transcription = transcript_payload["file"]["huddle_transcription"]
    turns = parse_transcription(transcription, merge_consecutive=True)
    speakers = [t.speaker_id for t in turns]
    # Same-speaker pairs collapse to one turn each.
    assert speakers == ["U00000001", "U00000002", "U00000003", "U00000001"]
    assert turns[0].text == "Lorem ipsum dolor sit amet. Consectetur adipiscing elit."
    assert turns[0].start_time_ms == 0
    assert turns[2].text == "Incididunt ut labore et dolore. Magna aliqua."


def test_parse_transcription_without_merging(transcript_payload: dict[str, Any]) -> None:
    transcription = transcript_payload["file"]["huddle_transcription"]
    turns = parse_transcription(transcription, merge_consecutive=False)
    assert len(turns) == 6


def test_parse_transcription_with_empty_input() -> None:
    assert parse_transcription(None) == []
    assert parse_transcription({}) == []
    assert parse_transcription({"lines": "not-a-list"}) == []


def test_parse_transcription_skips_invalid_lines() -> None:
    payload = {
        "lines": [
            {"user_id": "U1", "start_time_ms": 100, "contents": "Hello."},
            "not-a-dict",
            {"user_id": "U1"},  # missing contents
            {"user_id": "U1", "contents": "   "},  # blank text
            {"user_id": "U2", "start_time_ms": "bad", "contents": "World."},
        ]
    }
    turns = parse_transcription(payload, merge_consecutive=False)
    assert [t.speaker_id for t in turns] == ["U1", "U2"]
    assert turns[1].start_time_ms == 0


def test_parse_transcription_handles_alternate_field_names() -> None:
    payload = {
        "lines": [
            {"user": "U1", "start_time": 250, "text": "Alternate keys work."},
        ]
    }
    turns = parse_transcription(payload)
    assert turns[0].speaker_id == "U1"
    assert turns[0].start_time_ms == 250
    assert turns[0].text == "Alternate keys work."


def test_format_timestamp_under_one_hour() -> None:
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(9000) == "00:09"
    assert format_timestamp(65000) == "01:05"
    assert format_timestamp(599_000) == "09:59"


def test_format_timestamp_past_one_hour() -> None:
    assert format_timestamp(3_600_000) == "1:00:00"
    assert format_timestamp(3_725_000) == "1:02:05"


def test_format_timestamp_negative_clamps_to_zero() -> None:
    assert format_timestamp(-5) == "00:00"


def test_format_markdown_uses_display_names() -> None:
    turns = [
        SpeakerTurn("U1", 0, "Hi."),
        SpeakerTurn("U2", 9000, "Hey."),
    ]
    output = format_markdown(turns, user_map={"U1": "Alice", "U2": "Bob"})
    assert "**Alice** [00:00]: Hi." in output
    assert "**Bob** [00:09]: Hey." in output


def test_format_markdown_falls_back_to_user_id() -> None:
    turns = [SpeakerTurn("U1", 0, "Hi.")]
    output = format_markdown(turns)
    assert output == "**U1** [00:00]: Hi."


def test_format_lines_shape() -> None:
    turns = [SpeakerTurn("U1", 1500, "Hello.")]
    out = format_lines(turns, user_map={"U1": "Alice"})
    assert out == [{"speaker": "Alice", "time_ms": 1500, "text": "Hello."}]


def test_format_lines_no_user_map() -> None:
    turns = [SpeakerTurn("U1", 1500, "Hello.")]
    assert format_lines(turns) == [{"speaker": "U1", "time_ms": 1500, "text": "Hello."}]


def test_single_speaker_merges_to_one_turn() -> None:
    payload = {
        "lines": [
            {"user_id": "U1", "start_time_ms": 0, "contents": "One."},
            {"user_id": "U1", "start_time_ms": 1000, "contents": "Two."},
            {"user_id": "U1", "start_time_ms": 2000, "contents": "Three."},
        ]
    }
    turns = parse_transcription(payload)
    assert len(turns) == 1
    assert turns[0].text == "One. Two. Three."
    assert turns[0].start_time_ms == 0


def test_extract_summary_from_canvas(canvas_payload: dict[str, Any]) -> None:
    canvas = canvas_payload["file"]
    summary = extract_summary_from_canvas(canvas)
    assert "Lorem ipsum" in summary["summary_md"]
    assert summary["canvas_url"].startswith("https://example.slack.com/docs/")
    assert summary["attendees"] == ["U00000001", "U00000002", "U00000003"]
    assert len(summary["action_items"]) == 2
    assert summary["action_items"][0]["owner"] == "U00000001"


def test_extract_summary_from_empty_canvas() -> None:
    summary = extract_summary_from_canvas({})
    assert summary == {
        "summary_md": "",
        "action_items": [],
        "attendees": [],
        "canvas_url": "",
    }


def test_extract_summary_falls_back_through_text_fields() -> None:
    s1 = extract_summary_from_canvas({"preview": "preview-only"})
    assert s1["summary_md"] == "preview-only"
    s2 = extract_summary_from_canvas({"title": "title-only"})
    assert s2["summary_md"] == "title-only"


def test_extract_summary_handles_url_fallback() -> None:
    summary = extract_summary_from_canvas(
        {"url_private": "https://example.slack.com/files/x", "plain_text": "."}
    )
    assert summary["canvas_url"] == "https://example.slack.com/files/x"


def test_speaker_turn_display_name() -> None:
    turn = SpeakerTurn("U1", 0, "hi")
    assert turn.display_name() == "U1"
    assert turn.display_name({"U1": "Alice"}) == "Alice"
    assert turn.display_name({"U2": "Bob"}) == "U1"
