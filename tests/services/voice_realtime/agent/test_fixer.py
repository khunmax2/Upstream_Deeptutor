"""Fixer heuristics — each numbered case from page-agent's autoFixer must hold.

These are regression walls: every heuristic here is a class of real model
output observed in the wild. Removing one silently narrows the set of models
the loop can run on.
"""

import json

import pytest

from deeptutor.services.voice_realtime.agent.fixer import FixerError, normalize_output

GOOD = {
    "evaluation_previous_goal": "Clicked settings. Verdict: Success",
    "memory": "On the settings page now.",
    "next_goal": "Click the dark theme toggle.",
    "action": {"click_element_by_index": {"index": 12}},
}


def test_clean_output_passes_through():
    out = normalize_output(json.dumps(GOOD))
    assert out["action"] == {"click_element_by_index": {"index": 12}}
    assert out["next_goal"] == "Click the dark theme toggle."


def test_h1_json_buried_in_prose_and_code_fence():
    raw = "Sure! Here is my output:\n```json\n" + json.dumps(GOOD) + "\n```\nDone."
    assert normalize_output(raw)["action"]["click_element_by_index"]["index"] == 12


def test_h2_tool_call_envelopes_unwrapped():
    enveloped = {"name": "AgentOutput", "arguments": json.dumps(GOOD)}
    assert normalize_output(json.dumps(enveloped))["memory"] == GOOD["memory"]

    fn_env = {"type": "function", "function": {"arguments": json.dumps(GOOD)}}
    assert normalize_output(json.dumps(fn_env))["memory"] == GOOD["memory"]


def test_h3_double_stringified_action():
    doubled = dict(GOOD, action=json.dumps(GOOD["action"]))
    assert normalize_output(json.dumps(doubled))["action"] == GOOD["action"]


def test_h4_bare_action_gets_wrapped():
    raw = json.dumps({"click_element_by_index": {"index": 3}})
    out = normalize_output(raw)
    assert out["action"] == {"click_element_by_index": {"index": 3}}
    assert out["next_goal"] == ""  # reflection absent → empty, not crash


def test_h5_primitive_input_coerced():
    raw = json.dumps(dict(GOOD, action={"click_element_by_index": 7}))
    assert normalize_output(raw)["action"] == {"click_element_by_index": {"index": 7}}


def test_h5_stringy_index_coerced():
    raw = json.dumps(dict(GOOD, action={"click_element_by_index": {"index": "7"}}))
    assert normalize_output(raw)["action"]["click_element_by_index"]["index"] == 7


def test_h6_missing_action_falls_back_to_wait():
    raw = json.dumps({k: v for k, v in GOOD.items() if k != "action"})
    assert normalize_output(raw)["action"] == {"wait": {"seconds": 1}}


def test_h7_action_named_by_field_is_reshaped():
    """llama-3.x (live on Groq) names the action in a field instead of the key."""
    raw = json.dumps(
        dict(GOOD, action={"action_name": "click_element_by_index", "index": 2})
    )
    assert normalize_output(raw)["action"] == {"click_element_by_index": {"index": 2}}


def test_h7_named_field_with_text_args():
    raw = json.dumps(
        dict(GOOD, action={"tool": "input_text", "index": 3, "text": "pdpa"})
    )
    assert normalize_output(raw)["action"] == {
        "input_text": {"index": 3, "text": "pdpa"}
    }


def test_h7_leaves_a_real_keyed_action_untouched():
    """A field called 'name' inside proper args must not hijack the reshape."""
    raw = json.dumps(dict(GOOD, action={"done": {"text": "ok", "success": True}}))
    assert normalize_output(raw)["action"] == {"done": {"text": "ok", "success": True}}


def test_unknown_action_names_the_available_ones():
    raw = json.dumps(dict(GOOD, action={"teleport": {}}))
    with pytest.raises(FixerError, match="click_element_by_index"):
        normalize_output(raw)


def test_missing_required_param_is_actionable():
    raw = json.dumps(dict(GOOD, action={"input_text": {"index": 2}}))
    with pytest.raises(FixerError, match='"text"'):
        normalize_output(raw)


def test_no_json_at_all_raises():
    with pytest.raises(FixerError, match="no valid JSON"):
        normalize_output("I clicked the button for you!")
