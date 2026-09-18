"""Auth router — login, logout, status, registration, profile, and user-management endpoints."""

from contextvars import Token as _CtxToken
from datetime import datetime, timedelta, timezone
import logging
import re

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator

from deeptutor.services.config import load_auth_settings

# SameSite comes from settings and defaults to Lax.
#
# It used to be derived: "none" whenever the cookie was Secure. The comment above
# that line justified None by a *development* case — a frontend reached at
# 127.0.0.1 while the backend answers at localhost, which are different origins —
# but that case runs without HTTPS, so it took the other branch and got Lax
# anyway. Production, behind one reverse proxy, is where None was actually
# applied, and there the case does not arise: None attaches the session cookie
# to every cross-site request to this origin, which is the CSRF surface Lax
# exists to remove.
#
# The framed course studio does not need None either. It is served from this
# origin, and the image it runs from bakes `frame-ancestors 'self'` — measured
# inside the built image, not assumed.
#
# A genuinely cross-site frontend is still a real shape, so `cookie_samesite`
# remains settable; the loader refuses "none" without Secure, because browsers
# drop that cookie and a dropped session cookie looks like a login that does not
# stick.
_AUTH_SETTINGS = load_auth_settings()
_SECURE = bool(_AUTH_SETTINGS["cookie_secure"])
_SAMESITE = str(_AUTH_SETTINGS.get("cookie_samesite") or "lax")

from deeptutor.multi_user.audit import log_admin_action, log_usage
from deeptutor.multi_user.context import set_current_user, user_from_token_payload
from deeptutor.multi_user.device_credentials import (
    heartbeat_device_credential,
    issue_device_credential,
    list_device_credentials,
    revoke_device_credential,
)
from deeptutor.multi_user.identity import get_user_by_id
from deeptutor.multi_user.learning_access import learning_policy_for_user
from deeptutor.multi_user.models import AccountPreset
from deeptutor.multi_user.paths import local_admin_user
from deeptutor.services.auth import (
    AUTH_ENABLED,
    POCKETBASE_ENABLED,
    TOKEN_EXPIRE_HOURS,
    TokenPayload,
    account_deleted,
    account_disabled,
    add_user,
    authenticate,
    authenticate_device,
    authenticate_pb,
    create_token,
    decode_token,
    delete_user,
    get_user_info,
    is_first_user,
    list_users,
    register_pb,
    set_avatar,
    set_learner_profile,
    set_role,
)
from deeptutor.services.auth import (
    get_learner_profile as load_learner_profile,
)
from deeptutor.services.codex_auth.contracts import CodexAuthError
from deeptutor.services.codex_auth.service import deliver_codex_oauth_callback

logger = logging.getLogger(__name__)

router = APIRouter()

_COOKIE_NAME = "dt_token"
_COOKIE_MAX_AGE = TOKEN_EXPIRE_HOURS * 3600


def _cookie_attrs() -> dict:
    """Attribute set shared by ``login``'s ``set_cookie`` and ``logout``'s
    ``delete_cookie``.

    The deletion ``Set-Cookie`` must carry the same attributes as the one
    that created the cookie — ``delete_cookie`` defaults ``secure=False``,
    which browsers reject when paired with ``SameSite=None``, silently
    keeping the old cookie. See #623. Reads the module globals at call time
    so tests can monkeypatch ``_SECURE``/``_SAMESITE``.
    """
    return {
        "key": _COOKIE_NAME,
        "httponly": True,
        "samesite": _SAMESITE,
        "secure": _SECURE,
    }


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Payload for the POST /login endpoint."""

    username: str
    password: str


class DeviceLoginRequest(BaseModel):
    """Payload for the built-in device-credential login endpoint."""

    pairing_code: str = Field(min_length=8, max_length=128)
    pin: str = Field(min_length=6, max_length=6)


class DeviceCredentialCreateRequest(BaseModel):
    """Admin payload for issuing a local ordinary-user device credential."""

    user_id: str = Field(min_length=1, max_length=64)
    device_name: str = Field(min_length=1, max_length=80)
    expires_in_days: int = Field(ge=1, le=365)
    daily_limit_minutes: int = Field(ge=5, le=1440)


class RegisterRequest(BaseModel):
    """Payload for the POST /register endpoint."""

    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        import re

        v = v.strip()
        if not v:
            raise ValueError("Email cannot be empty")
        # Accept standard email addresses (used by PocketBase mode) or plain
        # usernames (used by the built-in SQLite/JSON auth mode).
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        plain_re = re.compile(r"^[A-Za-z0-9_\-.]{3,64}$")
        if not email_re.match(v) and not plain_re.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class SetRoleRequest(BaseModel):
    """Payload for the PUT /users/{username}/role endpoint."""

    role: str

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ("admin", "user"):
            raise ValueError("Role must be 'admin' or 'user'")
        return v


class SetDisabledRequest(BaseModel):
    """Fork: payload for PUT /users/{username}/disabled."""

    disabled: bool


class AdminCreateUserRequest(RegisterRequest):
    """Admin user-creation payload.

    A preset configures an ordinary account; it never becomes a third role.
    """

    preset: AccountPreset = "standard"


class AuthStatusResponse(BaseModel):
    """Response body for the GET /status endpoint."""

    enabled: bool
    authenticated: bool
    user_id: str | None = None
    username: str | None = None
    role: str | None = None
    is_admin: bool = False
    # The deployment's primary administrator (primary_admin.py). The Course
    # Studio gatekeeper turns this into the `x-deeptutor-primary` header, the
    # only way the studio tells the primary admin from a promoted one.
    is_primary: bool = False
    avatar: str = ""
    preset: AccountPreset | None = None
    learning_policy: dict | None = None


class UserInfo(BaseModel):
    """Single user record returned by the GET /users and /profile endpoints."""

    id: str = ""
    username: str
    role: str
    created_at: str
    disabled: bool = False
    avatar: str = ""
    preset: AccountPreset = "standard"
    # Fork: the primary administrator, whom no other admin may demote or delete.
    is_primary: bool = False
    # Fork: set while the account is in the bin (deleted, restorable, name taken).
    deleted_at: str | None = None


class LearnerProfileRequest(BaseModel):
    age: int | None = Field(default=None, ge=3, le=120)
    grade_level: str | None = Field(default=None, max_length=80)
    curriculum: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=80)
    reading_level: str | None = Field(default=None, max_length=80)
    explanation_style: str | None = Field(default=None, max_length=80)


# Markers settable through PUT /profile. Image markers ("img:<version>") are
# managed exclusively by the upload endpoint so users cannot point their
# avatar at a file that was never validated.
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")

# User ids are generated as "u_<uuid hex>" (plus the "local-admin" /
# "env-admin" sentinels); reject anything else before it reaches the
# filesystem layer.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UpdateProfileRequest(BaseModel):
    """Payload for the PUT /profile endpoint."""

    avatar: str

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, v: str) -> str:
        v = v.strip()
        if v and not _ICON_MARKER_RE.match(v):
            raise ValueError("Avatar must be empty or 'icon:<name>:<color>'")
        return v


# ---------------------------------------------------------------------------
# Shared helper — extract token from cookie or Bearer header
# ---------------------------------------------------------------------------


def _bearer_token_from_header(authorization: str | None) -> str | None:
    """Parse ``Authorization: Bearer <token>`` without using ``HTTPBearer``.

    ``HTTPBearer`` is a class-based dependency whose ``__call__`` is annotated
    ``request: Request``. FastAPI doesn't inject a Request into WebSocket
    dependency resolution, which makes ``HTTPBearer`` raise ``TypeError`` the
    moment a router with this dep mounts a WS endpoint. Doing the parse by
    hand keeps ``require_auth`` HTTP/WS-symmetric.
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1].strip()
        return token or None
    return None


def _extract_token(authorization: str | None, dt_token: str | None) -> str | None:
    return _bearer_token_from_header(authorization) or dt_token


# ---------------------------------------------------------------------------
# Dependencies — reusable auth guards for other routers
# ---------------------------------------------------------------------------


def _install_current_user(payload: TokenPayload | None) -> _CtxToken:
    """Install the request-local current-user ContextVar from an auth result.

    Single point of truth for ``payload → CurrentUser`` so HTTP and WebSocket
    entry points produce identical user objects. ``payload is None`` means
    "no JWT was required" (AUTH_ENABLED=false) and resolves to the local
    admin user; a non-None payload resolves through ``user_from_token_payload``.

    Returns the ContextVar reset token. HTTP callers ignore it (the request
    ends with the task, so the var is GC'd with the task context). WebSocket
    callers keep it and call ``reset_current_user`` in their ``finally`` block,
    because a WS connection outlives the dependency-resolution task.

    ⚠ Invariant: every authenticated entry point MUST call this before the
    handler runs. Skipping it leaves ``get_current_path_service()`` falling
    back to the admin workspace — the silent-routing root cause of #481.
    """
    user = local_admin_user() if payload is None else user_from_token_payload(payload)
    return set_current_user(user)


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> TokenPayload | None:
    """
    FastAPI dependency that enforces authentication when AUTH_ENABLED=true.

    Accepts the JWT from either:
      - Authorization: Bearer <token> header
      - dt_token cookie

    ``Header`` and ``Cookie`` are kept here in place of ``HTTPBearer`` so the
    function stays usable from WebSocket call sites that don't go through
    FastAPI's standard HTTP request lifecycle.

    Returns the authenticated TokenPayload, or None if auth is disabled.
    Raises HTTP 401 if auth is enabled but the token is missing or invalid.

    Declared ``async def`` so the ``set_current_user`` call runs in the same
    asyncio context as the endpoint. A sync dependency is dispatched via
    ``anyio.to_thread.run_sync``, which executes the function in a worker
    thread under a *copy* of the request context; any ``ContextVar.set``
    inside that thread is discarded when the thread returns, leaving the
    endpoint to read the unset default. That regression was the root cause
    of #481.
    """
    if not AUTH_ENABLED:
        _install_current_user(None)
        return None

    token = _extract_token(authorization, dt_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _install_current_user(payload)
    return payload


class _WsAuthFailed:
    """Sentinel: ws_require_auth failed and closed the WebSocket."""


ws_auth_failed: _WsAuthFailed = _WsAuthFailed()


async def ws_require_auth(ws: WebSocket) -> _CtxToken | _WsAuthFailed:
    """Authenticate a WebSocket connection and set the user ContextVar.

    Must be called **before** ``ws.accept()`` so the server can reject
    unauthenticated upgrades cleanly.

    Returns a ContextVar reset token on success, or ``ws_auth_failed``
    on failure (the WebSocket is already closed — the caller should
    ``return`` immediately).

    Usage::

        user_token = await ws_require_auth(ws)
        if user_token is ws_auth_failed:
            return
        await ws.accept()
        try:
            ...
        finally:
            reset_current_user(user_token)
    """
    if not AUTH_ENABLED:
        return _install_current_user(None)

    token = ws.query_params.get("token") or ws.cookies.get(_COOKIE_NAME)
    payload = decode_token(token) if token else None
    if not payload:
        await ws.close(code=4001)
        return ws_auth_failed

    return _install_current_user(payload)


async def require_admin(
    payload: TokenPayload | None = Depends(require_auth),
) -> TokenPayload:
    """
    FastAPI dependency that requires the caller to be an admin.

    Raises HTTP 403 if the authenticated user is not an admin.
    When AUTH_ENABLED=false, all requests are treated as admin.

    ``async def`` mirrors ``require_auth`` so the dependency chain stays on
    the event loop and the user ContextVar set by ``require_auth`` is visible
    to the endpoint.
    """
    if not AUTH_ENABLED:
        return _local_admin_token_payload()

    if payload is None or payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return payload


def _learning_surface_for_path(path: str) -> str:
    normalized = "/" + str(path or "").lstrip("/")
    for root, surface in (
        ("/api/reading", "reading"),
        ("/api/courses", "reading"),
        ("/api/chat", "chat"),
        ("/api/question", "chat"),
        ("/api/question-notebook", "chat"),
        ("/api/sessions", "chat"),
        # Choosing which model answers a chat turn is part of the chat surface.
        # Without this the settings router's guard denied it, so an account with
        # a learning policy could never see a model — including the `learner`
        # preset, which always carries a policy and cannot have it removed. An
        # admin could assign an LLM to a learner and the learner would not see
        # it, which left that preset unable to hold a conversation at all.
        #
        # Safe by construction, and by upstream's own design: `get_llm_options`
        # already returns `allowed_llm_options()` — grant-filtered — to every
        # non-admin, and `GET /api/settings` carries a non-admin branch whose
        # comment says model choices come from exactly this route. That code was
        # unreachable for learning accounts; the guard was broader than the
        # handlers it fronts.
        #
        # Deliberately the full path, never the "/api/settings" prefix: the loop
        # matches on prefix, so a shorter entry would open every settings write
        # on the same router.
        ("/api/settings/llm-options", "chat"),
    ):
        if normalized == root or normalized.startswith(f"{root}/"):
            return surface
    return ""


async def require_learning_surface(
    request: Request,
    _: TokenPayload | None = Depends(require_auth),
) -> None:
    """Second-stage default-deny guard for configured learning accounts."""
    from deeptutor.multi_user.learning_access import assert_learning_surface

    try:
        assert_learning_surface(_learning_surface_for_path(request.url.path))
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _local_admin_token_payload() -> TokenPayload:
    """Synthetic admin payload used when AUTH_ENABLED=false.

    Mirrors the local admin identity (LOCAL_ADMIN_USERNAME / LOCAL_ADMIN_ID)
    so audit logs and self-reference checks behave the same as in multi-user
    mode. Values are kept aligned with ``local_admin_user()`` in
    ``deeptutor/multi_user/paths.py``.
    """
    from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME

    return TokenPayload(
        username=LOCAL_ADMIN_USERNAME,
        role="admin",
        user_id=LOCAL_ADMIN_ID,
    )


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------


@router.get("/openai-codex/callback")
async def receive_codex_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    headers = {"Cache-Control": "no-store"}
    try:
        callback_state = state if len(request.query_params.getlist("state")) == 1 else None
        await deliver_codex_oauth_callback(code, callback_state, error)
    except CodexAuthError as exc:
        return HTMLResponse(
            (
                "<!doctype html><title>DeepWitya Codex</title>"
                "<p>Authentication could not be received. Return to DeepWitya and try again.</p>"
            ),
            status_code=exc.http_status,
            headers=headers,
        )
    return HTMLResponse(
        (
            "<!doctype html><title>DeepWitya Codex</title>"
            "<p>Authentication received. You can return to DeepWitya.</p>"
        ),
        headers=headers,
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    authorization: str | None = Header(default=None, alias="Authorization"),
    dt_token: str | None = Cookie(default=None, alias=_COOKIE_NAME),
) -> AuthStatusResponse:
    """Return whether auth is enabled and whether the current request is authenticated."""
    if not AUTH_ENABLED:
        return AuthStatusResponse(
            enabled=False,
            authenticated=True,
            user_id="local-admin",
            username="local",
            role="admin",
            is_admin=True,
            is_primary=True,
            preset="standard",
        )

    token = _extract_token(authorization, dt_token)
    payload = decode_token(token) if token else None
    avatar = ""
    preset: AccountPreset | None = None
    learning_policy = None
    if payload is not None:
        info = get_user_info(payload.username)
        if info:
            avatar = str(info.get("avatar") or "")
            raw_preset = str(info.get("preset") or "standard")
            if raw_preset == "learner":
                preset = "learner"
            elif raw_preset == "custom":
                preset = "custom"
            else:
                preset = "standard"
        learning_policy = learning_policy_for_user(
            payload.user_id,
            is_admin=payload.role == "admin",
        )
    from deeptutor.multi_user.primary_admin import is_primary_admin_account

    return AuthStatusResponse(
        enabled=True,
        authenticated=payload is not None,
        user_id=payload.user_id if payload else None,
        username=payload.username if payload else None,
        role=payload.role if payload else None,
        is_admin=payload.role == "admin" if payload else False,
        is_primary=(
            payload.role == "admin" and is_primary_admin_account(payload.user_id)
            if payload
            else False
        ),
        avatar=avatar,
        preset=preset,
        learning_policy=learning_policy,
    )


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Validate credentials and set a JWT cookie."""
    if not AUTH_ENABLED:
        return {"ok": True, "message": "Auth is disabled — no login required."}

    if POCKETBASE_ENABLED:
        # PocketBase mode: email = username field for backwards-compat with the
        # existing LoginRequest schema; users can pass their email as "username".
        pb_result = authenticate_pb(body.username, body.password)
        if not pb_result:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        payload, pb_token = pb_result
        response.set_cookie(value=pb_token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
        logger.info(f"User '{payload.username}' logged in via PocketBase (role={payload.role!r})")
        return {
            "ok": True,
            "user_id": payload.user_id,
            "username": payload.username,
            "role": payload.role,
            "is_admin": payload.role == "admin",
        }

    # Standard JWT + bcrypt mode
    result = authenticate(body.username, body.password)
    if not result:
        # Fork: a shut account is told so, instead of guessing at its password.
        if account_disabled(body.username):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "This account has been deleted"
                    if account_deleted(body.username)
                    else "This account is disabled"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    token = create_token(result.username, result.role, result.user_id)
    response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())

    logger.info(f"User '{result.username}' logged in (role={result.role!r})")
    return {
        "ok": True,
        "user_id": result.user_id,
        "username": result.username,
        "role": result.role,
        "is_admin": result.role == "admin",
    }


def _require_builtin_device_auth() -> None:
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device credentials require built-in authentication.",
        )
    if POCKETBASE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device credentials are not supported in PocketBase mode.",
        )


@router.post("/device-login")
async def device_login(body: DeviceLoginRequest, response: Response) -> dict:
    """Exchange a device pairing code and PIN for the account's normal cookie."""

    _require_builtin_device_auth()
    payload = authenticate_device(body.pairing_code, body.pin)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect device credentials",
        )
    if account_disabled(payload.username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This account has been deleted"
                if account_deleted(payload.username)
                else "This account is disabled"
            ),
        )

    token = create_token(
        payload.username,
        payload.role,
        payload.user_id,
        device_credential_id=payload.device_credential_id,
        device_session_nonce=payload.device_session_nonce,
    )
    response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
    logger.info(f"User '{payload.username}' logged in with a device credential")
    return {
        "ok": True,
        "user_id": payload.user_id,
        "username": payload.username,
        "role": payload.role,
        "is_admin": payload.role == "admin",
        "device_credential_id": payload.device_credential_id,
    }


@router.post("/device/heartbeat")
async def device_heartbeat(
    response: Response,
    payload: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Refresh a device lease and account bounded daily usage."""

    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device credentials require built-in authentication.",
        )
    if payload is None or not payload.device_credential_id or not payload.device_session_nonce:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This session does not use a device credential.",
        )
    try:
        device = heartbeat_device_credential(
            payload.device_credential_id,
            user_id=payload.user_id,
            session_nonce=payload.device_session_nonce,
        )
    except ValueError:
        response.delete_cookie(**_cookie_attrs())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device session is no longer active",
        ) from None
    return {"ok": not device.pop("limit_reached"), **device}


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the JWT cookie.

    Deletion attributes mirror ``login`` structurally via ``_cookie_attrs()``
    (see the rationale there and #623).
    """
    response.delete_cookie(**_cookie_attrs())
    return {"ok": True}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> dict:
    """
    Bootstrap-only registration.

    Public endpoint that creates the *first* admin account when the user store
    is empty. Once an admin exists, this endpoint is closed; further accounts
    must be created by an admin via ``POST /api/auth/users``.

    Only available when AUTH_ENABLED=true.
    """
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth is disabled — registration is not available.",
        )

    if POCKETBASE_ENABLED:
        # PocketBase deployments are documented as single-user. Keep registration
        # closed and require admins to provision users in the PocketBase admin UI.
        if not is_first_user():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Self-registration is closed. Ask an administrator to create your account.",
            )
        result = register_pb(username=body.username, email=body.username, password=body.password)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registration failed — username or email may already be taken.",
            )
        logger.info(f"First user registered via PocketBase: '{body.username}'")
        return {
            "ok": True,
            "user_id": result.get("id", ""),
            "username": body.username,
            "role": "user",
            "is_first_user": True,
            "is_admin": False,
        }

    # Standard mode — only allowed before the first admin exists.
    if not is_first_user():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is closed. Ask an administrator to create your account.",
        )

    existing = {u["username"]: u for u in list_users()}
    if body.username in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This name belongs to a deleted account; purge or restore it first"
                if existing[body.username].get("deleted_at")
                else "Username already taken"
            ),
        )

    add_user(body.username, body.password)
    user_id = ""
    role = "user"
    for item in list_users():
        if item.get("username") == body.username:
            user_id = str(item.get("id") or "")
            role = str(item.get("role") or "user")
            break
    logger.info(f"First user (admin) registered: '{body.username}'")
    return {
        "ok": True,
        "user_id": user_id,
        "username": body.username,
        "role": role,
        "is_first_user": True,
        "is_admin": role == "admin",
    }


@router.get("/is_first_user")
async def check_is_first_user() -> dict:
    """Return whether the user store is empty (used by the register UI)."""
    return {"is_first_user": is_first_user() if AUTH_ENABLED else False}


# ---------------------------------------------------------------------------
# Profile endpoints (any authenticated user, self-service)
# ---------------------------------------------------------------------------

_AVATAR_MAX_BYTES = 1 * 1024 * 1024
_AVATAR_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _sniff_image(data: bytes) -> str | None:
    """Detect a supported raster image format from its magic bytes.

    The uploaded filename and Content-Type are attacker-controlled, so the
    stored extension (and the media type served back) is derived from the
    bytes alone. SVG is deliberately unsupported — serving user-supplied SVG
    is a stored-XSS vector.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _require_profile_identity(payload: TokenPayload | None) -> TokenPayload:
    """Shared guard for the self-service profile endpoints."""
    if not AUTH_ENABLED or payload is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth is disabled — profiles are not available.",
        )
    return payload


@router.get("/profile", response_model=UserInfo)
async def get_profile(
    payload: TokenPayload | None = Depends(require_auth),
) -> UserInfo:
    """Return the current user's own account info."""
    current = _require_profile_identity(payload)
    info = get_user_info(current.username)
    if info is None:
        # PocketBase-backed identities have no local record; fall back to the
        # token claims so the profile page still renders.
        return UserInfo(
            id=current.user_id,
            username=current.username,
            role=current.role,
            created_at="",
        )
    return UserInfo(**info)


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    payload: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Update the current user's own avatar marker (icon choice or reset).

    Only the validated ``icon:<name>:<color>`` form (or empty string) is
    accepted here; ``img:`` markers are owned by the upload endpoint.
    """
    current = _require_profile_identity(payload)
    if not set_avatar(current.username, body.avatar):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # The marker no longer references an uploaded image, so drop the file.
    from deeptutor.multi_user.identity import delete_avatar_file

    if current.user_id and _USER_ID_RE.match(current.user_id):
        delete_avatar_file(current.user_id)
    return {"ok": True, "avatar": body.avatar}


@router.put("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    payload: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Upload an avatar image for the current user.

    The client is expected to crop/resize before uploading; the server only
    enforces a size cap and validates the format by magic bytes. Not available
    in PocketBase mode (those identities have no local user record).
    """
    current = _require_profile_identity(payload)
    if POCKETBASE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Avatar upload is not available in PocketBase mode.",
        )
    if not current.user_id or not _USER_ID_RE.match(current.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot store an avatar for this account.",
        )
    info = get_user_info(current.username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    data = await file.read(_AVATAR_MAX_BYTES + 1)
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Avatar image is too large (max 1 MB).",
        )
    ext = _sniff_image(data)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Avatar must be a PNG, JPEG or WebP image.",
        )

    from deeptutor.multi_user.identity import save_avatar_file

    # Bump the version embedded in the marker so clients cache-bust the URL.
    previous = str(info.get("avatar") or "")
    version = 1
    if previous.startswith("img:"):
        try:
            version = int(previous.split(":", 1)[1]) + 1
        except ValueError:
            version = 1
    marker = f"img:{version}"

    save_avatar_file(current.user_id, data, ext)
    if not set_avatar(current.username, marker):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    logger.info(f"User '{current.username}' uploaded a new avatar ({ext}, {len(data)} bytes)")
    return {"ok": True, "avatar": marker}


@router.delete("/profile/avatar")
async def remove_avatar(
    payload: TokenPayload | None = Depends(require_auth),
) -> dict:
    """Remove the current user's uploaded avatar image and reset the marker."""
    current = _require_profile_identity(payload)
    from deeptutor.multi_user.identity import delete_avatar_file

    if current.user_id and _USER_ID_RE.match(current.user_id):
        delete_avatar_file(current.user_id)
    set_avatar(current.username, "")
    return {"ok": True, "avatar": ""}


@router.get("/avatar/{user_id}")
async def get_avatar_image(
    user_id: str,
    _: TokenPayload | None = Depends(require_auth),
) -> FileResponse:
    """Serve a stored avatar image. Any authenticated user may view avatars
    (they appear in the admin table and next to the viewer's own profile)."""
    if not _USER_ID_RE.match(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    from deeptutor.multi_user.identity import get_avatar_file

    target = get_avatar_file(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    media_type = _AVATAR_MEDIA_TYPES.get(target.suffix.lstrip("."), "application/octet-stream")
    headers = {
        # Private user content; the marker version in the URL handles busting.
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    return FileResponse(path=str(target), media_type=media_type, headers=headers)


# ---------------------------------------------------------------------------
# Admin-only endpoints
# ---------------------------------------------------------------------------


@router.get("/devices")
async def list_devices(
    user_id: str | None = None,
    include_revoked: bool = False,
    _: TokenPayload = Depends(require_admin),
) -> dict:
    """List local device credential metadata without credential secrets."""

    _require_builtin_device_auth()
    credentials = list_device_credentials(user_id=user_id, include_revoked=include_revoked)
    users = {str(user.get("id") or ""): str(user.get("username") or "") for user in list_users()}
    return {
        "devices": [
            {**device, "username": users.get(device["user_id"], "")} for device in credentials
        ]
    }


@router.post("/devices", status_code=status.HTTP_201_CREATED)
async def issue_device(
    body: DeviceCredentialCreateRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Issue a revocable device credential for an ordinary local account."""

    _require_builtin_device_auth()
    if get_user_by_id(body.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        device, pairing_code, pin = issue_device_credential(
            user_id=body.user_id,
            device_name=body.device_name,
            expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days),
            daily_limit_minutes=body.daily_limit_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_admin_action(
        "device_credential_issue",
        target_user_id=body.user_id,
        summary={
            "device_credential_id": device["id"],
            "device_name": device["device_name"],
            "expires_at": device["expires_at"],
            "daily_limit_minutes": device["daily_limit_minutes"],
        },
    )
    logger.info(
        f"Admin '{current.username if current else 'local'}' issued device "
        f"credential {device['id']} for user id '{body.user_id}'"
    )
    return {
        "device": device,
        "pairing_code": pairing_code,
        "pin": pin,
    }


@router.delete("/devices/{device_credential_id}")
async def revoke_device(
    device_credential_id: str,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    _require_builtin_device_auth()
    device = revoke_device_credential(
        device_credential_id,
        revoked_by=str(current.user_id if current else ""),
    )
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device credential not found",
        )
    log_admin_action(
        "device_credential_revoke",
        target_user_id=device["user_id"],
        summary={"device_credential_id": device["id"]},
    )
    return {"device": device, "ok": True}


@router.get("/users", response_model=list[UserInfo])
async def get_users(_: TokenPayload = Depends(require_admin)) -> list[UserInfo]:
    """List all registered users. Requires admin role."""
    from deeptutor.multi_user.primary_admin import is_primary_admin_account

    return [
        UserInfo(**u, is_primary=is_primary_admin_account(str(u.get("id") or "")))
        for u in list_users()
    ]


def _require_local_learner(current: TokenPayload) -> tuple[str, dict]:
    """Resolve a self-service profile request to its local learner account."""

    if current.role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Learner profile required"
        )
    account = get_user_by_id(current.user_id)
    if account is None or account[0] != current.username:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if str(account[1].get("preset") or "standard") != "learner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Learner profile required"
        )
    return account


@router.get("/profile/learner-profile")
async def get_current_learner_profile(current: TokenPayload = Depends(require_auth)) -> dict:
    """Return the authenticated learner's own profile."""
    _require_local_learner(current)
    profile = load_learner_profile(current.username)
    return {"learner_profile": profile}


@router.put("/profile/learner-profile")
async def put_current_learner_profile(
    body: LearnerProfileRequest,
    current: TokenPayload = Depends(require_auth),
) -> dict:
    """Update only the authenticated learner's own profile."""
    _require_local_learner(current)
    from deeptutor.multi_user.learner_profile import normalize_profile

    try:
        profile = normalize_profile(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    updated = set_learner_profile(current.username, profile)
    log_usage(
        "learner_profile",
        current.user_id,
        "self_update",
        {"fields": sorted(profile or {})},
    )
    return {"learner_profile": updated}


@router.get("/users/{username}/learner-profile")
async def get_learner_profile(username: str, _: TokenPayload = Depends(require_admin)) -> dict:
    """Return the structured profile managed for an ordinary learner."""
    from deeptutor.multi_user.identity import get_user

    user = get_user(username)
    if (
        user is None
        or str(user.get("role") or "user") != "user"
        or str(user.get("preset") or "standard") != "learner"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"learner_profile": user.get("learner_profile")}


@router.put("/users/{username}/learner-profile")
async def put_learner_profile(
    username: str,
    body: LearnerProfileRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    from deeptutor.multi_user.identity import get_user
    from deeptutor.multi_user.learner_profile import normalize_profile

    user = get_user(username)
    if (
        user is None
        or str(user.get("role") or "user") != "user"
        or str(user.get("preset") or "standard") != "learner"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        profile = normalize_profile(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    updated = set_learner_profile(username, profile)
    log_admin_action(
        "learner_profile_update",
        target_user_id=str(user.get("id") or ""),
        summary={"fields": sorted(profile or {})},
    )
    logger.info("Admin '%s' updated learner profile for '%s'", current.username, username)
    return {"learner_profile": updated}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def admin_create_user(
    body: AdminCreateUserRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Admin-only: create a new user account.

    Replaces the public ``/register`` flow once the first admin exists. The
    new account is always created with role=``user``; admins can promote
    later via ``PUT /users/{username}/role``.
    """
    if not AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Auth is disabled — user creation is not available.",
        )

    if POCKETBASE_ENABLED:
        if body.preset != "standard":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only the standard preset is available in PocketBase mode.",
            )
        result = register_pb(username=body.username, email=body.username, password=body.password)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Failed to create user — username may already be taken.",
            )
        logger.info(
            f"Admin '{current.username if current else 'local'}' created PocketBase user "
            f"'{body.username}'"
        )
        return {
            "ok": True,
            "user_id": result.get("id", ""),
            "username": body.username,
            "role": "user",
            "is_admin": False,
            "preset": "standard",
        }

    existing = {u["username"]: u for u in list_users()}
    if body.username in existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This name belongs to a deleted account; purge or restore it first"
                if existing[body.username].get("deleted_at")
                else "Username already taken"
            ),
        )

    add_user(body.username, body.password, preset=body.preset)
    user_id = ""
    role = "user"
    preset = "standard"
    for item in list_users():
        if item.get("username") == body.username:
            user_id = str(item.get("id") or "")
            role = str(item.get("role") or "user")
            preset = str(item.get("preset") or "standard")
            break
    if preset == "learner":
        from deeptutor.multi_user.grants import learner_grant, save_grant

        try:
            save_grant(user_id, learner_grant(user_id))
        except Exception as exc:
            rolled_back = False
            try:
                rolled_back = delete_user(body.username)
            except Exception:
                logger.exception(
                    "Failed to roll back user '%s' after learner grant initialization failed",
                    body.username,
                )
            if not rolled_back:
                logger.error(
                    "Learner account '%s' may remain after grant initialization failed",
                    body.username,
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="The learner preset could not be initialized.",
            ) from exc
    log_admin_action(
        "account_create",
        target_user_id=user_id or None,
        summary={"username": body.username, "role": role, "preset": preset},
    )
    logger.warning(
        "Admin '%s' created user '%s' (role=%r, preset=%r)",
        current.username if current else "local",
        body.username,
        role,
        preset,
    )
    return {
        "ok": True,
        "user_id": user_id,
        "username": body.username,
        "role": role,
        "is_admin": role == "admin",
        "preset": preset,
    }


def _refuse_primary_admin(info: dict | None, current: TokenPayload | None, action: str) -> None:
    """Fork: no admin may demote or delete the primary administrator.

    The primary admin owns the deployment and is its superadmin (decided
    2026-09-15). Refusing the demotion also keeps the learner routes -- a
    password reset among them -- closed to it, since those refuse admin targets.
    """
    from deeptutor.multi_user.primary_admin import is_primary_admin_account

    if not info or not is_primary_admin_account(str(info.get("id") or "")):
        return
    logger.warning(
        "Admin '%s' tried to %s the primary administrator '%s'; refused",
        current.username if current else "local",
        action,
        info.get("username", ""),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "The primary administrator cannot be deleted"
            if action == "delete"
            else "The primary administrator cannot be disabled"
            if action == "disable"
            else "The primary administrator's role cannot be changed"
        ),
    )


def _require_primary_admin(current: TokenPayload | None, action: str, target: dict) -> None:
    """Fork: promoting, demoting and deleting are the primary admin's alone.

    Decided 2026-09-15 (docs/planning/admin-roles/, §2): other admins keep
    creating accounts and managing ordinary users. A refusal is audited and
    logged, since two admin accounts once vanished from the host with no trace.
    """
    from deeptutor.multi_user.primary_admin import is_primary_admin_account

    if current is None or is_primary_admin_account(str(current.user_id or "")):
        return
    target_name = str(target.get("username") or "")
    log_admin_action(
        "account_change_refused",
        target_user_id=str(target.get("id") or "") or None,
        summary={"action": action, "username": target_name},
    )
    logger.warning(
        "Admin '%s' tried to %s '%s'; refused: only the primary administrator manages "
        "administrators",
        current.username,
        action,
        target_name,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the primary administrator can change roles or delete accounts",
    )


@router.delete("/users/{username}", status_code=status.HTTP_200_OK)
async def remove_user(
    username: str,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Fork: delete moves the account to the bin (admin design §4, Phase 2).

    The record stays, so the name stays taken and everything the account owns
    stays where it is; it cannot sign in, its device credentials are revoked,
    and the primary admin can restore it. What removes its data is the
    separate, typed purge below. Only the primary admin, never its own
    account, never the primary admin.
    """
    from deeptutor.multi_user.device_credentials import revoke_device_credentials_for_user
    from deeptutor.multi_user.identity import set_deleted

    if current and username == current.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )

    info = get_user_info(username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _refuse_primary_admin(info, current, "delete")
    _require_primary_admin(current, "delete", info)

    if not set_deleted(username, True):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user_id = str(info.get("id") or "")
    revoked = 0
    if user_id:
        revoked = revoke_device_credentials_for_user(
            user_id, revoked_by=str(current.user_id if current else "local")
        )
    deleted_at = str((get_user_info(username) or {}).get("deleted_at") or "")

    log_admin_action(
        "account_delete",
        target_user_id=user_id or None,
        summary={"username": username, "role": str(info.get("role") or "user")},
    )
    logger.warning(
        "Admin '%s' moved account '%s' to the bin (role=%s, device credentials revoked=%d)",
        current.username if current else "local",
        username,
        info.get("role") or "user",
        revoked,
    )
    return {"ok": True, "deleted_at": deleted_at}


@router.post("/users/{username}/restore", status_code=status.HTTP_200_OK)
async def restore_user(
    username: str,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Fork: take an account back out of the bin, exactly as it was."""
    from deeptutor.multi_user.identity import set_deleted

    info = get_user_info(username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_primary_admin(current, "restore", info)
    if not info.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This account is not in the bin"
        )
    set_deleted(username, False)
    user_id = str(info.get("id") or "")
    log_admin_action(
        "account_restore",
        target_user_id=user_id or None,
        summary={"username": username, "role": str(info.get("role") or "user")},
    )
    logger.warning(
        "Admin '%s' restored account '%s' from the bin (role=%s)",
        current.username if current else "local",
        username,
        info.get("role") or "user",
    )
    return {"ok": True}


def _require_typed_name(confirm: str | None, expected: str) -> None:
    """A purge is irreversible; the caller types the name it means."""
    if confirm != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type the account name exactly to confirm the purge",
        )


def _purgeable_or_403(user_id: str) -> None:
    from deeptutor.multi_user.purge import is_purgeable_account_id

    if not is_purgeable_account_id(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The data of this account cannot be purged",
        )


@router.get("/users/{username}/footprint", status_code=status.HTTP_200_OK)
async def user_footprint(
    username: str,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Fork: what a purge of this account would remove on DeepWitya's side."""
    from deeptutor.multi_user.purge import account_footprint

    info = get_user_info(username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_primary_admin(current, "measure", info)
    user_id = str(info.get("id") or "")
    _purgeable_or_403(user_id)
    return {"footprint": account_footprint(user_id).as_dict()}


@router.delete("/users/{username}/purge", status_code=status.HTTP_200_OK)
async def purge_user(
    username: str,
    current: TokenPayload = Depends(require_admin),
    confirm: str | None = None,
) -> dict:
    """Fork: remove an account in the bin and everything it owns here.

    Only from the bin (409 otherwise), only the primary admin, only with the
    name typed (``?confirm=<username>``). The studio's half is the browser's
    call before this one (design §4); the two are independent and each is
    idempotent, so a failure on either side leaves something to press again.
    """
    from deeptutor.multi_user.identity import delete_avatar_file
    from deeptutor.multi_user.purge import purge_account_data

    info = get_user_info(username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _require_primary_admin(current, "purge", info)
    user_id = str(info.get("id") or "")
    _purgeable_or_403(user_id)
    if not info.get("deleted_at"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delete the account first; a purge only takes an account from the bin",
        )
    _require_typed_name(confirm, username)

    removed = purge_account_data(user_id)
    delete_avatar_file(user_id)
    delete_user(username)  # the record and its guardian links
    summary = {"username": username, "role": str(info.get("role") or "user"), **removed.as_dict()}
    summary.pop("locations", None)
    log_admin_action("account_purge", target_user_id=user_id or None, summary=summary)
    logger.warning(
        "Admin '%s' purged account '%s' (%s)",
        current.username if current else "local",
        username,
        user_id,
    )
    return {"ok": True, "removed": removed.as_dict()}


@router.get("/orphans", status_code=status.HTTP_200_OK)
async def list_orphans(current: TokenPayload = Depends(require_admin)) -> dict:
    """Fork: ids that still hold data here but have no account (a shallow
    delete from before the bin). Primary admin only."""
    from deeptutor.multi_user.purge import account_footprint, orphan_ids

    _require_primary_admin(current, "list leftovers", {"username": "", "id": ""})
    return {
        "orphans": [
            {"user_id": user_id, "footprint": account_footprint(user_id).as_dict()}
            for user_id in orphan_ids()
        ]
    }


@router.delete("/orphans/{user_id}", status_code=status.HTTP_200_OK)
async def purge_orphan(
    user_id: str,
    current: TokenPayload = Depends(require_admin),
    confirm: str | None = None,
) -> dict:
    """Fork: purge the data of an id that has no account (``?confirm=<id>``)."""
    from deeptutor.multi_user.identity import get_user_by_id
    from deeptutor.multi_user.purge import is_purgeable_account_id, purge_account_data

    _require_primary_admin(current, "purge leftovers of", {"username": "", "id": user_id})
    if not is_purgeable_account_id(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a purgeable account id"
        )
    if get_user_by_id(user_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This id belongs to an account; delete and purge it from the users list",
        )
    _require_typed_name(confirm, user_id)
    removed = purge_account_data(user_id)
    summary = {"username": "", "orphan": True, **removed.as_dict()}
    summary.pop("locations", None)
    log_admin_action("account_purge", target_user_id=user_id, summary=summary)
    logger.warning(
        "Admin '%s' purged the leftovers of %s (no account)",
        current.username if current else "local",
        user_id,
    )
    return {"ok": True, "removed": removed.as_dict()}


@router.put("/users/{username}/role", status_code=status.HTTP_200_OK)
async def update_user_role(
    username: str,
    body: SetRoleRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Change a user's role. Only the primary admin may, and not its own role."""
    if current and username == current.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role",
        )
    info = get_user_info(username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _refuse_primary_admin(info, current, "change the role of")
    _require_primary_admin(current, "change the role of", info)

    updated = set_role(username, body.role)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    previous = str(info.get("role") or "user")
    log_admin_action(
        "account_role_set",
        target_user_id=str(info.get("id") or "") or None,
        summary={"username": username, "from": previous, "to": body.role},
    )
    logger.warning(
        "Admin '%s' set '%s' role to %r (was %r)",
        current.username if current else "local",
        username,
        body.role,
        previous,
    )
    return {"ok": True, "username": username, "role": body.role}


@router.put("/users/{username}/disabled", status_code=status.HTTP_200_OK)
async def update_user_disabled(
    username: str,
    body: SetDisabledRequest,
    current: TokenPayload = Depends(require_admin),
) -> dict:
    """Fork: shut an account, or reopen it, instead of deleting it.

    Any admin for an ordinary user; the primary admin alone for an admin;
    nobody for the primary admin or themselves (docs/planning/admin-roles/,
    §3). The account keeps everything it owns; its tokens stop working on
    the next request and its device credentials are revoked.
    """
    from deeptutor.multi_user.device_credentials import revoke_device_credentials_for_user
    from deeptutor.multi_user.identity import set_disabled

    if current and username == current.username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot disable your own account",
        )
    info = get_user_info(username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    action = "disable" if body.disabled else "enable"
    _refuse_primary_admin(info, current, "disable")
    role = str(info.get("role") or "user")
    if role == "admin":
        _require_primary_admin(current, action, info)

    if not set_disabled(username, body.disabled):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user_id = str(info.get("id") or "")
    revoked = 0
    if body.disabled and user_id:
        revoked = revoke_device_credentials_for_user(
            user_id, revoked_by=str(current.user_id if current else "local")
        )

    log_admin_action(
        f"account_{action}",
        target_user_id=user_id or None,
        summary={"username": username, "role": role},
    )
    logger.warning(
        "Admin '%s' %sd account '%s' (role=%s, device credentials revoked=%d)",
        current.username if current else "local",
        action,
        username,
        role,
        revoked,
    )
    return {"ok": True, "username": username, "disabled": body.disabled}
