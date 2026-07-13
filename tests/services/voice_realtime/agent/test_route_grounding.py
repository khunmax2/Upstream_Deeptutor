"""Hard destination grounding — the deterministic route resolver + path checks.

Issue 01: the loop must not honour a confident `done` on the wrong page. These
pin the resolver's precision (the tools-vs-search conflation it exists to catch)
and its safe-skip behaviour (ambiguous / non-navigation tasks resolve to None so
the hard gate never manufactures a false failure).
"""

from __future__ import annotations

import pytest

from deeptutor.services.voice_realtime.agent.route_grounding import (
    landed_path,
    path_satisfies,
    resolve_target_route,
)


class TestResolveTargetRoute:
    def test_the_issue01_case_resolves_to_the_dedicated_search_route(self):
        # The exact live replay that produced the false success.
        assert (
            resolve_target_route("ไปตั้งค่าแล้วเข้าหน้าตั้งค่าการค้นหา") == "/settings/search"
        )

    def test_specific_alias_beats_the_generic_settings_hub(self):
        # "ตั้งค่า" (hub) is a substring of "ตั้งค่าการค้นหา"; the longer, more
        # specific alias must win — never resolve to the hub for a leaf task.
        assert resolve_target_route("เปิดหน้าตั้งค่าการค้นหา") == "/settings/search"

    def test_tools_task_resolves_to_tools_not_search(self):
        # The other side of the conflation: a tools task must NOT land on search.
        assert resolve_target_route("ไปหน้าตั้งค่าเครื่องมือ") == "/settings/tools"

    def test_bare_settings_resolves_to_the_hub(self):
        assert resolve_target_route("ไปหน้าตั้งค่า") == "/settings"

    def test_english_alias_matches(self):
        assert resolve_target_route("open search settings please") == "/settings/search"

    def test_action_task_with_no_named_route_is_skipped(self):
        # "create a new book" is an action, not a navigation → no hard gate.
        assert resolve_target_route("สร้างหนังสือใหม่ให้หน่อย") is None

    def test_empty_task_is_skipped(self):
        assert resolve_target_route("") is None
        assert resolve_target_route("   ") is None

    def test_toggle_task_without_a_destination_is_skipped(self):
        assert resolve_target_route("เปิดโหมดมืดให้หน่อย") is None


class TestLandedPath:
    def test_full_href_reduces_to_pathname(self):
        assert landed_path("http://localhost:3783/settings/search") == "/settings/search"

    def test_query_and_hash_are_stripped(self):
        assert landed_path("http://x/settings/search?tab=web#top") == "/settings/search"

    def test_trailing_slash_trimmed(self):
        assert landed_path("http://x/settings/search/") == "/settings/search"

    def test_bare_path_passes_through(self):
        assert landed_path("/settings/tools") == "/settings/tools"

    def test_root_is_preserved(self):
        assert landed_path("http://x/") == "/"

    def test_empty_is_empty(self):
        assert landed_path("") == ""


class TestPathSatisfies:
    def test_exact_match(self):
        assert path_satisfies("/settings/search", "/settings/search")

    def test_sibling_does_not_satisfy_a_leaf_target(self):
        # The core guarantee: /settings/tools does NOT satisfy /settings/search.
        assert not path_satisfies("/settings/search", "/settings/tools")

    def test_hub_target_accepts_a_subpage(self):
        assert path_satisfies("/settings", "/settings/search")

    def test_leaf_target_rejects_the_hub(self):
        assert not path_satisfies("/settings/search", "/settings")

    def test_prefix_is_not_a_false_positive(self):
        # /settings-x must not count as under /settings.
        assert not path_satisfies("/settings", "/settings-extra")

    @pytest.mark.parametrize(
        "target,landed",
        [("/settings/search/", "/settings/search"), ("/settings/search", "/settings/search/")],
    )
    def test_trailing_slash_insensitive(self, target, landed):
        assert path_satisfies(target, landed)
