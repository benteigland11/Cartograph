"""
Typed response/request shapes for the cloud registry protocol.

Serves two audiences:

1. Python consumers of `cloud.py` — IDEs + mypy use the TypedDicts to catch
   field-name typos and surface what's safe to access on each response.
2. OpenAPI generation — `scripts/gen_openapi.py` introspects these TypedDicts
   and emits them as `components.schemas` entries so a registry author in any
   language gets a proper spec without reading Python.

The server is the authority on what fields actually appear; these dicts use
`total=False` so every field is optional at the type level. This matches the
reality that third-party registries may omit some fields and still be
compatible. Required-by-protocol fields are called out in comments.

To add a new endpoint's response, define a TypedDict here, then reference it
by class name in `@endpoint(response="YourResponse")` on the cloud.py function.
"""

from typing import TypedDict


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ErrorResponse(TypedDict, total=False):
    """Uniform error envelope. Every endpoint MAY return this shape instead of
    its nominal success body when something goes wrong. `error` is required
    when present; `status_code` is HTTP status; `status` is an optional label."""
    error: str
    status_code: int
    status: str


# ---------------------------------------------------------------------------
# Registry metadata
# ---------------------------------------------------------------------------

class RegistryInfoResponse(TypedDict, total=False):
    """`GET /v1/registry/info` — capability advertisement used by the client to
    gate per-registry features (e.g. private visibility, rename, aliases)."""
    name: str
    version: str
    validates: bool
    supports_visibility: bool
    supports_rename: bool


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class Review(TypedDict, total=False):
    user: str
    rating: float
    comment: str
    created_at: str


class WidgetRecord(TypedDict, total=False):
    """Shape returned by inspect, search results, list, my-widgets, etc.
    `id` (namespaced as `@owner/widget-id`) and `version` are the only
    fields clients rely on being present. Everything else is additive."""
    id: str
    namespaced_id: str
    version: str
    name: str
    owner: str
    domain: str
    language: str
    description: str
    tags: list[str]
    rating: float
    install_count: int
    governance: str
    visibility: str
    contributors: list[str]
    created_at: str
    published_at: str
    reviews: list[Review]
    # Client-computed hash echoed back by the server (issue #15). When present,
    # enables no-op guard and three-way status comparison without downloading
    # the widget zip.
    implementation_hash: str


class SearchResponse(TypedDict, total=False):
    widgets: list[WidgetRecord]


class ListWidgetsResponse(TypedDict, total=False):
    widgets: list[WidgetRecord]
    count: int


class InspectResponse(WidgetRecord):
    """Alias for WidgetRecord — the inspect endpoint returns a single record."""
    pass


class MyWidgetsResponse(TypedDict, total=False):
    widgets: list[WidgetRecord]


# ---------------------------------------------------------------------------
# Publish / push
# ---------------------------------------------------------------------------

class PushResponse(TypedDict, total=False):
    """`POST /v1/widgets/{widget_id}/publish` response."""
    status: str
    namespaced_id: str
    version: str
    governance: str
    visibility: str
    implementation_hash: str


# ---------------------------------------------------------------------------
# Versions / rollback
# ---------------------------------------------------------------------------

class VersionEntry(TypedDict, total=False):
    version: str
    published_at: str
    reason: str
    implementation_hash: str


class VersionsResponse(TypedDict, total=False):
    versions: list[VersionEntry]


class RollbackResponse(TypedDict, total=False):
    status: str
    version: str


# ---------------------------------------------------------------------------
# Ratings / reviews
# ---------------------------------------------------------------------------

class RateResponse(TypedDict, total=False):
    status: str
    rating: float


class ReviewsResponse(TypedDict, total=False):
    reviews: list[Review]
    avg_rating: float


# ---------------------------------------------------------------------------
# Proposals (contribute flow)
# ---------------------------------------------------------------------------

class ProposalResponse(TypedDict, total=False):
    """`POST /v1/widgets/{owner}/{id}/contribute` response. `status` is
    `published` when the origin widget's governance is `open` (auto-merged)
    or `proposed` when it's `protected` (queued for review)."""
    status: str
    proposal_id: str
    version: str


class ProposalRecord(TypedDict, total=False):
    id: str
    widget_id: str
    owner: str
    proposer: str
    reason: str
    status: str
    created_at: str


class ProposalListResponse(TypedDict, total=False):
    proposals: list[ProposalRecord]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class WhoamiResponse(TypedDict, total=False):
    authenticated: bool
    uid: str
    owner: str
    email: str
    tos_accepted: bool


class TosResponse(TypedDict, total=False):
    version: str
    text: str
    url: str


class AcceptTosResponse(TypedDict, total=False):
    status: str


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class UpdateWidgetResponse(TypedDict, total=False):
    status: str
    governance: str
    visibility: str


class DeleteResponse(TypedDict, total=False):
    status: str


# ---------------------------------------------------------------------------
# User search
# ---------------------------------------------------------------------------

class UserRecord(TypedDict, total=False):
    owner: str
    uid: str


class UserSearchResponse(TypedDict, total=False):
    users: list[UserRecord]
