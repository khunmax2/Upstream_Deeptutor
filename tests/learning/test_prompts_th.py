"""Thai Mastery Path prompts: loading, fallback, parity with English."""

from __future__ import annotations

from pathlib import Path
import re

import yaml

from deeptutor.learning import prompts as learning_prompts
from deeptutor.learning.prompts import default_module_name, get_learning_prompts

_PROMPT_DIR = Path(learning_prompts.__file__).with_name("prompts")
# Single-brace .format placeholders, ignoring escaped ``{{`` / ``}}``.
_PLACEHOLDER = re.compile(r"(?<!\{)\{([a-zA-Z_]\w*)\}(?!\})")


def _flatten(data: dict, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, name))
        else:
            out[name] = value
    return out


def test_get_learning_prompts_th_loads_without_throwing() -> None:
    prompts = get_learning_prompts("th")
    assert isinstance(prompts, dict)
    # th.yaml exists, so we must get the Thai content, not an empty/zh fallback.
    assert prompts.get("diagnostic", {}).get("system", "").strip()


def test_default_module_name_th() -> None:
    assert default_module_name("th", 1) == "โมดูล 1"
    assert default_module_name("th", 7) == "โมดูล 7"


def test_th_yaml_parity_with_en() -> None:
    en = yaml.safe_load((_PROMPT_DIR / "en.yaml").read_text(encoding="utf-8"))
    th = yaml.safe_load((_PROMPT_DIR / "th.yaml").read_text(encoding="utf-8"))
    en_flat = _flatten(en)
    th_flat = _flatten(th)

    assert set(en_flat) == set(th_flat), (
        f"missing={set(en_flat) - set(th_flat)} extra={set(th_flat) - set(en_flat)}"
    )

    # Every .format placeholder in en must be preserved verbatim in th.
    for key, en_value in en_flat.items():
        if not isinstance(en_value, str):
            continue
        assert _PLACEHOLDER.findall(en_value) == _PLACEHOLDER.findall(str(th_flat[key])), (
            f"placeholder mismatch in {key}"
        )


def test_th_does_not_fall_back_to_chinese_module_name() -> None:
    # Regression for the old `lang != "zh"` fallback that coerced th onto zh.
    assert "模块" not in default_module_name("th", 1)
