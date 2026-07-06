"""Config for the voice-call static host (env-driven).

Only the server bind address lives here now. The call page itself
(`static/call.html`) talks directly to DeepTutor's realtime socket, so LLM /
STT / TTS are configured in DeepTutor's Settings > Voice catalog — not in this
prototype. The old standalone pipeline settings were removed with the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
import os


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


@dataclass(slots=True)
class Config:
    host: str = _env("HOST", "127.0.0.1")
    port: int = int(_env("PORT", "8800"))


CONFIG = Config()
