"""GeoGebra command repairs, driven by commands the visualizer's model wrote in UAT.

Fork. Every "before" string below is a command the model actually produced
(2026-09-13) that the real GeoGebra applet rejected or misrendered; every
"after" is the form measured to work in the same applet. The last cases pin
what must NOT be touched.
"""

from __future__ import annotations

import pytest

from deeptutor.tools.vision.ggb_repairs import repair_command, split_args
from deeptutor.tools.vision.ggb_validator import validate_ggbscript


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # Unknown commands: renamed to GeoGebra's own.
        ("SetLabelVisible[V, true]", "ShowLabel[V, true]"),
        ("SetPosition[Text1,0,6]", "SetCoords[Text1,0,6]"),
        (
            "Ecliptic = InfinitePlane[(0,0,0), (1,0,0), (0,1,0)]",
            "Ecliptic = Plane[(0,0,0), (1,0,0), (0,1,0)]",
        ),
        # 0-255 colour components turned the object white.
        ("SetColor[V, 214, 39, 40]", 'SetColor[V, "#D62728"]'),
        ("SetColor[R, 120, 120, 120]", 'SetColor[R, "#787878"]'),
        # Point with numbers: "Illegal argument: Number i".
        (
            "T1=Sequence[Sequence[Point[i,j],i,1,j],j,1,n]",
            "T1=Sequence[Sequence[(i, j),i,1,j],j,1,n]",
        ),
        (
            "T2 = Sequence(Sequence[Point(j, n + 1 - i), i, 1, j], j, 1, n)",
            "T2 = Sequence(Sequence[(j, n + 1 - i), i, 1, j], j, 1, n)",
        ),
        ("P = Point(2, 3)", "P = (2, 3)"),
        # Sequence variable written as j = 1: "Undefined variable j".
        (
            "Sequence[Sequence[(i, j), j = 1, i], i = 1, n]",
            "Sequence[Sequence[(i, j), j, 1, i], i, 1, n]",
        ),
        # LaTeX in Text: raw markup until the fourth argument is true.
        (
            r'Text["$$\sum_{k=1}^{n} k = \frac{n(n+1)}{2}$$", (n/2, n + 2.5), true]',
            r'Text["\sum_{k=1}^{n} k = \frac{n(n+1)}{2}", (n/2, n + 2.5), true, true]',
        ),
        (
            r'Text3=Text["พื้นที่สี่เหลี่ยม = n \times (n+1)",(n/2,-4),true]',
            r'Text3=Text["พื้นที่สี่เหลี่ยม = n \times (n+1)", (n/2,-4), true, true]',
        ),
        # A doubled backslash garbles LaTeX.
        (
            r'Text["\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}", (0, -1)]',
            r'Text["\sum_{i=1}^{n} i = \frac{n(n+1)}{2}", (0, -1), false, true]',
        ),
        # A bare string never renders LaTeX; FormulaText does.
        (
            r'Text1="\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}"',
            r'Text1=FormulaText["\sum_{i=1}^{n} i = \frac{n(n+1)}{2}"]',
        ),
        # Text["...", x, y] is not a signature; the point was split in two.
        ('T9=Text["label",(a+b)/2,a+b+0.8]', 'T9=Text["label", ((a+b)/2, a+b+0.8)]'),
    ],
)
def test_measured_failures_are_repaired(before: str, after: str) -> None:
    fixed, warnings = repair_command(before)
    assert fixed == after
    assert warnings


def test_an_unknown_setslider_is_dropped() -> None:
    fixed, warnings = repair_command("SetSlider[n,1,10,1]")
    assert fixed == ""
    assert any("SetSlider" in w for w in warnings)


@pytest.mark.parametrize(
    "command",
    [
        # Point on an object at a parameter is a different, valid command.
        "P = Point(c, 0.5)",
        "Q = Point(f)",
        "R = Point(A, v)",
        # Already-correct colour forms.
        'SetColor[A, "#1F77B4"]',
        "SetColor[A, 0.839, 0.153, 0.157]",
        "SetColor[A, 1, 0, 0]",
        'SetColor[A, "Red"]',
        # Plain text, correct LaTeX text, and a correct Sequence.
        'Text["รวม = n(n+1) จุด", (n/2, -3.5), true]',
        r'Text["\sum_{k=1}^{n} k", (0, 6.5), false, true]',
        'Text2="n = "+n',
        "L = Sequence(Sequence((i, j), j, 1, i), i, 1, n)",
        "ShowLabel[t, false]",
        "f(x) = x^2",
    ],
)
def test_correct_commands_pass_untouched(command: str) -> None:
    fixed, warnings = repair_command(command)
    assert fixed == command
    assert warnings == []


def test_repairs_are_idempotent() -> None:
    once, _ = repair_command(r'Text["$$\\sum_{k=1}^{n} k$$", (0, 1), true]')
    twice, warnings = repair_command(once)
    assert twice == once
    assert warnings == []


def test_split_args_respects_nesting_and_strings() -> None:
    assert split_args('"a, b", (1, 2), f(x, y), [3, 4]') == [
        '"a, b"',
        "(1, 2)",
        "f(x, y)",
        "[3, 4]",
    ]


def test_the_validator_applies_the_repairs_to_a_whole_payload() -> None:
    # The sigma payload from UAT: before the repairs three lines raised GeoGebra
    # errors and the formula showed as raw markup.
    script = "\n".join(
        [
            "n=Slider[1,10,1]",
            'SetCaption[n,"n"]',
            "T1=Sequence[Sequence[Point[i,j],i,1,j],j,1,n]",
            "SetColor[T1,31,119,180]",
            r'Text1=Text["$$\sum_{k=1}^{n} k$$",(n/2,-2),true]',
            "SetLabelVisible[T1, false]",
            "SetSlider[n,1,10,1]",
        ]
    )
    fixed, warnings, errors = validate_ggbscript(script)
    assert errors == []
    assert "Point[" not in fixed and "Point(" not in fixed
    assert "SetLabelVisible" not in fixed
    assert "SetSlider" not in fixed
    assert "$" not in fixed
    assert '"#1F77B4"' in fixed
    assert warnings
