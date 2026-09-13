"""Fork: the image carries Manim, so the math animator and visualize's video path work.

Upstream leaves Manim to the runtime ``DEEPTUTOR_EXTRAS`` hook, which fails in
the production image: pycairo has no Linux wheel and that image has no
compiler, so the feature answers "math_animator requires optional
dependencies" (fork UAT, 2026-09-12). The fork builds Manim in the
``python-base`` stage and names its runtime libraries in ``production``. An
upstream sync that takes upstream's Dockerfile would drop both without an
error; these assertions make that a red test.
"""

from __future__ import annotations

from pathlib import Path
import re

_REPO = Path(__file__).resolve().parents[2]


def _stages() -> dict[str, str]:
    """Dockerfile text per build stage, keyed by the ``AS <name>`` alias."""
    stages: dict[str, list[str]] = {}
    current: str | None = None
    for line in (_REPO / "Dockerfile").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^FROM\s+.*\s+AS\s+(\S+)\s*$", line, flags=re.IGNORECASE)
        if match:
            current = match.group(1)
            stages[current] = []
            continue
        if current is not None:
            stages[current].append(line)
    return {name: "\n".join(body) for name, body in stages.items()}


def test_python_base_builds_manim_with_the_headers_pycairo_needs() -> None:
    base = _stages()["python-base"]
    assert "pip install -r requirements/math-animator.txt" in base
    assert "libcairo2-dev" in base
    assert "libpango1.0-dev" in base


def test_production_carries_manims_runtime_libraries() -> None:
    production = _stages()["production"]
    # fonts-thai-tlwg: without a Thai font Pango draws Thai labels as boxes.
    for package in ("libcairo2", "libpango-1.0-0", "libpangocairo-1.0-0", "fonts-thai-tlwg"):
        assert re.search(rf"^\s+{re.escape(package)} \\$", production, flags=re.MULTILINE), package


def test_production_carries_latex_for_mathtex() -> None:
    # Without LaTeX a MathTex the model writes despite the prompt fails the
    # whole request; the smaller latex-base/-recommended set fails on Manim's
    # default template, so the -extra/-science/cm-super set is the floor.
    production = _stages()["production"]
    for package in (
        "texlive-latex-base",
        "texlive-latex-extra",
        "texlive-fonts-recommended",
        "texlive-science",
        "cm-super",
        "dvisvgm",
    ):
        assert re.search(rf"^\s+{re.escape(package)} \\$", production, flags=re.MULTILINE), package


def test_production_takes_site_packages_from_python_base() -> None:
    production = _stages()["production"]
    assert "COPY --from=python-base /usr/local/lib/python3.11/site-packages" in production


def test_the_math_animator_requirements_name_manim() -> None:
    text = (_REPO / "requirements" / "math-animator.txt").read_text(encoding="utf-8")
    assert re.search(r"^manim\b", text, flags=re.MULTILINE)


def test_the_app_user_has_a_writable_home() -> None:
    # supervisord's user= keeps root's HOME=/root, so the backend ran with a
    # HOME it cannot read: Manim died at import on /root/.config/manim/manim.cfg
    # (PermissionError, UAT 2026-09-13). The home exists and both backend
    # programs are handed it.
    stages = _stages()
    assert "install -d -o deeptutor -g deeptutor /home/deeptutor" in stages["production"]
    for name in ("production", "development"):
        backend = stages[name].split("[program:backend]", 1)[1].split("[program:", 1)[0]
        assert 'HOME="/home/deeptutor"' in backend, name
