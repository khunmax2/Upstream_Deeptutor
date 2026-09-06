#!/usr/bin/env python3
"""Find the Thai gaps a translation file cannot close.

`build_th_locale.py` checks the translation: coverage, interpolation parity, keys
that no longer exist upstream. OpenMAIC's own `check-i18n-keys.mjs` checks that
every locale carries every key. Both pass while the app still shows Chinese and
English, because the things they check are not where those come from.

Three kinds of gap live outside the locale files, and every one of them was found
by *using the app* rather than by any check:

  hardcoded      a UI string written in source instead of passed through `t()`.
                 `toast.error('Persistence is unavailable...')` renders that
                 English sentence in every locale there will ever be.

  cjk-literal    a Chinese string literal in a component. The narrowest and most
                 certain signal there is: source files hold identifiers and
                 markup, so a CJK run in one is display text that skipped i18n.

  language-list  an array of language codes offering `zh` and `en` but not `th`.
                 The label exists — `settings.lang_th` is "ไทย" in every locale —
                 and cannot be selected, because what is missing is an option and
                 an option is data, not text. A translation cannot add one.

Reporting is the point. This does not decide what to do about a finding; it makes
sure the finding is in front of somebody, on every upstream update, rather than
waiting to be tripped over.

    python check_openmaic_i18n_gaps.py --openmaic ../OpenMAIC
    python check_openmaic_i18n_gaps.py --openmaic ../OpenMAIC --strict   # exit 1

`--strict` is for the moment the list is empty and you want it to stay empty. It
is not there yet: the known findings are listed in `KNOWN` below and reported
separately, so a new one is visible without being buried under the old ones.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

# Where UI text lives. Locale files are excluded — Chinese belongs in zh-CN.json.
SOURCE_DIRS = ("app", "components", "lib", "hooks")
SOURCE_SUFFIXES = {".ts", ".tsx"}
SKIP_PARTS = {"node_modules", ".next", "dist", "locales", "__tests__", "tests"}

# Paths that are the translation system rather than users of it. `lib/i18n/`
# holds the locale tables themselves — `workbench.ts` carries `workbenchZh`, the
# Chinese locale, in TypeScript because hook-free helpers need it synchronously.
# Chinese there is the point. Scanning it reported 245 findings that were all
# correct code, which is the kind of noise that gets a checker switched off.
SKIP_PREFIXES = ("lib/i18n/",)

# Provider-supplied proper nouns. Azure names its voices `晓晓 (女)`; that is the
# voice's name, not product copy, and translating it would stop it matching what
# the provider documents.
VOICE_NAME = re.compile(r"^\s*(?:name|label|displayName):\s*['\"]")

CJK = re.compile(r"[一-鿿぀-ヿ]")

# A UI message handed a bare string. `t(...)` inside is what makes it fine, so a
# quote directly after the paren is what makes it not.
TOAST_LITERAL = re.compile(
    r"""\b(?:toast\.(?:error|success|info|warning|loading)|alert)\(\s*['"]([^'"]{12,})['"]"""
)

# An array of ISO-639 codes. Anchored on `zh` and `en` together so that ordinary
# string arrays do not match.
LANG_ARRAY = re.compile(r"\[[^\]]*['\"]zh['\"][^\]]*['\"]en['\"][^\]]*\]", re.S)

# Findings already reported and being carried deliberately. Keeping them here
# rather than deleting them is what lets `--strict` mean "nothing new".
KNOWN = {
    ("app/page.tsx", "cjk-literal"),
    ("app/page.tsx", "hardcoded"),
    ("lib/hooks/use-home-discovery.tsx", "hardcoded"),
    # `funasr` declares what SenseVoice can actually transcribe, and Thai is not
    # on that list. Correct as written: adding `th` would turn a missing menu
    # entry into a wrong answer. Carried here so --strict stays usable.
    ("lib/audio/constants.ts", "language-list"),
}


def source_files(root: Path):
    for directory in SOURCE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SOURCE_SUFFIXES:
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            yield path


def scan(root: Path) -> list[tuple[str, str, int, str]]:
    """Return (relative path, kind, line number, evidence)."""
    findings: list[tuple[str, str, int, str]] = []

    for path in source_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(SKIP_PREFIXES):
            continue

        # A Chinese string on a server route is almost always a model prompt, not
        # something a reader sees. Both matter and they are not the same problem:
        # UI text in Chinese shows Chinese; a prompt in Chinese steers the model
        # toward answering in it. Counting them together hid both.
        is_prompt = (
            rel.startswith("app/api/") or "prompt" in rel.lower() or "/agents/" in rel
        )

        for number, line in enumerate(text.splitlines(), 1):
            # Checked first and unconditionally: an English hardcoded string has
            # no CJK in it, so gating this on the CJK match — which a first pass
            # here did — silently dropped every one of them.
            match = TOAST_LITERAL.search(line)
            if match:
                findings.append((rel, "hardcoded", number, match.group(1)[:90]))

            hit = CJK.search(line)
            if not hit:
                continue
            stripped = line.lstrip()
            # Comments are not shipped to anyone. A Chinese comment explaining a
            # geometry helper is a maintenance question, not a localisation one,
            # and counting it buried the context-menu labels that do matter.
            if stripped.startswith(("*", "//", "/*")):
                continue
            if VOICE_NAME.match(line):
                continue
            if "//" not in line[: line.find(hit.group())]:
                kind = "prompt-literal" if is_prompt else "cjk-literal"
                findings.append((rel, kind, number, line.strip()[:90]))

        for match in LANG_ARRAY.finditer(text):
            block = match.group(0)
            if "'th'" in block or '"th"' in block:
                continue
            number = text[: match.start()].count("\n") + 1
            codes = re.findall(r"['\"]([a-z]{2,3}(?:-[A-Za-z]{2,4})?)['\"]", block)
            findings.append(
                (rel, "language-list", number, f"{len(codes)} codes, no 'th': {', '.join(codes[:10])}")
            )

    return sorted(findings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openmaic", type=Path, default=Path("../OpenMAIC"))
    parser.add_argument("--strict", action="store_true", help="exit 1 on anything not in KNOWN")
    args = parser.parse_args()

    root = args.openmaic.resolve()
    if not (root / "package.json").is_file():
        print(f"[i18n-gaps] not an OpenMAIC checkout: {root}", file=sys.stderr)
        return 2

    findings = scan(root)
    known = [f for f in findings if (f[0], f[1]) in KNOWN]
    fresh = [f for f in findings if (f[0], f[1]) not in KNOWN]

    label = {
        "hardcoded": "UI text written in source, never passed through t()",
        "cjk-literal": "Chinese literal in a component — a reader sees this",
        "prompt-literal": "Chinese literal on a server route — a model reads this",
        "language-list": "language options with no Thai",
    }

    print(f"[i18n-gaps] {root}")
    for title, group in (("NEW", fresh), ("known, already reported", known)):
        if not group:
            continue
        print(f"\n[i18n-gaps] {title}: {len(group)}")
        for rel, kind, number, evidence in group:
            print(f"  {kind:14} {rel}:{number}")
            print(f"  {'':14} {label[kind]}")
            print(f"  {'':14} {evidence}")

    if not findings:
        print("\n[i18n-gaps] nothing found — which is worth doubting more than trusting.")
        return 0

    print(
        "\n[i18n-gaps] None of these can be fixed by editing th-TH.partial.json."
        "\n[i18n-gaps] Each needs a source change, so each is a patch — and each is an"
        "\n[i18n-gaps] upstream candidate, since none of them is about DeepTutor."
    )

    if args.strict and fresh:
        print(f"\n[i18n-gaps] --strict: {len(fresh)} finding(s) not in KNOWN.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
