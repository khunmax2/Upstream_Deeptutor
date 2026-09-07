"""A promoted admin gets its own workspace, not the first admin's.

The reported symptom: create a second account, promote it to admin, and it can
see every chat session belonging to admin #1. HKUDS/DeepTutor#1230 reports the
same defect from the other side — an account promoted to admin loses its own
history behind the shared tree, and cannot be demoted back onto it.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user.context import user_from_token_payload
from deeptutor.multi_user.models import LOCAL_ADMIN_ID
from deeptutor.multi_user.paths import (
    ADMIN_WORKSPACE_ROOT,
    admin_scope,
    get_path_service_for_scope,
    scope_for_user,
)
from deeptutor.multi_user.primary_admin import primary_admin_id


class _Payload:
    def __init__(self, user_id: str, username: str, role: str) -> None:
        self.user_id = user_id
        self.username = username
        self.role = role


def _admins(seed_user):
    """The bootstrap admin, then one promoted afterwards."""
    first = seed_user("owner", role="admin")
    seed_user("colleague")
    second = seed_user("colleague", role="admin")
    return first, second


def test_a_second_admin_does_not_land_in_the_first_admins_workspace(mu_isolated_root, seed_user):
    first, second = _admins(seed_user)
    assert first["id"] != second["id"]

    first_scope = scope_for_user(first["id"], is_admin=True)
    second_scope = scope_for_user(second["id"], is_admin=True)

    assert first_scope.root == admin_scope().root
    assert second_scope.root != first_scope.root
    assert second_scope.user_id == second["id"]


def test_two_admins_do_not_share_one_chat_history_database(mu_isolated_root, seed_user):
    first, second = _admins(seed_user)

    first_db = get_path_service_for_scope(scope_for_user(first["id"], is_admin=True))
    second_db = get_path_service_for_scope(scope_for_user(second["id"], is_admin=True))

    assert first_db.get_chat_history_db() != second_db.get_chat_history_db()


def test_promotion_does_not_move_an_account_off_its_own_workspace(mu_isolated_root, seed_user):
    """The #1230 half: history follows the account across a role change."""
    seed_user("owner", role="admin")
    account = seed_user("learner-turned-admin")

    before = scope_for_user(account["id"], is_admin=False)
    after = scope_for_user(account["id"], is_admin=True)

    assert after.root == before.root


def test_the_primary_admin_is_the_earliest_created_admin(mu_isolated_root, seed_user):
    first, _second = _admins(seed_user)
    assert primary_admin_id() == first["id"]


def test_the_election_is_recorded_and_then_stuck(mu_isolated_root, seed_user):
    """A deleted or demoted primary must never hand ``data/`` to another admin."""
    from deeptutor.multi_user.identity import delete_user
    from deeptutor.multi_user.primary_admin import reset_primary_admin_cache

    first, second = _admins(seed_user)
    assert primary_admin_id() == first["id"]

    delete_user("owner")
    reset_primary_admin_cache()

    assert primary_admin_id() == first["id"]
    assert scope_for_user(second["id"], is_admin=True).root != ADMIN_WORKSPACE_ROOT.resolve()


@pytest.mark.parametrize("sentinel", [LOCAL_ADMIN_ID, "env-admin"])
def test_sentinel_admins_still_own_the_deployment_tree(mu_isolated_root, seed_user, sentinel):
    """AUTH_ENABLED=false and the env bootstrap admin are the deployment."""
    _admins(seed_user)
    assert scope_for_user(sentinel, is_admin=True).root == admin_scope().root


def test_a_token_for_a_second_admin_resolves_to_its_own_scope(mu_isolated_root, seed_user):
    _first, second = _admins(seed_user)

    user = user_from_token_payload(_Payload(second["id"], "colleague", "admin"))

    assert user.is_admin, "privileges come from the role, not from the workspace"
    assert user.scope.root != admin_scope().root
    assert user.scope.user_id == second["id"]
