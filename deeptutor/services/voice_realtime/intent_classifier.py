"""Intent classifier — the primary semantic router for voice turns.

The keyword ladder in ``pipeline.run_text_turn`` catches only phrasings it was
written for; anything else falls to the chat LLM, which does ONE UI action and
stops (so "สร้างหนังสือใหม่" navigates and never clicks "New book"). This
classifier is the semantic backbone the keywords could never be: it decides
whether an utterance is a CONVERSATION (``chat``) or a command to OPERATE the
screen (``ui_task``). ``ui_task`` → the in-page agent loop (which interprets and
does the right number of steps); ``chat`` → the chat capability, unchanged.

Design (docs/issues/voice-intent-classifier/PRD.md):
- Runs only AFTER the free deterministic fast-path misses (A1 hybrid), so obvious
  commands stay instant and free.
- Two buckets only — the loop owns step count; a sharper decision is a more
  reliable one.
- A cheap LITE model: the decision is easy (one word), unlike the loop which
  needs a strong model. Configured separately so the tiers don't have to match.
- OFF by default; on failure it returns ``None`` so the caller keeps today's
  behaviour — the classifier can only improve routing, never break a turn.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Literal

logger = logging.getLogger(__name__)

FLAG_ENV = "DEEPTUTOR_VOICE_CLASSIFIER"
MODEL_ENV = "DEEPTUTOR_VOICE_CLASSIFIER_MODEL"
BASE_URL_ENV = "DEEPTUTOR_VOICE_CLASSIFIER_BASE_URL"
API_KEY_ENV = "DEEPTUTOR_VOICE_CLASSIFIER_API_KEY"
# Force the provider spec by name (e.g. `openai`) for OpenAI-compat upstreams so
# the endpoint wins over model-name inference — same rationale as the agent
# loop's DEEPTUTOR_AGENT_BINDING. Unset ⇒ inference (Gemini unaffected).
BINDING_ENV = "DEEPTUTOR_VOICE_CLASSIFIER_BINDING"

Intent = Literal["chat", "ui_task"]

_SYSTEM_PROMPT = """You route one utterance in DeepTutor, a Thai-first learning app.
Output ONLY a JSON object: {"intent": "chat"} or {"intent": "ui_task"}.

- "ui_task" = the user wants to OPERATE the screen: navigate, open / create /
  add / delete / edit something, click a control, fill a field, change a setting.
  Examples: "สร้างหนังสือใหม่", "ขอสมุดเล่มใหม่", "ไปหน้าตั้งค่า", "เปลี่ยนเป็นธีมมืด",
  "ลบ KB นี้", "กดค้นหา", "open the knowledge center".
- "chat" = the user is asking a question or conversing and wants an ANSWER, not a
  screen action. Examples: "ราคาทองวันนี้เท่าไหร่", "อธิบาย PDPA ให้หน่อย",
  "สวัสดีครับ", "PDPA คืออะไร".

When genuinely unsure, choose "ui_task". Reply with ONLY the JSON object."""


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def classifier_enabled() -> bool:
    """On only when explicitly switched AND a model is configured. Off ⇒ the
    voice router behaves exactly as today."""
    return _env(FLAG_ENV).lower() in {"1", "true", "yes"} and bool(_env(MODEL_ENV))


def _context_line(ui_context: dict[str, str] | None) -> str:
    if not ui_context:
        return ""
    page = (ui_context.get("path") or "").strip()
    summary = (ui_context.get("summary") or "").strip()[:200]
    if not page and not summary:
        return ""
    tail = f" — {summary}" if summary else ""
    return f"\n(หน้าปัจจุบัน: {page}{tail})"


def _parse_intent(raw: str) -> Intent:
    """Extract the intent; anything that isn't a clear ``chat`` is ``ui_task``
    (the bias: better to run the loop and have it bow out than to chat-answer a
    command)."""
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            value = str(json.loads(match.group(0)).get("intent", "")).lower()
            return "chat" if value == "chat" else "ui_task"
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
    return "chat" if raw.strip().lower() == "chat" else "ui_task"


async def classify(transcript: str, ui_context: dict[str, str] | None = None) -> Intent | None:
    """Return ``"chat"`` / ``"ui_task"``, or ``None`` when unavailable/failed
    (caller then keeps today's behaviour). Never raises."""
    if not classifier_enabled() or not transcript.strip():
        return None
    try:
        from deeptutor.services.llm import complete

        kwargs: dict[str, Any] = {
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_retries": 1,
        }
        base_url = _env(BASE_URL_ENV)
        api_key = _env(API_KEY_ENV)
        binding = _env(BINDING_ENV)
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        if binding:
            kwargs["binding"] = binding

        raw = await complete(
            f"{transcript}{_context_line(ui_context)}",
            system_prompt=_SYSTEM_PROMPT,
            model=_env(MODEL_ENV),
            **kwargs,
        )
    except Exception:  # noqa: BLE001 — a classifier failure must not break the turn
        logger.warning("voice classify failed; deferring to the chat path", exc_info=True)
        return None

    intent = _parse_intent(raw)
    logger.info("voice classify intent=%s %r", intent, transcript[:60])
    return intent
