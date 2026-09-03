"""The selector and the turn agree on which model an ordinary user gets.

`request_preparer` pins the first granted-and-available model when a turn
arrives with no selection. `allowed_llm_options()` used to tell the browser
there was no active model at all, so a learner with one assigned LLM saw an
empty "Select model" control even though every turn would have used that
model. Both now read one helper.
"""

from deeptutor.multi_user import model_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope

PROFILE = "llm-profile-shared"


def _user(tmp_path):
    return CurrentUser(
        id="u_kid",
        username="kid",
        role="user",
        scope=UserScope(kind="user", user_id="u_kid", root=tmp_path / "u_kid"),
    )


def _catalog() -> dict:
    return {
        "services": {
            "llm": {
                "profiles": [
                    {
                        "id": PROFILE,
                        "name": "Shared",
                        "models": [
                            {"id": "m-first", "name": "First", "model": "first-1"},
                            {"id": "m-second", "name": "Second", "model": "second-1"},
                        ],
                    }
                ]
            }
        }
    }


def _grant_both(_user_id=None) -> dict:
    return {"models": {"llm": [{"profile_id": PROFILE, "model_ids": ["m-first", "m-second"]}]}}


def _grant_none(_user_id=None) -> dict:
    return {"models": {"llm": []}}


def test_the_first_granted_model_is_the_active_default(tmp_path, monkeypatch):
    monkeypatch.setattr(model_access, "admin_catalog", _catalog)
    monkeypatch.setattr(model_access, "load_grant", _grant_both)
    token = set_current_user(_user(tmp_path))
    try:
        payload = model_access.allowed_llm_options()
        assert payload["active"] == {"profile_id": PROFILE, "model_id": "m-first"}
        flags = {o["model_id"]: o["is_active_default"] for o in payload["options"]}
        assert flags == {"m-first": True, "m-second": False}
        # The turn path pins the very same model.
        assert model_access.default_llm_selection_for_user("u_kid") == payload["active"]
    finally:
        reset_current_user(token)


def test_no_granted_model_means_no_active_default(tmp_path, monkeypatch):
    monkeypatch.setattr(model_access, "admin_catalog", _catalog)
    monkeypatch.setattr(model_access, "load_grant", _grant_none)
    token = set_current_user(_user(tmp_path))
    try:
        payload = model_access.allowed_llm_options()
        assert payload == {"active": None, "options": []}
        assert model_access.default_llm_selection_for_user("u_kid") is None
    finally:
        reset_current_user(token)
