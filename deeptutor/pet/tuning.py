"""Balancing knobs for the pet — every number the game feel depends on.

Kept out of the code path so day-5 balancing (and live demo tuning) is a config
edit, not a code edit: drop a ``data/user/settings/pet.json`` with any subset of
these fields to override the defaults, matching how the rest of DeepTutor reads
runtime settings.

The defaults below were **demo-tuned** until 2026-09-20 (see
`docs/issues/anima-habitat/DEMO.md`): a fresh pet fell sick about 75 seconds
after it was created, which sold a three-minute demo and nothing else. They
are now tuned for a school term, the user's call on the dashboards report's
open item 1:

* a pet fed by a mastered objective (hunger ``-25``) has **three days** before
  neglect makes it sick; a fresh pet starts at the same distance from the gate
  (``initial_hunger = 50``), so a student who signs up on Friday still has a
  healthy companion on Monday;
* ``learn_exp = 50`` with ``exp_to_next = 100`` stays -- mastering **2**
  objectives levels the pet up, which a student can reach in one sitting.

The demo numbers are one ``pet.json`` away (``decay_hunger_per_sec: 0.0667``,
``initial_hunger: 70``).
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

    # decay (per wall-clock second, integrated lazily on read). One mastered
    # objective's relief (25 hunger) lasts SICK_AFTER_DAYS of neglect.
    decay_hunger_per_sec: float = 25.0 / (3 * 86400)  # ~+25 hunger / 3 days
    happy_decay_per_sec: float = 50.0 / (3 * 86400)  # bleeds only while starving
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
    initial_hunger: float = 50.0  # three days from the sick gate, like a fed pet
    initial_happy: float = 80.0

    # evolution: levels at which the pet advances to its next form (stage 2, 3, …).
    # Stage is recomputed from level in ``apply_rules`` — the SINGLE source of the
    # thresholds, so the frontend renders ``stage`` and never re-derives it.
    evolve_levels: list[int] = [3, 7]


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
