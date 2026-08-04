"""match_agent_task — the deterministic door into the loop (D2 routing).

The stakes: a false negative just means the old fast-path/miss behavior (safe);
a false positive spends a full agent run on chit-chat (expensive). So the
matcher must be conservative and these tests skew toward rejecting.
"""

from deeptutor.services.voice_realtime.agent.intent import match_agent_task


def test_the_acceptance_utterance_matches():
    assert match_agent_task("ไปตั้งค่าแล้วเปลี่ยนธีมมืด")


def test_compound_with_named_connector():
    assert match_agent_task("เปิดศูนย์ความรู้ จากนั้นค้นหา pdpa")
    assert match_agent_task("กดตั้งค่า ต่อด้วยเลือกภาษาไทย")


def test_simple_navigation_stays_on_the_fast_path():
    assert match_agent_task("ไปหน้าหลัก") is None
    assert match_agent_task("เปิดศูนย์ความรู้") is None


def test_simple_click_stays_on_the_fast_path():
    assert match_agent_task("กดปุ่มบันทึก") is None


def test_sentence_particle_after_connector_is_not_a_second_step():
    # "แล้วกัน" / "แล้วนะ" are particles, not plans.
    assert match_agent_task("ไปหน้าหลักแล้วกัน") is None
    assert match_agent_task("เปิดตั้งค่าแล้วนะ") is None


def test_questions_are_conversation_not_tasks():
    assert match_agent_task("ทำไมต้องไปตั้งค่าแล้วเปลี่ยนธีม") is None
    assert match_agent_task("ไปตั้งค่าแล้วเปลี่ยนธีมได้ไหม") is None


def test_non_action_openers_do_not_match():
    assert match_agent_task("เมื่อกี้ไปตั้งค่าแล้วเปลี่ยนธีมมา") is None
    assert match_agent_task("อยากรู้เรื่องธีมมืด") is None


def test_rambling_beyond_the_cap_is_left_to_the_llm():
    long_text = "ไปตั้งค่าแล้วเปลี่ยนธีมมืด " + "และช่วยดูเรื่องอื่นให้หน่อย " * 10
    assert match_agent_task(long_text) is None


# ── "กลับ" (back-to) family — the live-test gap: this utterance fell through
# to the old navigate-only chat path instead of the loop, because none of the
# original openers matched a sentence starting with "กลับ". ──


def test_back_to_home_then_search_matches():
    assert match_agent_task("กลับไปหน้าหลักแล้วค้นหาราคาทอง")


def test_back_to_settings_variants_match():
    assert match_agent_task("กลับไปที่ตั้งค่าแล้วเปลี่ยนธีมมืด")
    assert match_agent_task("กลับไปแล้วเปิดศูนย์ความรู้")
    assert match_agent_task("กลับแล้วค้นหา pdpa")


def test_bare_back_without_a_second_step_stays_on_the_fast_path():
    assert match_agent_task("กลับไปหน้าหลัก") is None


# ── Rule 2: connector elided (live-test bug: "ไปตั้งค่าเปลี่ยนธีมมืด" reached
# the chat LLM, which called ui_navigate and dropped the theme half) ──


def test_nav_opener_plus_second_verb_without_connector_matches():
    assert match_agent_task("ไปตั้งค่าเปลี่ยนธีมมืด")
    assert match_agent_task("ไปหน้าหลักค้นหาราคาทอง")
    assert match_agent_task("กลับไปหน้าหลักค้นหาราคาทอง")
    assert match_agent_task("เปิดตั้งค่าเปลี่ยนภาษา")


def test_plain_navigation_still_stays_on_the_fast_path():
    assert match_agent_task("ไปตั้งค่า") is None
    assert match_agent_task("ไปหน้าหลัก") is None
    assert match_agent_task("เปิดศูนย์ความรู้") is None


def test_click_opener_with_verby_button_label_is_not_a_task():
    # "เปลี่ยนธีม" here is ONE button whose label contains a verb — the click
    # rung owns it (and its own miss seam already routes to the agent).
    assert match_agent_task("กดปุ่มเปลี่ยนธีม") is None


def test_verb_inside_a_noun_does_not_false_fire():
    # "ปัญหา" contains "หา" — excluded from the second-step scan.
    assert match_agent_task("ไปดูปัญหาหน่อย") is None


# ── clipped verbs (live-test gap #3: "ไปhomeแล้วค้นราคาน้ำมัน" died as a
# navigate-only turn — spoken Thai clips "ค้นหา" to "ค้น") ──


def test_clipped_search_verb_matches():
    assert match_agent_task("กลับไปhomeแล้วค้นราคาน้ำมัน")
    assert match_agent_task("ไปhomeแล้วค้นราคาแตงกวา")
    assert match_agent_task("ไปหน้าหลักค้นราคาทอง")  # connector elided too


def test_clipped_verb_does_not_widen_the_fast_path_exits():
    assert match_agent_task("ไปหน้าหลัก") is None
    assert match_agent_task("กดปุ่มค้นหา") is None  # click rung owns this
