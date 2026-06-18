"""Skill taxonomy labels fall back to English for Thai (not Chinese)."""

from __future__ import annotations

from deeptutor.services.skill.taxonomy import DomainNode, Option


def test_option_label_th_returns_english_not_chinese() -> None:
    opt = Option("academics", "学业辅导", "Academics")
    assert opt.label("th") == "Academics"
    assert opt.label("en") == "Academics"
    assert opt.label("zh") == "学业辅导"


def test_domain_node_label_th_returns_english_not_chinese() -> None:
    node = DomainNode("math", "数学", "Mathematics")
    assert node.label("th") == "Mathematics"
    assert node.label("zh") == "数学"
