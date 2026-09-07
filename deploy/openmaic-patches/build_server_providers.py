#!/usr/bin/env python3
"""Write OpenMAIC's `server-providers.yml` from DeepTutor's own provider settings.

Two applications side by side, each with its own provider configuration, is the
seam a customer notices first: nobody expects to type the same API key twice.
Closing it needed no patch. OpenMAIC already reads a server-side
`server-providers.yml` covering `providers` (LLM), `tts`, `asr`, `pdf`, `image`,
`video` and `web-search` — its own `docker-compose.yml` even carries the mount
line, commented out. What was missing was something to write the file.

    DeepTutor  data/user/settings/model_catalog.json
                        │  this script
                        ▼
    OpenMAIC   /app/server-providers.yml   (read-only mount)

Three things this has to get right, and each was learned the hard way:

**Container addresses.** A URL that works in DeepTutor's settings page may be
`http://localhost:11434`, and inside OpenMAIC's container `localhost` is that
container. Every rewritten URL is checked and loopback is replaced with
`host.docker.internal`, which the compose file maps. Getting this wrong produces
"connection refused" from a service that is plainly running.

**Names differ.** DeepTutor calls it `gemini`, `stt` and `search`; OpenMAIC calls
the same things `google`, `asr` and `web-search`. An unmapped name is skipped and
reported rather than guessed at, because a provider id OpenMAIC does not know is
silently ignored by its loader — a wrong guess would look exactly like success.

**The output holds secrets.** It is written under `data/`, which is gitignored,
and nothing here prints a key: `--dry-run` shows the file with every credential
masked, which is what makes it safe to paste into a bug report.

    python build_server_providers.py --dry-run     # show it, keys masked
    python build_server_providers.py               # write it
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# DeepTutor's `binding` → the provider id OpenMAIC knows, **per section**.
#
# Not one table, because the same vendor is named differently in each capability:
# OpenAI is `openai` for LLM, `openai-tts` for speech and `openai-whisper` for
# recognition. A first version used a single table and emitted `openai` in all
# three; OpenMAIC's loader ignores ids it does not recognise, so the TTS and ASR
# entries would have been dropped in silence and the file would have looked
# entirely correct. Verified against provider-config.ts's own env maps.
#
# Anything absent here is reported and skipped rather than guessed at.
BINDING_TO_PROVIDER: dict[str, dict[str, str]] = {
    "providers": {
        "openai": "openai",
        "azure": "azure",
        "azure_openai": "azure",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "gemini": "google",
        "google": "google",
        "deepseek": "deepseek",
        "qwen": "qwen",
        "dashscope": "qwen",
        "kimi": "kimi",
        "moonshot": "kimi",
        "minimax": "minimax",
        "glm": "glm",
        "zhipu": "glm",
        "siliconflow": "siliconflow",
        "doubao": "doubao",
        "volcengine": "doubao",
        "ollama": "ollama",
        "lemonade": "lemonade",
        "atlascloud": "atlascloud",
        # OpenAI-compatible relays have no id of their own; they are `openai`
        # with a different base URL, which is exactly how OpenMAIC models them.
        "groq": "openai",
        "custom": "openai",
    },
    "tts": {
        "openai": "openai-tts",
        "custom": "openai-tts",
        "groq": "openai-tts",
        "azure": "azure-tts",
        "glm": "glm-tts",
        "qwen": "qwen-tts",
        "doubao": "doubao-tts",
        "elevenlabs": "elevenlabs-tts",
        "minimax": "minimax-tts",
        "lemonade": "lemonade-tts",
        "voxcpm": "voxcpm-tts",
    },
    "asr": {
        "openai": "openai-whisper",
        "custom": "openai-whisper",
        "groq": "openai-whisper",
        "whisper": "openai-whisper",
        "azure": "azure-asr",
        "qwen": "qwen-asr",
        "funasr": "funasr-asr",
        "lemonade": "lemonade-asr",
    },
    "web-search": {
        "tavily": "tavily",
        "bocha": "bocha",
        "brave": "brave",
        "baidu": "baidu",
        "searxng": "searxng",
        "minimax": "minimax",
        "doubao": "doubao",
        "claude": "claude",
        "anthropic": "claude",
    },
    "pdf": {
        "mineru": "mineru",
        "mineru-cloud": "mineru-cloud",
        "unpdf": "unpdf",
    },
    # OpenMAIC's image and video sections exist; no DeepTutor binding has been
    # seen for them yet, so they stay empty rather than being guessed at.
    "image": {},
    "video": {},
}

# DeepTutor service → OpenMAIC YAML section. `embedding` and `task` have no
# counterpart: OpenMAIC does its own retrieval and has no second model slot.
SERVICE_TO_SECTION = {
    "llm": "providers",
    "tts": "tts",
    "stt": "asr",
    "search": "web-search",
    "imagegen": "image",
    "videogen": "video",
}

LOOPBACK = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def container_reachable(url: str, replacement: str) -> tuple[str, bool]:
    """Point a host-loopback URL at the host as the container sees it."""
    if not url:
        return url, False
    for host in LOOPBACK:
        for prefix in (f"//{host}:", f"//{host}/"):
            if prefix in url:
                return url.replace(host, replacement, 1), True
        if url.endswith(f"//{host}"):
            return url.replace(host, replacement, 1), True
    return url, False


def active_profile(service: dict) -> dict | None:
    """The profile the operator actually selected, not merely the first one."""
    profiles = service.get("profiles") or []
    if not profiles:
        return None
    wanted = service.get("active_profile_id")
    for profile in profiles:
        if profile.get("id") == wanted:
            return profile
    return profiles[0]


def build(catalog: dict, host_alias: str) -> tuple[dict, list[str]]:
    sections: dict[str, dict] = {}
    notes: list[str] = []

    for service_name, service in (catalog.get("services") or {}).items():
        section = SERVICE_TO_SECTION.get(service_name)
        if section is None:
            if (service.get("profiles") or []) and service_name not in ("embedding", "task"):
                notes.append(f"skipped service '{service_name}' — OpenMAIC has no section for it")
            continue

        profile = active_profile(service)
        if not profile:
            continue

        binding = (profile.get("binding") or profile.get("provider") or "").strip().lower()
        raw_base = (profile.get("base_url") or "").strip()

        # A vendor's own id and its OpenAI-compatible shim are different
        # protocols wearing the same name. DeepTutor talks to Gemini through
        # `.../v1beta/openai/`; OpenMAIC's `google` provider is `type: 'google'`
        # and appends native Gemini paths to whatever base it is given, so it
        # built `.../v1beta/openai/models/...` and every call returned
        # `AI_APICallError: Not Found`.
        #
        # The URL says which protocol is meant, so read it rather than the name:
        # a base ending in `/openai` is the compatible shim, and OpenMAIC models
        # exactly that as its generic `openai` provider.
        compat = raw_base.rstrip("/").endswith("/openai")
        if compat and section == "providers":
            provider_id = "openai"
            notes.append(
                f"{service_name}: base URL is an OpenAI-compatible endpoint, so it is "
                f"configured as 'openai' rather than '{binding}' — the native provider "
                f"would append its own paths and 404."
            )
        else:
            provider_id = BINDING_TO_PROVIDER.get(section, {}).get(binding)
        if not provider_id:
            notes.append(
                f"skipped {service_name}: binding '{binding}' has no OpenMAIC id in section "
                f"'{section}'. Add it to BINDING_TO_PROVIDER[{section!r}] if OpenMAIC "
                f"supports that provider there."
            )
            continue

        api_key = (profile.get("api_key") or "").strip()
        base_url, rewritten = container_reachable(raw_base, host_alias)
        if rewritten:
            notes.append(f"{service_name}: rewrote a loopback base_url to {host_alias}")

        if not api_key and not base_url:
            notes.append(f"skipped {service_name}: neither an API key nor a base URL is set")
            continue

        entry: dict[str, object] = {}
        if api_key:
            entry["apiKey"] = api_key
        if base_url:
            entry["baseUrl"] = base_url
        models = [m.get("model") or m.get("name") for m in (profile.get("models") or [])]
        models = [m for m in models if m]
        if models:
            entry["models"] = models

        # Speech is the one section where the model does not settle the request.
        # A self-hosted engine ships its own voices, and the built-in default the
        # client would otherwise send — `alloy` for `openai-tts` — is a name it
        # has never heard of:
        #
        #   provider=openai-tts, voice=alloy -> OpenAI TTS API error: Bad Request
        #
        # `voices:` is authoritative server-side and is surfaced to the picker,
        # so the reader is offered the voice the request will actually use.
        if section == "tts":
            voices = [m.get("voice") for m in (profile.get("models") or []) if m.get("voice")]
            voices = list(dict.fromkeys(v for v in voices if v))
            if voices:
                entry["voices"] = voices
            else:
                notes.append(
                    f"{service_name}: no voice named in DeepTutor's profile, so the "
                    "provider's own default will be used. If this endpoint has its own "
                    "voice list, name one on the model in DeepTutor's settings."
                )

        sections.setdefault(section, {})[provider_id] = entry

    return sections, notes


def to_yaml(sections: dict, mask: bool) -> str:
    """Emit YAML by hand — one dependency fewer, and the shape is this simple."""

    def scalar(value: str) -> str:
        return json.dumps(value)  # quotes and escapes exactly like YAML wants

    lines = [
        "# Generated by deploy/openmaic-patches/build_server_providers.py",
        "# from DeepTutor's data/user/settings/model_catalog.json.",
        "#",
        "# Do not edit by hand: the next run overwrites it. Change the provider in",
        "# DeepTutor's settings and run the script again.",
        "#",
        "# Contains credentials. It lives under data/, which is gitignored.",
        "",
    ]
    for section in ("providers", "tts", "asr", "pdf", "image", "video", "web-search"):
        entries = sections.get(section)
        if not entries:
            continue
        lines.append(f"{section}:")
        for provider_id, entry in sorted(entries.items()):
            lines.append(f"  {provider_id}:")
            for key, value in entry.items():
                if isinstance(value, list):
                    lines.append(f"    {key}:")
                    lines.extend(f"      - {scalar(v)}" for v in value)
                elif key == "apiKey" and mask:
                    lines.append(f"    {key}: {scalar('***' + str(value)[-4:] if value else '')}")
                else:
                    lines.append(f"    {key}: {scalar(str(value))}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path("data/user/settings"))
    parser.add_argument("--out", type=Path, default=Path("data/user/openmaic/server-providers.yml"))
    parser.add_argument(
        "--host-alias",
        default="host.docker.internal",
        help="what the container should call the host (default: host.docker.internal)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print it with keys masked")
    args = parser.parse_args()

    catalog_path = args.settings / "model_catalog.json"
    if not catalog_path.is_file():
        print(f"[server-providers] not found: {catalog_path}", file=sys.stderr)
        return 2

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    sections, notes = build(catalog, args.host_alias)

    if not sections:
        print("[server-providers] nothing to write — no provider in DeepTutor maps to OpenMAIC.")
        for note in notes:
            print(f"  {note}")
        return 1

    for note in notes:
        print(f"[server-providers] {note}")

    counts = ", ".join(f"{name} {len(entries)}" for name, entries in sorted(sections.items()))
    print(f"[server-providers] {counts}")

    if args.dry_run:
        print()
        print(to_yaml(sections, mask=True))
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_yaml(sections, mask=False), encoding="utf-8", newline="\n")
    print(f"[server-providers] wrote {args.out}")
    print("[server-providers] mount it read-only at /app/server-providers.yml and restart openmaic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
