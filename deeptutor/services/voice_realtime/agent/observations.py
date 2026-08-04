"""System observations: the loop's own notes to the LLM (page-agent §1.2 step 3).

These are ``<sys>`` lines injected into history — the mechanism that catches
navigation ("Page navigated to → …"), stops wait-loops, and forces a wrap-up
as the step budget runs out. Cheap, deterministic, and they fire whether or
not the model is paying attention.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ObservationTracker:
    max_steps: int
    last_url: str = ""
    total_wait_s: float = 0.0
    _pending: list[str] = field(default_factory=list)

    def push(self, note: str) -> None:
        """Queue an out-of-band observation (user takeover, rejected action …)."""
        self._pending.append(note)

    def note_action(self, name: str, args: dict) -> None:
        """Track accumulated waiting; any non-wait action resets the meter."""
        if name == "wait":
            self.total_wait_s += float(args.get("seconds") or 0)
        else:
            self.total_wait_s = 0.0

    def collect(self, url: str, step: int) -> list[str]:
        """Observations to record before *step* (0-based) thinks."""
        notes = list(self._pending)
        self._pending.clear()

        if url != self.last_url:
            if self.last_url:  # first observation is not a navigation
                notes.append(f"Page navigated to → {url}")
            self.last_url = url

        if self.total_wait_s >= 3:
            notes.append(
                f"You have waited {self.total_wait_s:.0f} seconds accumulatively. "
                "DO NOT wait any longer unless you have a good reason."
            )

        remaining = self.max_steps - step
        if remaining == 5:
            notes.append(
                "⚠️ Only 5 steps remaining. Consider wrapping up or calling done "
                "with partial results."
            )
        elif remaining == 2:
            notes.append("⚠️ Critical: only 2 steps left! Finish the task or call done immediately.")

        return notes
