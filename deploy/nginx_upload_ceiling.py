#!/usr/bin/env python3
"""The upload ceiling of DeepWitya's ``location /deepwitya`` block on the host.

That block lives in a server file other teams share
(``/etc/nginx/sites-available/sansarnnews-ssl``). Without a
``client_max_body_size`` inside it, nginx applies its 1 MB default to every
DeepWitya upload -- knowledge-base files, reading materials -- and answers 413
itself, before the app (which allows 200 MB) ever sees the request. The
go-live cutover only swapped that block's port, so the ceiling that the old
``/deepwitya2`` snippet and the go-live preview carried never reached
production. Found 2026-09-15: a 1,052,664-byte PDF failed and a smaller text
file passed, which read as "PDFs with images fail".

``--apply`` adds one line inside the block, under a marker comment, so
``--remove`` takes out exactly what ``--apply`` put in. Nothing outside the
block changes; an existing ceiling inside it is set to the new value.

    python3 deploy/nginx_upload_ceiling.py <file> --check
    python3 deploy/nginx_upload_ceiling.py <file> --apply [200m]
    python3 deploy/nginx_upload_ceiling.py <file> --remove

Exit status 0 when done or nothing to do, 1 when refused (no block, several
blocks, no closing brace, not an nginx size). Called by
``deploy/apply-nginx-golive.sh``.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sys

MARK = "# DeepWitya upload ceiling — see deploy/apply-nginx-golive.sh"
DEFAULT_CEILING = "200m"
NGINX_DEFAULT = "1m"

# `location /deepwitya {` exactly: not /deepwitya/studio, not /deepwitya2.
_OPEN = re.compile(r"^([ \t]*)location\s+/deepwitya\s*\{[ \t]*\n", re.M)
_CEILING = re.compile(r"^([ \t]*client_max_body_size\s+)(\S+?)(\s*;)", re.M)
_SIZE = re.compile(r"^\d+[kKmMgG]?$")


class Refused(Exception):
    """The file is not in a shape this edits safely; edit it by hand."""


@dataclass(frozen=True)
class Block:
    body: int  # offset just after the `location /deepwitya {` line
    end: int  # offset just after the block's closing brace
    indent: str  # indentation of the `location` line


def find_block(text: str) -> Block:
    opens = list(_OPEN.finditer(text))
    if not opens:
        raise Refused("ไม่มี `location /deepwitya {`")
    if len(opens) > 1:
        raise Refused(f"มี `location /deepwitya {{` {len(opens)} ที่ — ต้องแก้มือ")
    opening = opens[0]
    indent = opening.group(1)
    # The block ends at the first `}` on its own line at the same indentation,
    # the rule the other edits in apply-nginx-golive.sh use.
    close = re.compile(r"^" + re.escape(indent) + r"\}", re.M).search(text, opening.end())
    if not close:
        raise Refused("หา closing brace ของ location /deepwitya ไม่เจอ")
    return Block(body=opening.end(), end=close.end(), indent=indent)


def ceilings(text: str) -> list[str]:
    """The client_max_body_size values set inside the block (empty: nginx's 1m)."""
    block = find_block(text)
    return [m.group(2) for m in _CEILING.finditer(text, block.body, block.end)]


def apply(text: str, value: str = DEFAULT_CEILING) -> tuple[str, str]:
    """The text with the block's ceiling at ``value``, and what changed."""
    if not _SIZE.match(value):
        raise Refused(f"ไม่ใช่ขนาดแบบ nginx: {value!r}")
    block = find_block(text)
    inner = text[block.body : block.end]
    found = [m.group(2) for m in _CEILING.finditer(inner)]
    if found == [value]:
        return text, f"มี client_max_body_size {value} อยู่แล้ว — ไม่แตะ"
    if found:
        inner = _CEILING.sub(lambda m: m.group(1) + value + m.group(3), inner)
        return (
            text[: block.body] + inner + text[block.end :],
            f"client_max_body_size {', '.join(found)} → {value}",
        )
    pad = block.indent + "    "
    lines = f"{pad}{MARK}\n{pad}client_max_body_size {value};\n"
    return (
        text[: block.body] + lines + text[block.body :],
        f"+ client_max_body_size {value} (+2 บรรทัด)",
    )


def remove(text: str) -> tuple[str, bool]:
    """The text without the ceiling ``apply`` added; a ceiling set by hand stays."""
    pattern = re.compile(
        r"^[ \t]*" + re.escape(MARK) + r"\n[ \t]*client_max_body_size\s+\S+?\s*;\n", re.M
    )
    new = pattern.sub("", text, count=1)
    return new, new != text


def main(argv: list[str]) -> int:
    # A report must never fail an edit that already landed: the caller restores
    # the backup on a non-zero exit. Keep the terminal's encoding, but escape
    # what it cannot show (Thai on a cp1252 console) instead of raising.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    if len(argv) < 2 or argv[1] not in {"--check", "--apply", "--remove"}:
        print(__doc__, file=sys.stderr)
        return 1
    path, mode = argv[0], argv[1]
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    try:
        if mode == "--check":
            found = ceilings(text)
            state = (
                f"client_max_body_size {', '.join(found)}"
                if found
                else f"ไม่มี client_max_body_size — nginx ใช้ค่า default {NGINX_DEFAULT}"
            )
            print(f"  {path}: location /deepwitya {state}")
            return 0
        if mode == "--apply":
            new, what = apply(text, argv[2] if len(argv) > 2 else DEFAULT_CEILING)
        else:
            new, removed = remove(text)
            what = "เอาเพดานอัปโหลดของ go-live ออกแล้ว" if removed else "ไม่มีเพดานอัปโหลดของ go-live"
    except Refused as error:
        print(f"!! {path}: {error}", file=sys.stderr)
        return 1
    if new != text:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new)
    print(f"  {path}: location /deepwitya {what}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
