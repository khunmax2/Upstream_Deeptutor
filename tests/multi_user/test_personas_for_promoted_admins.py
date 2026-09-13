"""An admin promoted after the first one sees the system personas, read-only.

Fork. Upstream gives every admin the one deployment tree (``data/``), so its
code reads "not an admin" as "does not own the deployment's personas" and only
then merges them in. This fork gives ``data/`` to the primary admin alone and
every later admin a private workspace (``primary_admin.py``), so on the host a
promoted admin's persona list read 0: its own workspace had none, and the
system presets — seeded only into ``data/`` — were withheld because it is an
admin. Ordinary users saw them all along.

The presets now reach every account whose workspace is not the deployment
tree: listing, opening, the partner wizard, creating a partner from one, and
the chat turn itself. Anything the account writes still lands in its own
workspace, and its own persona of the same name shadows the preset.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

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


@pytest.fixture
def world(mu_isolated_root, seed_user, monkeypatch):
    from deeptutor.multi_user.identity import set_role
    from deeptutor.multi_user.paths import USERS_ROOT, get_admin_path_service
    from deeptutor.services.persona import PersonaService

    admin_tree = get_admin_path_service().workspace_root
    monkeypatch.setattr(PathService, "_instance", PathService(workspace_root=admin_tree))

    presets_root = get_admin_path_service().get_workspace_dir() / "personas"
    seeded = PersonaService(root=presets_root).seed_presets()
    assert seeded, "the bundled presets did not seed"

    accounts = {"owner": ("admin", seed_user("owner", role="admin")["id"])}
    accounts["demo"] = ("admin", seed_user("demo")["id"])
    set_role("demo", "admin")
    accounts["student"] = ("user", seed_user("student")["id"])
    return SimpleNamespace(
        accounts=accounts,
        preset=seeded[0],
        presets_root=presets_root,
        own_root=lambda name: USERS_ROOT / accounts[name][1] / "user" / "workspace" / "personas",
    )


@contextmanager
def acting_as(world, name: str):
    role, user_id = world.accounts[name]
    token = set_current_user(user_from_token_payload(_Payload(user_id, name, role)))
    try:
        yield
    finally:
        reset_current_user(token)


def listed(world, name: str) -> dict[str, dict]:
    from deeptutor.api.routers.personas import list_personas

    with acting_as(world, name):
        return {item["name"]: item for item in asyncio.run(list_personas())["personas"]}


def test_a_promoted_admin_sees_the_system_presets_read_only(world) -> None:
    personas = listed(world, "demo")

    assert world.preset in personas
    assert personas[world.preset]["read_only"] is True
    assert personas[world.preset]["source"] == "admin"


def test_a_promoted_admin_can_open_a_preset(world) -> None:
    from deeptutor.api.routers.personas import get_persona

    with acting_as(world, "demo"):
        detail = asyncio.run(get_persona(world.preset))

    assert detail["read_only"] is True
    assert detail["content"]


def test_the_partner_wizard_and_partner_creation_offer_the_presets(world) -> None:
    from deeptutor.api.routers.partners import _load_persona_markdown, soul_sources

    with acting_as(world, "demo"):
        sources = asyncio.run(soul_sources())
        markdown = _load_persona_markdown(world.preset)

    assert world.preset in {item["name"] for item in sources["personas"]}
    assert markdown.strip()


def test_a_chat_turn_falls_back_to_the_presets_for_the_same_accounts() -> None:
    source = Path("deeptutor/services/session/turns/executor.py").read_text(encoding="utf-8")
    persona_block = source[source.index("requested_persona = ") :]
    persona_block = persona_block[: persona_block.index("active_persona = ")]
    assert "reads_deployment_presets(current_user)" in persona_block
    assert "not current_user.is_admin" not in persona_block


def test_a_promoted_admins_own_persona_is_private_and_shadows_the_preset(world) -> None:
    from deeptutor.api.routers.personas import CreatePersonaRequest, create_persona

    preset_file = world.presets_root / world.preset / "PERSONA.md"
    preset_before = preset_file.read_bytes()

    with acting_as(world, "demo"):
        asyncio.run(
            create_persona(
                CreatePersonaRequest(name=world.preset, description="mine", content="My voice.")
            )
        )

    assert (world.own_root("demo") / world.preset / "PERSONA.md").exists()
    assert preset_file.read_bytes() == preset_before
    mine = listed(world, "demo")[world.preset]
    assert mine.get("read_only") is not True
    assert mine["description"] == "mine"


def test_the_primary_admin_lists_its_own_tree_once(world) -> None:
    personas = listed(world, "owner")

    assert world.preset in personas
    assert personas[world.preset].get("read_only") is not True


def test_an_ordinary_user_still_sees_the_presets(world) -> None:
    personas = listed(world, "student")

    assert personas[world.preset]["read_only"] is True
