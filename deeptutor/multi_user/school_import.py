"""Fork: CSV import of student accounts (school roles design, Phase 3a).

One file at term start instead of a hundred dialogs::

    username,password,classroom
    somchai.k,,ม.4/1
    naree.p,Temp-1234!,ม.4/1

* ``username`` follows the same rule as ``POST /api/auth/users``
  (``RegisterRequest``: an email address, or 3-64 of ``A-Za-z0-9_-.``);
* ``password`` may be empty -- one is generated (12 letters and digits) and
  returned **once** in the report; nothing here logs it;
* ``classroom`` is a classroom name; unknown names are an error for that
  row unless the caller asks for them to be created.

Every account is created with preset ``student`` through
:func:`deeptutor.services.auth.add_user` -- the same code as the admin
route -- then added to its classroom, which applies the class defaults and
derives the guardian links (:mod:`classrooms`). A row whose username exists
is ``skipped``, so a file can be re-run after one line is fixed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import io
import re
import secrets
import string
from typing import Any

from .classrooms import ClassroomError, add_students, classroom_by_name, create_classroom
from .identity import load_users

STUDENT_PRESET = "student"
MAX_ROWS = 500
_PASSWORD_ALPHABET = string.ascii_letters + string.digits
_PASSWORD_LENGTH = 12
# Mirrors ``RegisterRequest.username_valid`` in api/routers/auth.py; the test
# suite checks both accept and refuse the same samples.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PLAIN_RE = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")
_MIN_PASSWORD = 8


@dataclass
class ImportRow:
    line: int
    username: str
    password: str
    classroom: str


@dataclass
class ImportReport:
    created: list[dict[str, str]] = field(default_factory=list)  # username, classroom, password
    skipped: list[dict[str, Any]] = field(default_factory=list)  # username, line, reason
    errors: list[dict[str, Any]] = field(default_factory=list)  # line, reason
    classrooms_created: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        """The report without the passwords -- for the audit line."""
        return {
            "created": len(self.created),
            "skipped": len(self.skipped),
            "errors": len(self.errors),
            "classrooms_created": len(self.classrooms_created),
        }

    def credentials_csv(self) -> str:
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["username", "password", "classroom"])
        for row in self.created:
            writer.writerow([row["username"], row["password"], row["classroom"]])
        return out.getvalue()


def generate_password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


def valid_username(value: str) -> bool:
    return bool(_EMAIL_RE.match(value) or _PLAIN_RE.match(value))


def parse_csv(text: str) -> tuple[list[ImportRow], list[dict[str, Any]]]:
    """Rows and the per-line errors of a CSV with a ``username,password,classroom`` header."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    if "username" not in headers or "classroom" not in headers:
        return [], [{"line": 1, "reason": "The header must name username and classroom columns."}]
    rows: list[ImportRow] = []
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in reader:
        index = reader.line_num  # the file's line, blank lines included
        if len(rows) + len(errors) >= MAX_ROWS:
            errors.append({"line": index, "reason": f"At most {MAX_ROWS} rows per file."})
            break
        cells = {str(k).strip().lower(): str(v or "").strip() for k, v in raw.items() if k}
        username = cells.get("username", "")
        password = cells.get("password", "")
        classroom = cells.get("classroom", "")
        if not username and not password and not classroom:
            continue  # a blank line
        if not valid_username(username):
            errors.append({"line": index, "reason": "Invalid username."})
            continue
        if password and len(password) < _MIN_PASSWORD:
            errors.append(
                {"line": index, "reason": f"A password is at least {_MIN_PASSWORD} characters."}
            )
            continue
        if not classroom:
            errors.append({"line": index, "reason": "The classroom is empty."})
            continue
        if username.lower() in seen:
            errors.append({"line": index, "reason": "This username appears twice in the file."})
            continue
        seen.add(username.lower())
        rows.append(
            ImportRow(line=index, username=username, password=password, classroom=classroom)
        )
    return rows, errors


def import_students(text: str, *, create_classrooms: bool = False) -> ImportReport:
    """Create the accounts and place them; never raises for one bad row."""
    from deeptutor.multi_user.audit import log_admin_action
    from deeptutor.services.auth import add_user

    rows, errors = parse_csv(text)
    report = ImportReport(errors=errors)
    existing = {name.lower(): record for name, record in load_users().items()}
    by_classroom: dict[str, list[str]] = {}
    for row in rows:
        classroom = classroom_by_name(row.classroom)
        if classroom is None:
            if not create_classrooms:
                report.errors.append(
                    {"line": row.line, "reason": f"Unknown classroom: {row.classroom}"}
                )
                continue
            try:
                classroom = create_classroom(row.classroom)
            except ClassroomError as exc:
                report.errors.append({"line": row.line, "reason": str(exc)})
                continue
            report.classrooms_created.append(classroom["name"])
        if row.username.lower() in existing:
            record = existing[row.username.lower()]
            reason = "in the bin" if record.get("deleted_at") else "already exists"
            report.skipped.append({"line": row.line, "username": row.username, "reason": reason})
            continue
        password = row.password or generate_password()
        add_user(row.username, password, preset=STUDENT_PRESET)
        created = load_users().get(row.username)
        if created is None:
            report.errors.append({"line": row.line, "reason": "The account was not created."})
            continue
        existing[row.username.lower()] = created
        user_id = str(created.get("id") or "")
        log_admin_action(
            "account_create",
            target_user_id=user_id or None,
            summary={
                "username": row.username,
                "role": "user",
                "preset": STUDENT_PRESET,
                "via": "import",
            },
        )
        by_classroom.setdefault(classroom["id"], []).append(user_id)
        report.created.append(
            {"username": row.username, "password": password, "classroom": classroom["name"]}
        )
    for classroom_id, student_ids in by_classroom.items():
        try:
            add_students(classroom_id, student_ids)
        except ClassroomError as exc:
            report.errors.append({"line": 0, "reason": f"Placing students failed: {exc}"})
    return report


__all__ = ["ImportReport", "ImportRow", "generate_password", "import_students", "parse_csv"]
