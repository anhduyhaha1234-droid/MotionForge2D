"""API security boundary helpers (S08-H02).

This module owns the two hardening pieces the sprint-exit review required:

- :class:`OriginGuardMiddleware` — replaces the previous wildcard CORS with a
  *configurable origin allowlist* plus an origin guard:

  - No ``Origin`` header  → the request is a native/CLI local-app contract
    call and is passed through untouched;
  - ``Origin`` in the configured allowlist → normal operation, and the
    middleware emits ``Access-Control-Allow-Origin`` for it (credentials are
    NOT enabled — this is a local JWT-free app; ``allow_credentials`` defaults
    to False and is only turned on through explicit configuration);
  - Other ``Origin`` (or ``Origin: null``) → state-changing requests
    (POST/PUT/PATCH/DELETE) get a **403 before any side effect** (the route
    never runs), preflight OPTIONS get a 403 with **no valid ACAO**, and safe
    reads pass through with no ACAO emitted (a browser is not able to read the
    response).

  The allowlist is read from :func:`app.api.deps.get_config` at *request*
  time (not captured at construction), so launchers and tests can configure
  ``MOTIONFORGE_CORS_ORIGINS`` deterministically.

- :func:`validate_path_identifier` — identifier validation that MUST run
  before any identifier is joined into a filesystem path.  It rejects path
  separators, ``..`` traversal, absolute-path shapes, control bytes and
  over-length values, so a project/object identifier can never escape the
  managed project root through a raw ``Path.joinpath``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Requests that mutate state.  When an untrusted Origin is present they must
#: be rejected BEFORE the route (and therefore before any side effect).
_STATE_CHANGING_METHODS: frozenset[str] = frozenset(
    {"POST", "PUT", "PATCH", "DELETE"}
)
#: Methods a cross-origin preflight may request (echoed untouched).
_ALLOWED_METHODS: frozenset[str] = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)

#: An identifier used as a single filesystem path segment.
#: Project ids are ``uuid4().hex[:12]`` and object ids ``uuid4().hex[:8]``;
#: we stay permissive (word chars, dot, dash) but forbid anything that could
#: traverse or escape a joined path.
_PATH_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_MAX_IDENTIFIER_LENGTH = 200

#: Precise header names (bytes) as they travel through an ASGI message.
_HDR_ORIGIN = b"origin"
_HDR_ACAO = b"access-control-allow-origin"
_HDR_ACAC = b"access-control-allow-credentials"
_HDR_ACAM = b"access-control-allow-methods"
_HDR_ACAH = b"access-control-allow-headers"
_HDR_VARY = b"vary"
_HDR_ACRM = b"access-control-request-method"


class InvalidPathIdentifierError(ValueError):
    """An identifier is not safe to join into a filesystem path."""


def validate_path_identifier(value: str, *, label: str = "identifier") -> str:
    """Return *value* unchanged when it is safe as a single path segment.

    Raises :class:`InvalidPathIdentifierError` otherwise.  Run this before any
    filesystem join of a client-supplied project/object identifier.
    """
    if not isinstance(value, str) or not value:
        raise InvalidPathIdentifierError(f"{label} is empty")
    if len(value) > _MAX_IDENTIFIER_LENGTH:
        raise InvalidPathIdentifierError(
            f"{label} exceeds {_MAX_IDENTIFIER_LENGTH} characters"
        )
    if not _PATH_IDENTIFIER_RE.fullmatch(value):
        raise InvalidPathIdentifierError(
            f"{label} {value!r} contains characters that are not allowed in a "
            "filesystem path segment"
        )
    if ".." in value:
        raise InvalidPathIdentifierError(
            f"{label} {value!r} contains a path-traversal sequence"
        )
    return value


def _is_state_changing(method: str) -> bool:
    return method in _STATE_CHANGING_METHODS


class OriginGuardMiddleware:
    """CORS allowlist + untrusted-origin guard (S08-H02).

    Added *last* (outermost) in the app so it runs before every route: an
    untrusted state-changing request never reaches its handler.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        origins_provider: Callable[[], Iterable[str]],
        allow_credentials: bool = False,
    ) -> None:
        self.app = app
        self._origins_provider = origins_provider
        self._allow_credentials = allow_credentials

    def _allowed(self, origin: str) -> bool:
        normalized = origin.rstrip("/")
        return any(
            str(candidate).rstrip("/") == normalized
            for candidate in self._origins_provider()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        origin = request.headers.get("origin", "")
        method = (scope.get("method") or "GET").upper()

        # Local-app contract: native/CLI clients carry no Origin.
        if not origin:
            await self.app(scope, receive, send)
            return

        if self._allowed(origin):
            # Include credentials? No — the product never uses cookie
            # credentials; exposing ACAO is enough for a trusted origin.
            await self._dispatch_with_cors(scope, receive, send, origin)
            return

        # ── Untrusted Origin (or Origin:null) ──────────────────────────────
        if _is_state_changing(method):
            response = JSONResponse(
                {"detail": "untrusted origin rejected"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        if method == "OPTIONS":
            # Preflight from a disallowed origin MUST NOT receive a valid ACAO.
            response = JSONResponse(
                {"detail": "origin not allowed"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        # Safe reads: let the route run, but emit NO cross-origin headers so a
        # browser cannot read the response through an untrusted page.
        await self.app(scope, receive, send)

    async def _dispatch_with_cors(
        self, scope: Scope, receive: Receive, send: Send, origin: str
    ) -> None:
        """Dispatch to the app, decorating the response with ACAO.

        A preflight (OPTIONS with ``Access-Control-Request-Method``) is
        answered directly with 200 + the CORS headers, without touching the
        route table.
        """
        request = Request(scope)
        method = (scope.get("method") or "GET").upper()

        if method == "OPTIONS" and request.headers.get("access-control-request-method"):
            headers: dict[str, str] = {
                "access-control-allow-origin": origin,
                "vary": "Origin",
                "access-control-allow-methods": ", ".join(sorted(_ALLOWED_METHODS)),
            }
            req_headers = request.headers.get("access-control-request-headers")
            if req_headers:
                headers["access-control-allow-headers"] = req_headers
            if self._allow_credentials:
                headers["access-control-allow-credentials"] = "true"
            await Response(status_code=200, headers=headers)(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                extra: list[tuple[bytes, bytes]] = [
                    (_HDR_ACAO, origin.encode("latin-1")),
                    (_HDR_VARY, b"Origin"),
                ]
                if self._allow_credentials:
                    extra.append((_HDR_ACAC, b"true"))
                # Replace any pre-existing ACAO so a downstream layer can never
                # leak a stale wildcard.
                merged = [h for h in existing if h[0].lower() != _HDR_ACAO]
                message["headers"] = merged + extra
            await send(message)

        await self.app(scope, receive, send_wrapper)
