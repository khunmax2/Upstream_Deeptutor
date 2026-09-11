"""The role a session carries is the store's current answer, not the token's.

``TokenPayload.role`` is what ``require_admin``, ``/api/auth/status`` (read by
the sidebar and the course-studio gatekeeper) and the learning-policy admin
exemption all trust. Read from the JWT alone, a promotion waited for the next
login and a demotion left a former admin holding admin for up to
TOKEN_EXPIRE_HOURS. These pin the store as the authority.
"""

from __future__ import annotations

import pytest

from deeptutor.services import auth as auth_service


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "test-secret-for-role-tests")
    monkeypatch.setattr(auth_service, "POCKETBASE_ENABLED", False)


def test_promotion_is_visible_on_the_next_decode(mu_isolated_root, secret):
    # The first account in an empty store is made admin whatever was asked;
    # alice has to be the second.
    auth_service.add_user("root", "pw-root", role="admin")
    auth_service.add_user("alice", "pw-alice", role="user")
    token = auth_service.create_token("alice", role="user")
    assert auth_service.decode_token(token).role == "user"

    assert auth_service.set_role("alice", "admin")
    assert auth_service.decode_token(token).role == "admin"


def test_demotion_does_not_wait_for_the_token_to_expire(mu_isolated_root, secret):
    auth_service.add_user("boss", "pw-boss", role="admin")
    token = auth_service.create_token("boss", role="admin")
    assert auth_service.decode_token(token).role == "admin"

    assert auth_service.set_role("boss", "user")
    # The token still says admin; the answer must not.
    assert auth_service.decode_token(token).role == "user"


def test_a_user_the_store_does_not_know_keeps_the_token_role(mu_isolated_root, secret):
    # Tests across the suite mint tokens for users that were never stored, and
    # the single-user bootstrap account arrives through auth.json rather than
    # the identity store. Neither may start failing because of this change.
    token = auth_service.create_token("ghost", role="admin", user_id="u-ghost")
    assert auth_service.decode_token(token).role == "admin"
