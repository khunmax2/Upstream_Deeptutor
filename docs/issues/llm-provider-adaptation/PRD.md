# Provider-aware LLM call adaptation (env-only, UI-ready)

Status: ready-for-agent
Owner: Attapon · Drafted: 2026-07-12 · Deferred until: LLM quota returns (needs live calls to verify)

## Problem

Switching the LLM provider currently means chasing code fixes. Concretely: with
`.env.agent` pointed at Groq (`qwen/qwen3-32b`), the voice agent loop's LLM call
returns **400 Bad Request** because the shipping request carries params the
provider rejects. The voice pipeline was built/tuned for Gemini and has no Groq
adaptation. We do NOT want to hand-patch each call site (voice, chat, tools)
every time the model changes. There is no config UI yet — this must work from
env / settings only.

Observed live (2026-07-12): `POST https://api.groq.com/openai/v1/chat/completions
→ 400`, surfaced to the caller as the spoken `_THINK_FAILED_LINE`
("สมองของผู้ช่วยขัดข้องครับ"). Same class of error hit repeatedly during the
Phase E eval (see `docs/reports/REPORT_inpage_agent_phaseE_2026-07-12.md`).

## Root cause — two gaps in an ALREADY-EXISTING layer

The app already has the right skeleton: `PROVIDER_CAPABILITIES`
(`deeptutor/services/llm/capabilities.py`) + `_sanitize_call_kwargs`
(`deeptutor/services/llm/factory.py:311`) already strip params a provider does
not support (e.g. `response_format` is dropped when
`supports_response_format(binding, model)` is false). The gaps:

1. **`reasoning_effort` is not in the capability system.** It is passed through
   on every call (factory.py ~161–204), never checked against the provider. So
   `reasoning_effort="minimal"` (a Gemini/OpenAI value that `think()` hardcodes
   in `agent/llm.py`) reaches Groq, which rejects it (`400`; per-model allowed
   sets differ — llama: none; qwen3: none/default; gpt-oss: full range).
2. **Provider is inferred from the MODEL NAME, not the endpoint.**
   `_resolve_provider_spec` (factory.py:77) falls back to `find_by_model(model)`
   when the base_url is not a recognised gateway, so `qwen/*` routes to the
   **dashscope** provider (which injects dashscope-only `enable_thinking`) even
   though we are calling Groq. Passing `binding="openai"` already fixes this, but
   nothing sets it from env.

## Design — one central layer, env-only, UI-ready

Fix at the **shared LLM layer** so every caller (voice/chat/tools) benefits and
switching provider = editing config, no code:

1. **Bring `reasoning_effort` into the capability system.** Add a per-provider (and
   where needed per-model) notion of accepted `reasoning_effort` values, and have
   `_sanitize_call_kwargs` **drop or remap** it — same pattern as `response_format`.
   Safe default: unknown provider/value ⇒ **drop** (it is an optimization, never
   required) rather than send something that 400s.
2. **Let the endpoint decide the provider, not the model name.** Either (a) quick:
   add `DEEPTUTOR_AGENT_BINDING` env read by `resolve_agent_llm()` and forwarded to
   `complete()` (force generic `openai` for OpenAI-compat upstreams), or (b) clean:
   teach provider resolution to recognise known OpenAI-compat hosts (e.g.
   `api.groq.com`) as a gateway so `base_url` wins over `find_by_model`.

Reference implementation already exists: the Phase E eval shim
(`eval/inpage_agent/run_ours.py::_install_groq_shim`) does exactly this per-model
remap + forced openai binding — lift that logic into the central layer.

## UI readiness (the config-SOURCE decision — decide now, costs nothing later)

Separate **where config comes from** (env / settings / UI) from **how we adapt to
the provider** (the capability layer). The capability/adaptation layer is keyed on
the *resolved* provider and never changes regardless of the source. So:

- The adaptation work above is done **once** and a future UI needs **zero** rework
  of it.
- The only thing to design for now is the config SOURCE. Resolve provider config
  from the existing settings store (`data/user/settings/*.json`, via
  `RuntimeSettingsService`) **with env override**, not env-only. Then a future UI
  is a pure front-end (a "mask") that writes settings — the same resolver + the
  same capability layer read it. If instead we hardcode env-only reading now,
  adding a UI later means adding a settings path (small, but avoidable).

## Acceptance

- With `.env.agent` (or settings) pointed at Groq `qwen/qwen3-32b`, the voice
  agent loop completes a turn (no 400) — `reasoning_effort` remapped/dropped,
  no dashscope `enable_thinking` injected.
- Switching to Gemini requires **only** a config change; no code edit. Gemini
  behaviour is byte-identical to today (regression-guarded).
- Chat + tools call sites unaffected (shared code — needs their tests green too).
- Unit tests: capability table for `reasoning_effort`; sanitizer drop/remap;
  provider resolution by endpoint.

## Caution

Touches the SHARED LLM factory + capabilities used by chat/tools/voice (wider
blast radius than a voice-only shim). Land it behind tests with safe defaults
(unknown ⇒ drop). Verifying end-to-end needs live provider calls (hence deferred
until quota).

## Comments
