"""An admin promoted after the first one can open the knowledge bases it creates.

Fork. Upstream gives every admin the one deployment tree, so its knowledge-base
access layer resolves any admin's KB against ``data/knowledge_bases``. This fork
gives that tree to the primary admin alone (``primary_admin.py``). A promoted
admin's KBs are created in — and listed from — its own workspace, but every
per-KB route (files, upload, reindex, delete, and RAG in chat) resolved them in
the primary admin's tree: on the host and locally, "Knowledge base 'MyLaws' not
found" for a KB that had just been indexed.

Only the account that owns the deployment tree resolves against it now; a
promoted admin resolves and lists its own KBs, like any account with its own
workspace. Reaching the primary admin's KBs stays closed to it for now (an open
design question, recorded in CLAUDE.md).
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from deeptutor.multi_user.context import (
    reset_current_user,
    set_current_user,
    user_from_token_payload,
)
from deeptutor.services.path_service import PathService


class _Payload:
    def __init__(self, user_id: str, username: str, role: str) -> None:
        self.user_id = user_id
        self.username = username
        self.role = role


def _make_kb(root, name: str) -> None:
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    (root / name).mkdir(parents=True, exist_ok=True)
    KnowledgeBaseManager(base_dir=str(root)).register_knowledge_base(name)


@pytest.fixture
def world(mu_isolated_root, seed_user, monkeypatch):
    from deeptutor.multi_user.identity import set_role
    from deeptutor.multi_user.knowledge_access import _manager_for
    from deeptutor.multi_user.paths import (
        get_admin_path_service,
        get_path_service_for_scope,
        scope_for_user,
    )

    admin_tree = get_admin_path_service().workspace_root
    monkeypatch.setattr(PathService, "_instance", PathService(workspace_root=admin_tree))
    _manager_for.cache_clear()

    accounts = {"owner": ("admin", seed_user("owner", role="admin")["id"])}
    accounts["demo"] = ("admin", seed_user("demo")["id"])
    set_role("demo", "admin")
    accounts["student"] = ("user", seed_user("student")["id"])

    deployment_root = get_admin_path_service().get_knowledge_bases_root()
    demo_root = get_path_service_for_scope(
        scope_for_user(accounts["demo"][1], is_admin=True)
    ).get_knowledge_bases_root()
    student_root = get_path_service_for_scope(
        scope_for_user(accounts["student"][1], is_admin=False)
    ).get_knowledge_bases_root()
    _make_kb(deployment_root, "Deploy")
    _make_kb(demo_root, "MyLaws")
    _make_kb(student_root, "Notes")
    yield SimpleNamespace(
        accounts=accounts,
        deployment_root=deployment_root,
        demo_root=demo_root,
        student_root=student_root,
    )
    _manager_for.cache_clear()


@contextmanager
def acting_as(world, name: str):
    role, user_id = world.accounts[name]
    token = set_current_user(user_from_token_payload(_Payload(user_id, name, role)))
    try:
        yield
    finally:
        reset_current_user(token)


def test_a_promoted_admin_resolves_its_own_knowledge_base(world) -> None:
    from deeptutor.multi_user.knowledge_access import assert_writable, resolve_kb

    with acting_as(world, "demo"):
        read = resolve_kb("MyLaws")
        write = assert_writable("MyLaws")

    assert read.base_dir.resolve() == world.demo_root.resolve()
    assert read.id == "user:kb:MyLaws"
    assert write.base_dir.resolve() == world.demo_root.resolve()


def test_an_old_admin_prefixed_id_still_finds_the_promoted_admins_own_kb(world) -> None:
    from deeptutor.multi_user.knowledge_access import resolve_kb

    with acting_as(world, "demo"):
        resource = resolve_kb("admin:kb:MyLaws")

    assert resource.base_dir.resolve() == world.demo_root.resolve()


def test_a_promoted_admin_does_not_reach_the_primary_admins_kbs(world) -> None:
    from deeptutor.multi_user.knowledge_access import resolve_kb

    with acting_as(world, "demo"):
        with pytest.raises(HTTPException) as caught:
            resolve_kb("Deploy")

    assert caught.value.status_code == 404


def test_a_promoted_admin_lists_its_own_kbs_under_its_own_ids(world) -> None:
    from deeptutor.api.routers.knowledge import list_knowledge_bases
    from deeptutor.multi_user.knowledge_access import list_visible_knowledge_bases

    with acting_as(world, "demo"):
        visible = list_visible_knowledge_bases()
        listed = asyncio.run(list_knowledge_bases())

    assert [(item["id"], item["source"]) for item in visible] == [("user:kb:MyLaws", "user")]
    assert visible[0]["provenance_label"] == "Created by you"
    assert [(item.id, item.source) for item in listed] == [("user:kb:MyLaws", "user")]


def test_the_primary_admin_still_owns_the_deployment_kbs(world) -> None:
    from deeptutor.api.routers.knowledge import list_knowledge_bases
    from deeptutor.multi_user.knowledge_access import resolve_kb

    with acting_as(world, "owner"):
        resource = resolve_kb("Deploy")
        listed = asyncio.run(list_knowledge_bases())

    assert resource.base_dir.resolve() == world.deployment_root.resolve()
    assert resource.id == "admin:kb:Deploy"
    assert [(item.id, item.source) for item in listed] == [("admin:kb:Deploy", "admin")]


def test_an_ordinary_user_is_unchanged(world) -> None:
    from deeptutor.multi_user.knowledge_access import resolve_kb

    with acting_as(world, "student"):
        resource = resolve_kb("Notes")

    assert resource.base_dir.resolve() == world.student_root.resolve()
    assert resource.id == "user:kb:Notes"
