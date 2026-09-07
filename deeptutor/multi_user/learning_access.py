"""Learning-account policy resolution and turn enforcement."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .context import get_current_user
from .grants import load_grant


def learning_policy_for_user(user_id: str, *, is_admin: bool = False) -> dict[str, Any] | None:
    """Return the sanitized public policy for an account."""
    if is_admin:
        return None
    loaded = load_grant(user_id)
    policy = loaded.get("learning_policy")
    if policy is None:
        from .identity import get_user_by_id

        user = get_user_by_id(user_id)
        if user is not None and str(user[1].get("preset") or "standard") == "learner":
            from .grants import learner_grant

            policy = learner_grant(user_id).get("learning_policy")
    return deepcopy(policy) if isinstance(policy, dict) else None


def current_learning_policy() -> dict[str, Any] | None:
    user = get_current_user()
    return learning_policy_for_user(user.id, is_admin=user.is_admin)


def apply_learning_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply account policy before a turn is validated or persisted."""
    policy = current_learning_policy()
    if policy is None:
        return payload

    capability = str(payload.get("capability") or "chat")
    allowed = set(policy.get("allowed_capabilities") or [])
    if capability not in allowed:
        raise PermissionError(
            "This learning account cannot use this mode. Please choose an allowed learning mode."
        )
    return {
        **payload,
        "persona": str(policy.get("locked_persona") or ""),
        # Learners never inherit a broad tool surface from a stale session or a
        # crafted payload. Reading's context tools are mounted server-side from
        # the open material and remain available to the reading capability.
        "tools": [],
        "enabled_tools": [],
        "knowledge_bases": [],
        "kb_name": "",
        "enable_rag": False,
        "enable_web_search": False,
        "partner_id": None,
        "bot_id": None,
    }


def assert_learning_surface(surface: str) -> None:
    """Deny a server surface not explicitly exposed to a learning account."""
    policy = current_learning_policy()
    if policy is None:
        return
    if surface not in set(policy.get("allowed_surfaces") or ["chat", "reading"]):
        target = f"{surface} surface" if surface else "requested server surface"
        raise PermissionError(f"This learning account cannot use the {target}.")


def accessible_material_ids() -> set[str] | None:
    """Reading material the current account may open.

    ``None`` means unrestricted. Otherwise the set is the guardian's allowlist
    (``reading.material_ids``) plus anything this account uploaded itself while
    ``allow_upload`` was granted — an upload the learner cannot then open is
    not an upload, which is what left "Allow learner uploads" inert.

    Self-uploads are unioned in only while the permission stands, so revoking
    it returns the account to exactly the guardian's list without deleting the
    learner's own files; re-granting it brings them back.
    """
    policy = current_learning_policy()
    if policy is None:
        return None
    reading = policy.get("reading")
    if not isinstance(reading, dict):
        return None
    assigned = set(reading.get("material_ids") or [])
    if "*" in assigned:
        return None
    if bool(reading.get("allow_upload")):
        from .learner_uploads import self_uploaded_ids

        assigned |= self_uploaded_ids()
    return assigned


def assert_learning_material(material_id: str, *, upload: bool = False) -> None:
    """Enforce upload and assigned-material policy in the authenticated scope."""
    policy = current_learning_policy()
    if policy is None:
        return
    has_reading = isinstance(policy.get("reading"), dict)
    reading = policy.get("reading") if has_reading else {}
    if upload:
        if has_reading and not bool(reading.get("allow_upload")):
            raise PermissionError("This learning account cannot upload reading materials.")
        return
    accessible = accessible_material_ids()
    if accessible is None:
        return
    if str(material_id or "") not in accessible:
        raise PermissionError("This reading material is not assigned to this learning account.")


def assert_learning_material_mutation(material_id: str) -> None:
    """Protect administrator-assigned material from learner-side deletion."""
    policy = current_learning_policy()
    if policy is None:
        return
    reading = policy.get("reading") if isinstance(policy.get("reading"), dict) else {}
    if not bool(reading.get("allow_upload")):
        raise PermissionError("This learning account cannot modify assigned reading materials.")
    # A learner deletes what a learner brought. Assigned material is the
    # guardian's, and ``allow_upload`` is permission to add, never permission to
    # remove someone else's assignment — which is what the docstring above has
    # always promised and the assigned-material check alone did not deliver.
    from .learner_uploads import self_uploaded_ids

    if str(material_id or "") not in self_uploaded_ids():
        raise PermissionError("This learning account cannot modify assigned reading materials.")
    assert_learning_material(material_id)


def allowed_reading_extensions() -> set[str] | None:
    """None means unrestricted; a set is the learner extension allowlist."""
    policy = current_learning_policy()
    if policy is None:
        return None
    if not isinstance(policy.get("reading"), dict):
        return {"read_aloud", "guided_learning", "vocabulary", "quiz", "translation"}
    return set(policy["reading"].get("extensions") or [])


__all__ = [
    "accessible_material_ids",
    "allowed_reading_extensions",
    "apply_learning_policy",
    "assert_learning_material",
    "assert_learning_material_mutation",
    "assert_learning_surface",
    "current_learning_policy",
    "learning_policy_for_user",
]
