"""The bridge must not drop a provider OpenMAIC actually supports.

`build()` skips any binding missing from `BINDING_TO_PROVIDER` and records a
note. Nothing downstream reads those notes: the settings save that triggered
the refresh still succeeds, the file is still written, and the course studio
simply comes up with nothing to call. That is how an OpenRouter deployment
reached production with an empty `providers:` section — no error anywhere, just
a studio that could not generate.

So these pin the mapping itself rather than the notes.
"""

from __future__ import annotations

from deeptutor.services.config.openmaic_bridge import BINDING_TO_PROVIDER, build


def _catalog(binding: str, base_url: str) -> dict:
    return {
        "services": {
            "llm": {
                "active_profile_id": "p1",
                "profiles": [
                    {
                        "id": "p1",
                        "binding": binding,
                        "base_url": base_url,
                        "api_key": "sk-test",
                        "models": [{"id": "m1", "model": "some/model"}],
                    }
                ],
            }
        }
    }


def test_openrouter_maps_to_its_own_openmaic_id() -> None:
    """OpenRouter is a first-class provider in OpenMAIC, not an `openai` relay.

    `LLM_ENV_MAP.OPENROUTER = 'openrouter'` in
    integration/maic/lib/server/provider-config.ts. Flattening it to `openai`
    would also work over the wire, but it would label the provider as something
    it is not, and the id exists precisely so it does not have to be.
    """
    assert BINDING_TO_PROVIDER["providers"]["openrouter"] == "openrouter"


def test_an_openrouter_catalog_produces_a_provider() -> None:
    sections, notes = build(
        _catalog("openrouter", "https://openrouter.ai/api/v1"), "host.docker.internal"
    )

    assert "openrouter" in sections.get("providers", {}), (
        f"OpenRouter was dropped from the generated config; notes were: {notes}"
    )
    assert sections["providers"]["openrouter"]["baseUrl"] == "https://openrouter.ai/api/v1"


def test_an_unknown_binding_is_skipped_with_a_note() -> None:
    """The skip path stays intact — this is not a licence to map everything."""
    sections, notes = build(
        _catalog("no-such-vendor", "https://example.invalid/v1"), "host.docker.internal"
    )

    assert "providers" not in sections
    assert any("no-such-vendor" in note for note in notes)


def test_every_providers_target_is_an_id_openmaic_declares() -> None:
    """Guard against inventing an id: a value OpenMAIC does not know is dropped
    on its side instead of ours, which is the same silence one layer later.

    The list mirrors `LLM_ENV_MAP` in
    integration/maic/lib/server/provider-config.ts.
    """
    openmaic_llm_ids = {
        "openai",
        "azure",
        "atlascloud",
        "anthropic",
        "google",
        "deepseek",
        "qwen",
        "kimi",
        "minimax",
        "glm",
        "siliconflow",
        "doubao",
        "openrouter",
        "grok",
        "tencent-hunyuan",
        "xiaomi",
        "ollama",
        "lemonade",
        "bedrock",
    }
    unknown = set(BINDING_TO_PROVIDER["providers"].values()) - openmaic_llm_ids
    assert not unknown, f"not ids OpenMAIC declares: {sorted(unknown)}"
