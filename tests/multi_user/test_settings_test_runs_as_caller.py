"""Settings' Run test acts as the admin who pressed it.

Fork. On the host, an admin promoted after the first one ran Settings →
Embedding → Run test. The run's worker thread did not carry the caller's
identity, so when the probe succeeded and saved the detected dimension, the
catalog service fell back to the default tree — the primary admin's
``data/user/settings/model_catalog.json`` — and saved the tester's whole catalog
there. The page then showed the tested profile as saved with its key masked
(``***``); the next run restored that mask against the tester's own catalog,
which never had the profile, and sent ``Bearer ***`` ("Missing Authentication
header"). Found 2026-09-14 when a probe of this very path overwrote a developer
catalog the same way.

These tests drive the real routes with one primary admin and two admins
promoted after it. The default PathService is pinned to the primary admin's
tree, as in production — so a write that loses track of the caller lands where
it did on the host (and never in a developer's real ``data/``).
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

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


def _embedding(tag: str, key: str, *, base_url: str = "https://openrouter.ai/api/v1/embeddings"):
    return {
        "version": 1,
        "services": {
            "embedding": {
                "active_profile_id": f"{tag}-emb",
                "active_model_id": f"{tag}-emb-m",
                "profiles": [
                    {
                        "id": f"{tag}-emb",
                        "name": f"OpenRouter {tag}",
                        "binding": "openrouter",
                        "base_url": base_url,
                        "api_key": key,
                        "models": [
                            {
                                "id": f"{tag}-emb-m",
                                "name": "bge-m3",
                                "model": "baai/bge-m3",
                                "dimension": "",
                            }
                        ],
                    }
                ],
            }
        },
    }


@pytest.fixture
def world(mu_isolated_root, seed_user, monkeypatch):
    from deeptutor.multi_user.identity import set_role
    from deeptutor.multi_user.paths import USERS_ROOT, get_admin_path_service
    from deeptutor.services.config.model_catalog import ModelCatalogService

    admin_tree = get_admin_path_service().workspace_root
    monkeypatch.setattr(PathService, "_instance", PathService(workspace_root=admin_tree))

    sent: list[str] = []

    class FakeClient:
        def __init__(self, config) -> None:  # noqa: ANN001
            sent.append(config.api_key)
            self.adapter = MagicMock(MODELS_INFO={})

        async def embed(self, texts):  # noqa: ANN001
            return [[0.1] * 1024 for _ in texts]

    monkeypatch.setattr("deeptutor.services.embedding.client.EmbeddingClient", FakeClient)
    monkeypatch.setattr("deeptutor.services.embedding.client.reset_embedding_client", lambda: None)

    ids = {"owner": seed_user("owner", role="admin")["id"]}
    for name in ("demo1", "demo2"):
        ids[name] = seed_user(name)["id"]
        set_role(name, "admin")
    primary = get_admin_path_service().get_settings_file("model_catalog")
    ModelCatalogService(path=primary).save(_embedding("PRIMARY", "sk-primary"))
    files = {"owner": primary}
    for name in ("demo1", "demo2"):
        files[name] = USERS_ROOT / ids[name] / "user" / "settings" / "model_catalog.json"
    return SimpleNamespace(ids=ids, files=files, sent=sent)


@contextmanager
def acting_as(world, name: str):
    token = set_current_user(user_from_token_payload(_Payload(world.ids[name], name, "admin")))
    try:
        yield
    finally:
        reset_current_user(token)


def save_own(world, name: str, catalog: dict) -> None:
    from deeptutor.services.config.model_catalog import get_model_catalog_service

    with acting_as(world, name):
        get_model_catalog_service().save(catalog)


def saved_view(world, name: str) -> dict:
    """What the page holds after loading: the account's own catalog, keys masked."""
    from deeptutor.services.config.model_catalog import (
        get_model_catalog_service,
        redact_catalog_secrets,
    )

    with acting_as(world, name):
        return redact_catalog_secrets(get_model_catalog_service().load())


def run_test(world, name: str, page_catalog: dict):
    from deeptutor.api.routers.settings import CatalogPayload, start_service_test
    from deeptutor.services.config import get_config_test_runner

    with acting_as(world, name):
        started = asyncio.run(start_service_test("embedding", CatalogPayload(catalog=page_catalog)))
    run = get_config_test_runner().get(started["run_id"])
    for _ in range(250):
        if run.status != "running":
            return run
        time.sleep(0.02)
    raise AssertionError("the test run never finished")


def embedding_models(path) -> dict[str, dict]:
    if not path.exists():
        return {}
    catalog = json.loads(path.read_text(encoding="utf-8"))
    return {
        model["id"]: {
            **model,
            "api_key": profile.get("api_key"),
            "base_url": profile.get("base_url"),
        }
        for profile in catalog.get("services", {}).get("embedding", {}).get("profiles", [])
        for model in profile.get("models", [])
    }


def test_a_promoted_admins_test_never_writes_the_primary_catalog(world) -> None:
    primary_before = world.files["owner"].read_bytes()
    save_own(world, "demo1", _embedding("D1", "sk-demo1"))

    run = run_test(world, "demo1", saved_view(world, "demo1"))

    assert run.status == "completed", [e["message"] for e in run.events]
    assert world.sent[-1] == "sk-demo1"
    assert world.files["owner"].read_bytes() == primary_before
    assert embedding_models(world.files["demo1"])["D1-emb-m"]["dimension"] == "1024"


def test_each_promoted_admin_keeps_to_its_own_catalog(world) -> None:
    primary_before = world.files["owner"].read_bytes()
    save_own(world, "demo1", _embedding("D1", "sk-demo1"))
    save_own(world, "demo2", _embedding("D2", "sk-demo2"))

    run_test(world, "demo1", saved_view(world, "demo1"))
    run_test(world, "demo2", saved_view(world, "demo2"))

    assert world.sent[-2:] == ["sk-demo1", "sk-demo2"]
    assert set(embedding_models(world.files["demo1"])) == {"D1-emb-m"}
    assert set(embedding_models(world.files["demo2"])) == {"D2-emb-m"}
    assert world.files["owner"].read_bytes() == primary_before


def test_testing_a_profile_before_saving_it_writes_nothing(world) -> None:
    primary_before = world.files["owner"].read_bytes()
    save_own(world, "demo1", {"version": 1, "services": {}})

    run = run_test(world, "demo1", _embedding("NEW", "sk-typed-in-the-form"))

    assert run.status == "completed", [e["message"] for e in run.events]
    assert world.sent[-1] == "sk-typed-in-the-form"
    assert "NEW-emb-m" not in embedding_models(world.files["demo1"])
    assert world.files["owner"].read_bytes() == primary_before
    dimension = [e for e in run.events if e["type"] == "dimension"]
    assert dimension and dimension[-1]["persisted"] is False
    assert dimension[-1]["dimension"] == 1024


def test_the_dimension_is_not_written_over_a_profile_edited_on_the_page(world) -> None:
    save_own(world, "demo1", _embedding("D1", "sk-demo1"))
    page = saved_view(world, "demo1")
    page["services"]["embedding"]["profiles"][0]["base_url"] = "https://example.test/v1/embeddings"

    run = run_test(world, "demo1", page)

    assert run.status == "completed", [e["message"] for e in run.events]
    saved = embedding_models(world.files["demo1"])["D1-emb-m"]
    assert saved["dimension"] == ""
    assert saved["base_url"] == "https://openrouter.ai/api/v1/embeddings"


def test_a_masked_key_that_is_not_saved_fails_clearly_and_sends_nothing(world) -> None:
    save_own(world, "demo1", {"version": 1, "services": {}})

    run = run_test(world, "demo1", _embedding("NEW", "***"))

    assert run.status == "failed"
    assert "enter it again" in run.events[-1]["message"]
    assert world.sent == []


def test_saving_a_key_that_is_only_the_mask_is_refused(world) -> None:
    from deeptutor.api.routers.settings import (
        CatalogPayload,
        CatalogServicePayload,
        apply_catalog_service,
        update_catalog,
    )

    save_own(world, "demo1", {"version": 1, "services": {}})
    before = world.files["demo1"].read_bytes()
    masked = _embedding("NEW", "***")

    with acting_as(world, "demo1"):
        with pytest.raises(HTTPException) as whole:
            asyncio.run(update_catalog(CatalogPayload(catalog=masked)))
        with pytest.raises(HTTPException) as one:
            asyncio.run(
                apply_catalog_service(
                    CatalogServicePayload(
                        service="embedding", config=masked["services"]["embedding"]
                    )
                )
            )

    assert whole.value.status_code == one.value.status_code == 400
    assert "enter it again" in str(whole.value.detail)
    assert world.files["demo1"].read_bytes() == before


def test_the_primary_admin_still_saves_its_own_dimension(world) -> None:
    demo_before = world.files["demo1"].read_bytes() if world.files["demo1"].exists() else b""

    run = run_test(world, "owner", saved_view(world, "owner"))

    assert run.status == "completed", [e["message"] for e in run.events]
    assert world.sent[-1] == "sk-primary"
    assert embedding_models(world.files["owner"])["PRIMARY-emb-m"]["dimension"] == "1024"
    after = world.files["demo1"].read_bytes() if world.files["demo1"].exists() else b""
    assert after == demo_before
