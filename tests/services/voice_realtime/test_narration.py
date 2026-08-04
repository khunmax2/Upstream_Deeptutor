"""Tests for the voice narration filler lines."""

from __future__ import annotations

from deeptutor.services.voice_realtime.narration import (
    HANG_LINE,
    REASSURE_LINE,
    filler_for_tool,
)


def test_known_tools_have_specific_fillers() -> None:
    assert "เอกสาร" in filler_for_tool("rag")
    assert "อินเทอร์เน็ต" in filler_for_tool("web_search")
    assert filler_for_tool("read_memory") != filler_for_tool("rag")


def test_unknown_tool_stays_silent() -> None:
    # A "please wait" must be earned by a real wait (the watchdog's job) —
    # unknown tools may finish instantly, so no pre-emptive filler.
    assert filler_for_tool("some_new_tool") == ""
    assert filler_for_tool("") == ""


def test_watchdog_lines_are_nonempty_and_speakable() -> None:
    # No markdown/symbols — these get read aloud verbatim.
    for line in (REASSURE_LINE, HANG_LINE):
        assert line and not any(c in line for c in "*#`$|")
