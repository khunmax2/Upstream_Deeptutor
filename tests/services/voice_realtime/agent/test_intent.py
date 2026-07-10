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
