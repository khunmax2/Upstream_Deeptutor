"""Fork: an account store that exists but cannot be read is an outage, not empty.

On 2026-09-19 ``data/system/auth/users.json`` was left root-owned 0600 by a
``docker exec`` run as root while the app ran as ``deeptutor``. ``_read_json``
swallowed the ``PermissionError`` and answered ``{}``, so the next writer
(``save_user``) wrote "empty plus one record" back through the atomic write --
a new file, replacing the one it never read. Four accounts were lost.

The rule now: readable or refuse. Every write path goes through
``load_users``, so ``load_users`` raising is enough to keep the file intact.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from deeptutor.multi_user import identity

_SEEDED = {
    "alice": {"id": "u_alice", "hash": "h1", "role": "admin", "created_at": "t"},
    "bob": {"id": "u_bob", "hash": "h2", "role": "user", "created_at": "t"},
}


def _seed_store() -> bytes:
    """Write the store and return its exact bytes, so "untouched" is byte-equal."""
    identity.USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(_SEEDED, indent=2).encode("utf-8")
    identity.USERS_FILE.write_bytes(raw)
    return raw


def _make_unreadable(monkeypatch) -> None:
    """Make ``USERS_FILE`` raise ``PermissionError`` on read, portably.

    ``chmod 000`` is ignored by a root runner and does nothing on Windows, so
    the read itself is patched: the file stays on disk, ``exists()`` is true,
    and only ``read_text`` refuses -- exactly the shape of the 0600 root-owned
    file on the host.
    """
    original = Path.read_text
    target = identity.USERS_FILE.resolve()

    def refusing(self: Path, *args, **kwargs):
        if self.resolve() == target:
            raise PermissionError(13, "Permission denied", str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refusing)


def test_save_user_refuses_when_store_is_unreadable(mu_isolated_root, monkeypatch, caplog):
    before = _seed_store()
    _make_unreadable(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="deeptutor.multi_user.identity"):
        with pytest.raises(identity.UsersStoreUnreadableError):
            identity.save_user("mallory", "h3")

    # The file was neither replaced nor touched.
    assert identity.USERS_FILE.exists()
    assert identity.USERS_FILE.read_bytes() == before  # bytes: read_text is still patched
    # The outage reached the log at a level ``docker logs`` shows.
    assert any(
        record.levelno >= logging.ERROR and "users.json" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "writer",
    [
        lambda: identity.delete_user("alice"),
        lambda: identity.set_role("bob", "admin"),
        lambda: identity.set_disabled("bob", True),
        lambda: identity.set_deleted("bob", True),
        lambda: identity.set_password("bob", "h9"),
        lambda: identity.set_avatar("bob", "x"),
        lambda: identity.set_preset("bob", "learner"),
    ],
)
def test_every_writer_refuses_when_store_is_unreadable(mu_isolated_root, monkeypatch, writer):
    before = _seed_store()
    _make_unreadable(monkeypatch)

    with pytest.raises(identity.UsersStoreUnreadableError):
        writer()

    assert identity.USERS_FILE.read_bytes() == before


def test_corrupt_store_is_refused_not_emptied(mu_isolated_root, caplog):
    identity.USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    identity.USERS_FILE.write_text('{"alice": {"hash": "h1"', encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="deeptutor.multi_user.identity"):
        with pytest.raises(identity.UsersStoreUnreadableError):
            identity.load_users()

    assert identity.USERS_FILE.read_text(encoding="utf-8") == '{"alice": {"hash": "h1"'
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_missing_store_is_still_empty_for_first_run(mu_isolated_root):
    assert not identity.USERS_FILE.exists()
    assert identity.load_users() == {}

    record = identity.save_user("first", "h1")

    assert record["role"] == "admin"
    assert set(identity.load_users()) == {"first"}


def test_readable_store_is_untouched_by_the_rule(mu_isolated_root):
    _seed_store()

    identity.save_user("carol", "h3")

    assert set(identity.load_users()) == {"alice", "bob", "carol"}


def test_turn_recovery_keeps_running_on_an_unreadable_store(mu_isolated_root, monkeypatch):
    """The background leader's recovery pass must not thrash on the outage."""
    from deeptutor.app.container import ApplicationContainer

    _seed_store()
    _make_unreadable(monkeypatch)

    users = ApplicationContainer._local_users()

    assert [user.id for user in users] == ["local-admin"]
