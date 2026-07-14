"""Balancing knobs for the pet — every number the game feel depends on.

Kept out of the code path so day-5 balancing (and live demo tuning) is a config
edit, not a code edit: drop a ``data/user/settings/pet.json`` with any subset of
these fields to override the defaults, matching how the rest of DeepTutor reads
runtime settings.

The defaults below are **demo-tuned** (see `docs/issues/anima-habitat/DEMO.md`):

* ``initial_hunger = 70`` — the pet starts hungry, so the very first thing the
  audience sees is a companion that *needs* them (demo script step 1).
* ``learn_exp = 50`` with ``exp_to_next = 100`` — mastering **2** objectives
  levels the pet up. At the original 20 exp a level-up needed 5 mastered
  objectives, which is unreachable in a 3-minute demo, so the level-up beat
  (script step 4) could never fire.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict

from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class PetTuning(BaseModel):
    """Every tunable number, with demo-ready defaults."""

    model_config = ConfigDict(extra="ignore")

    # decay (per wall-clock second, integrated lazily on read)
    decay_hunger_per_sec: float = 1.0 / 15.0  # ~+1 hunger / 15s
    happy_decay_per_sec: float = 2.0 / 15.0  # bleeds only while starving
    hunger_unhappy: float = 60.0  # above this, decay also hurts happiness
    sick_threshold: float = 75.0  # upward crossing → sick

    # event deltas
    learn_exp: float = 50.0
    learn_hunger_relief: float = 25.0
    learn_happy: float = 10.0
    quiz_pass_happy: float = 20.0
    quiz_fail_happy: float = 5.0

    # progression + a fresh pet's starting point
    exp_to_next: float = 100.0
    initial_hunger: float = 70.0
    initial_happy: float = 80.0


DEFAULT_TUNING = PetTuning()


def load_tuning() -> PetTuning:
    """Read ``data/user/settings/pet.json``; fall back to defaults.

    A malformed file must never break the pet — it is a balancing knob, not a
    correctness input — so we log and use the defaults.
    """
    path = get_path_service().get_settings_dir() / "pet.json"
    if not path.exists():
        return DEFAULT_TUNING
    try:
        return PetTuning.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        logger.warning("pet: ignoring malformed %s; using default tuning", path, exc_info=True)
        return DEFAULT_TUNING


__all__ = ["DEFAULT_TUNING", "PetTuning", "load_tuning"]
