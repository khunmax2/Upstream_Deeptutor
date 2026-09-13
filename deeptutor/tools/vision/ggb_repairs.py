"""Deterministic repairs for GeoGebra commands the visualizer's model gets wrong.

Fork. Measured 2026-09-13 by running the commands the GeoGebra visualizer's
model actually wrote in UAT through the real GeoGebra applet (headless Chrome,
one ``evalCommand`` per line, the way ``web/components/Geogebra.tsx`` does):

* ``SetLabelVisible[A, true]`` -> "Unknown command". The visualizer's own
  prompt named it; GeoGebra's command is ``ShowLabel``.
* ``SetPosition[T, x, y]`` and ``SetSlider[n, a, b, s]`` -> "Unknown command".
  ``SetCoords`` moves a text or a point; a slider is made with ``Slider``, so
  a ``SetSlider`` line is dropped.
* ``InfinitePlane[A, B, C]`` (3D) -> "Unknown command", and every later line
  naming the plane fails with it; ``Plane[A, B, C]`` is the command.
* ``Point(i, j)`` / ``Point[i, j]`` with numbers -> "Illegal argument: Number i".
  A coordinate is written ``(i, j)``. ``Point(<object>, <parameter>)`` is a
  different, valid command and is left alone: only a first argument that is a
  number, or an expression over the enclosing ``Sequence``'s loop variables,
  is rewritten. ``Point[(i, j)]`` (a coordinate wrapped in Point) -> "Illegal
  argument: Point (i, j)"; the coordinate alone is what was meant.
* ``Sequence[expr, j = 1, i]`` -> "Undefined variable j". The signature is
  ``Sequence(<expression>, <variable>, <from>, <to>[, <step>])``.
* ``SetColor[A, 214, 39, 40]`` -> no error, but the object turns white: the
  components are read on a 0-1 scale. Rewritten to the hex form, which lands
  on the exact colour.
* ``Text["$$\\sum ...$$", P, true]`` -> the markup shows raw. LaTeX renders
  only with the fourth argument true and without ``$`` delimiters; a doubled
  backslash (``\\\\sum``) garbles it; a bare string assignment never renders
  LaTeX while ``FormulaText`` does. ``Text["...", x, y]`` (the point split into
  two numbers) is rebuilt as ``Text["...", (x, y)]``.

Each rule rewrites only a form measured to fail into the form measured to
work; anything a rule does not recognise passes through untouched.
"""

from __future__ import annotations

from collections.abc import Callable
import re

_IDENT = r"[A-Za-z_][A-Za-z0-9_']*"
_IDENT_RE = re.compile(rf"^{_IDENT}$")
_CLOSE = {"[": "]", "(": ")"}
_BOOLEANS = {"true", "false"}

RENAMED_COMMANDS = {
    "SetLabelVisible": "ShowLabel",
    "SetPosition": "SetCoords",
    "InfinitePlane": "Plane",
}
DROPPED_COMMANDS = frozenset({"SetSlider"})

# A LaTeX hint inside a text: a $ delimiter or a backslash command.
_LATEX_HINT = re.compile(r"\$|\\[A-Za-z]")
# A doubled backslash in front of a command or brace: \\sum -> \sum.
_DOUBLED_BACKSLASH = re.compile(r"\\\\(?=[A-Za-z{}])")
_STRING_ASSIGNMENT = re.compile(rf'^(\s*{_IDENT}\s*=\s*)"(.*)"\s*$', re.DOTALL)
_NUMERIC_REST = re.compile(r"^[\d\s.+\-*/^()]*$")


def split_args(inner: str) -> list[str]:
    """Split a command's argument text on top-level commas.

    Commas inside nested brackets, parentheses or string literals are not
    separators.
    """
    args: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    for char in inner:
        if char == '"':
            in_string = not in_string
        elif not in_string:
            if char in "[(":
                depth += 1
            elif char in "])":
                depth -= 1
            elif char == "," and depth == 0:
                args.append("".join(current).strip())
                current = []
                continue
        current.append(char)
    tail = "".join(current).strip()
    if tail or args:
        args.append(tail)
    return args


def _matching(text: str, open_idx: int) -> int | None:
    depth = 0
    in_string = False
    for idx in range(open_idx, len(text)):
        char = text[idx]
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
            if depth == 0:
                return idx
    return None


def _find_calls(command: str, name: str) -> list[tuple[int, int, int]]:
    """``(start, open, close)`` for every ``name[...]`` or ``name(...)``."""
    calls = []
    for match in re.finditer(rf"\b{name}\s*([\[(])", command):
        open_idx = match.end() - 1
        close_idx = _matching(command, open_idx)
        if close_idx is not None:
            calls.append((match.start(), open_idx, close_idx))
    return calls


Fix = Callable[[list[str], str], "str | None"]


def _rewrite_calls(command: str, name: str, fix: Fix) -> str:
    """Apply ``fix`` to every ``name`` call, innermost (rightmost) first.

    ``fix`` gets the call's arguments and its opening bracket and returns the
    replacement text for the whole call, or ``None`` to leave it.
    """
    for _ in range(64):
        for start, open_idx, close_idx in sorted(_find_calls(command, name), reverse=True):
            args = split_args(command[open_idx + 1 : close_idx])
            replacement = fix(args, command[open_idx])
            if replacement is not None and replacement != command[start : close_idx + 1]:
                command = command[:start] + replacement + command[close_idx + 1 :]
                break
        else:
            return command
    return command


def _call(name: str, open_char: str, args: list[str]) -> str:
    return f"{name}{open_char}{', '.join(args)}{_CLOSE[open_char]}"


def _rename(command: str, warnings: list[str]) -> str:
    for old, new in RENAMED_COMMANDS.items():
        pattern = rf"\b{old}(?=\s*[\[(])"
        if re.search(pattern, command):
            command = re.sub(pattern, new, command)
            warnings.append(f"Renamed {old} to {new}: GeoGebra has no {old}")
    return command


def _dropped(command: str) -> str | None:
    head = re.match(rf"^\s*({_IDENT})\s*[\[(]", command)
    if head and head.group(1) in DROPPED_COMMANDS:
        return head.group(1)
    return None


def _set_color(command: str, warnings: list[str]) -> str:
    def fix(args: list[str], open_char: str) -> str | None:
        if len(args) != 4:
            return None
        try:
            components = [float(value) for value in args[1:]]
        except ValueError:
            return None
        if min(components) < 0 or max(components) > 255 or max(components) <= 1:
            return None
        hex_code = "#" + "".join(f"{round(value):02X}" for value in components)
        warnings.append(
            f"SetColor components {', '.join(args[1:])} are 0-255; GeoGebra reads 0-1 "
            f"(the object turned white) -- rewritten as {hex_code}"
        )
        return _call("SetColor", open_char, [args[0], f'"{hex_code}"'])

    return _rewrite_calls(command, "SetColor", fix)


def _sequence_variables(command: str, warnings: list[str]) -> str:
    def fix(args: list[str], open_char: str) -> str | None:
        if len(args) < 3:
            return None
        match = re.match(rf"^({_IDENT})\s*=\s*(.+)$", args[1], re.DOTALL)
        if match is None:
            return None
        warnings.append(
            f"Sequence variable written as '{args[1]}'; the signature is "
            "Sequence(<expression>, <variable>, <from>, <to>)"
        )
        return _call(
            "Sequence", open_char, [args[0], match.group(1), match.group(2).strip(), *args[2:]]
        )

    return _rewrite_calls(command, "Sequence", fix)


def _loop_variables(command: str) -> set[str]:
    names: set[str] = set()
    for _, open_idx, close_idx in _find_calls(command, "Sequence"):
        args = split_args(command[open_idx + 1 : close_idx])
        if len(args) >= 4 and _IDENT_RE.match(args[1]):
            names.add(args[1])
    return names


def _is_number(expression: str, loop_variables: set[str]) -> bool:
    """A numeric literal, or arithmetic over the enclosing loop variables."""
    if not expression.strip():
        return False
    names = re.findall(_IDENT, expression)
    if any(name not in loop_variables for name in names):
        return False
    return bool(_NUMERIC_REST.match(re.sub(_IDENT, "", expression)))


def _is_coordinate(expression: str) -> bool:
    """A literal ``(x, y)`` or ``(x, y, z)``: parentheses spanning the whole text."""
    expression = expression.strip()
    if not expression.startswith("(") or _matching(expression, 0) != len(expression) - 1:
        return False
    return len(split_args(expression[1:-1])) in (2, 3)


def _points(command: str, warnings: list[str]) -> str:
    loop_variables = _loop_variables(command)

    def fix(args: list[str], open_char: str) -> str | None:
        if len(args) == 1 and _is_coordinate(args[0]):
            warnings.append(f"Point[{args[0]}] rewritten as the coordinate {args[0]}")
            return args[0]
        if len(args) != 2 or not _is_number(args[0], loop_variables):
            return None
        warnings.append(f"Point({', '.join(args)}) rewritten as a coordinate ({', '.join(args)})")
        return f"({args[0]}, {args[1]})"

    return _rewrite_calls(command, "Point", fix)


def _clean_latex(body: str) -> str:
    body = _DOUBLED_BACKSLASH.sub(r"\\", body)
    return body.replace("$$", "").replace("$", "").strip()


def _texts(command: str, warnings: list[str]) -> str:
    def fix(args: list[str], open_char: str) -> str | None:
        if len(args) not in (2, 3, 4):
            return None
        first = args[0]
        is_string = len(first) >= 2 and first.startswith('"') and first.endswith('"')
        new_args = list(args)
        if len(args) == 3 and args[2] not in _BOOLEANS and args[1] not in _BOOLEANS:
            # Text["...", x, y]: the point was split into two numbers.
            new_args = [first, f"({args[1]}, {args[2]})"]
        if not is_string or not _LATEX_HINT.search(first[1:-1]):
            return None if new_args == args else _call("Text", open_char, new_args)
        new_args[0] = f'"{_clean_latex(first[1:-1])}"'
        if len(new_args) == 2:
            new_args += ["false", "true"]
        elif len(new_args) == 3:
            new_args.append("true")
        else:
            new_args[3] = "true"
        return _call("Text", open_char, new_args)

    fixed = _rewrite_calls(command, "Text", fix)
    if fixed != command:
        warnings.append(
            "Text rewritten to Text(<string>, <point>) or, for LaTeX, "
            "Text(<string>, <point>, <bool>, true)"
        )
    return fixed


def _string_assignment(command: str, warnings: list[str]) -> str:
    match = _STRING_ASSIGNMENT.match(command)
    if match is None or not _LATEX_HINT.search(match.group(2)):
        return command
    warnings.append("LaTeX string assignment rewritten to FormulaText, which renders it")
    return f'{match.group(1)}FormulaText["{_clean_latex(match.group(2))}"]'


def repair_command(command: str) -> tuple[str, list[str]]:
    """Return ``(repaired command, warnings)``; an empty command means drop it."""
    dropped = _dropped(command)
    if dropped is not None:
        return "", [f"Dropped {dropped}: GeoGebra has no such command"]
    warnings: list[str] = []
    fixed = _rename(command, warnings)
    fixed = _set_color(fixed, warnings)
    fixed = _sequence_variables(fixed, warnings)
    fixed = _points(fixed, warnings)
    fixed = _texts(fixed, warnings)
    fixed = _string_assignment(fixed, warnings)
    return fixed, warnings


__all__ = ["repair_command", "split_args", "RENAMED_COMMANDS", "DROPPED_COMMANDS"]
