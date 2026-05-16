"""Shared test fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
TEST_WORKSPACE = "example"
TEST_XOXC = "xoxc-0000-0000-0000-redactedplaceholderforuseinunittestsonly"
TEST_XOXD = "xoxd-redactedplaceholderforuseinunittestsonly%3D%3D"


def load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
        return data


@pytest.fixture()
def huddles_history_payload() -> dict[str, Any]:
    return load_fixture("huddles_history.json")


@pytest.fixture()
def canvas_payload() -> dict[str, Any]:
    return load_fixture("files_info_canvas.json")


@pytest.fixture()
def transcript_payload() -> dict[str, Any]:
    return load_fixture("files_info_transcript.json")


@pytest.fixture()
def auth_payload() -> dict[str, Any]:
    return load_fixture("auth_test.json")
