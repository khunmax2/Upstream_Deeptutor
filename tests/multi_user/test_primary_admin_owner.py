"""Exactly one account owns ``data/``, and only a handover moves it.

Fork, Phase 1 of docs/planning/admin-roles/DESIGN_primary_admin_and_account_lifecycle.md
(decided 2026-09-15). Before this, ``primary_admin.py`` treated the ``auth.json``
bootstrap account (``env-admin``) as an owner of ``data/`` on top of the account
it had recorded, so a deployment with both had two owners sharing one
workspace; and the election read ``users.json`` only, so the bootstrap account
-- the deployment's first admin -- could never be the recorded one.

Now: a usable bootstrap account (username and password hash) wins the
election while nothing is recorded; a recorded owner is never replaced by
itself; and the owner changes only through ``python -m
deeptutor.multi_user.primary_admin handover <account>``, which is audited.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.multi_user.paths import admin_scope, scope_for_user
from deeptutor.multi_user.primary_admin import (
    ENV_ADMIN_ID,
    is_primary_admin_account,
    main,
    primary_admin_id,
    reset_primary_admin_cache,
)


@pytest.fixture
def bootstrap(monkeypatch):
    """Make the ``auth.json`` bootstrap account usable, or leave it half-set."""
    from deeptutor.services import auth as auth_service
    from deeptutor.services.auth import hash_password

    def _set(username: str = "operator", *, with_password: bool = True) -> str:
        monkeypatch.setattr(auth_service, "AUTH_USERNAME", username)
        monkeypatch.setattr(
            auth_service,
            "AUTH_PASSWORD_HASH",
            hash_password("operator-password") if with_password else "",
        )
        monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
        reset_primary_admin_cache()
        return username

    return _set


def _owns_deployment_tree(user_id: str) -> bool:
    return scope_for_user(user_id, is_admin=True).root == admin_scope().root


def _marker(mu_isolated_root) -> dict:
    path = mu_isolated_root / "data" / "system" / "auth" / "primary_admin.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _audit_lines(mu_isolated_root) -> list[dict]:
    path = mu_isolated_root / "data" / "system" / "audit" / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_a_usable_bootstrap_admin_is_elected_while_nothing_is_recorded(
    mu_isolated_root, seed_user, bootstrap
):
    bootstrap()
    owner = seed_user("owner", role="admin")

    assert primary_admin_id() == ENV_ADMIN_ID
    assert _marker(mu_isolated_root) == {"user_id": ENV_ADMIN_ID}
    assert _owns_deployment_tree(ENV_ADMIN_ID)
    assert not _owns_deployment_tree(owner["id"])
    assert is_primary_admin_account(ENV_ADMIN_ID)
    assert not is_primary_admin_account(owner["id"])


def test_a_bootstrap_admin_without_a_password_is_not_elected(
    mu_isolated_root, seed_user, bootstrap
):
    bootstrap(with_password=False)
    owner = seed_user("owner", role="admin")

    assert primary_admin_id() == owner["id"]
    assert not _owns_deployment_tree(ENV_ADMIN_ID)


def test_a_recorded_owner_is_not_replaced_by_a_bootstrap_admin_that_appears_later(
    mu_isolated_root, seed_user, bootstrap
):
    owner = seed_user("owner", role="admin")
    assert primary_admin_id() == owner["id"]

    bootstrap()

    assert primary_admin_id() == owner["id"]
    assert _owns_deployment_tree(owner["id"])
    # The bootstrap account is an admin like any other now: its own workspace,
    # and the users page does not call it the primary admin.
    assert not _owns_deployment_tree(ENV_ADMIN_ID)
    assert not is_primary_admin_account(ENV_ADMIN_ID)


def test_handover_moves_the_deployment_tree_and_leaves_a_record(
    mu_isolated_root, seed_user, capsys
):
    owner = seed_user("owner", role="admin")
    seed_user("colleague")
    colleague = seed_user("colleague", role="admin")
    assert primary_admin_id() == owner["id"]

    assert main(["handover", "colleague"]) == 0

    assert primary_admin_id() == colleague["id"]
    assert _marker(mu_isolated_root) == {"user_id": colleague["id"]}
    assert _owns_deployment_tree(colleague["id"])
    assert not _owns_deployment_tree(owner["id"])
    record = [
        line for line in _audit_lines(mu_isolated_root) if line["action"] == "primary_handover"
    ]
    assert len(record) == 1
    assert record[0]["target_user_id"] == colleague["id"]
    assert record[0]["summary"] == {"from": owner["id"], "to": colleague["id"]}
    assert record[0]["actor_id"] == "operator"
    out = capsys.readouterr().out
    assert colleague["id"] in out and owner["id"] in out


def test_handover_reaches_the_bootstrap_admin_by_either_name(
    mu_isolated_root, seed_user, bootstrap
):
    owner = seed_user("owner", role="admin")
    assert primary_admin_id() == owner["id"]
    username = bootstrap()

    assert main(["handover", username]) == 0
    assert primary_admin_id() == ENV_ADMIN_ID

    assert main(["handover", "owner"]) == 0
    assert main(["handover", ENV_ADMIN_ID]) == 0
    assert primary_admin_id() == ENV_ADMIN_ID


def test_handover_refuses_anything_that_is_not_an_admin(
    mu_isolated_root, seed_user, bootstrap, capsys
):
    owner = seed_user("owner", role="admin")
    seed_user("student")
    assert primary_admin_id() == owner["id"]

    assert main(["handover", "student"]) != 0
    assert main(["handover", "nobody"]) != 0
    # The bootstrap account is not usable here: no password.
    bootstrap(with_password=False)
    assert main(["handover", ENV_ADMIN_ID]) != 0
    assert main(["handover", "operator"]) != 0

    assert primary_admin_id() == owner["id"]
    assert _marker(mu_isolated_root) == {"user_id": owner["id"]}
    assert not [
        line for line in _audit_lines(mu_isolated_root) if line["action"] == "primary_handover"
    ]
    assert "refused" in capsys.readouterr().err.lower()


def test_handover_to_the_current_owner_changes_nothing(mu_isolated_root, seed_user):
    owner = seed_user("owner", role="admin")
    assert primary_admin_id() == owner["id"]

    assert main(["handover", "owner"]) == 0

    assert primary_admin_id() == owner["id"]
    assert not [
        line for line in _audit_lines(mu_isolated_root) if line["action"] == "primary_handover"
    ]


def test_show_names_the_owner(mu_isolated_root, seed_user, capsys):
    owner = seed_user("owner", role="admin")

    assert main(["show"]) == 0

    out = capsys.readouterr().out
    assert owner["id"] in out and "owner" in out
