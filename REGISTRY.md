# Registry Protocol

The contract a registry must honor to serve Cartograph clients. The CLI is
the reference consumer: the endpoint metadata in `src/cartograph/cloud.py`
is the source of truth for the wire surface, and `_validate_widgets()` in
the same file is the source of truth for the widget row contract. When this
document and the code disagree, the code wins - file an issue.

Audience: anyone implementing or operating a registry - self-hosted,
company-internal, or hosted-for-you. The hosted public registry at
`api.cartograph.tools` (prefix `cg`) implements all of this; a minimal
registry needs only the read tier.

## The model

A registry is an HTTP service that stores immutable, validated widget
versions and answers search. Clients are configured with
`cartograph registry add <url>`; from then on the registry's widgets are
searchable and installable under its prefix (`<prefix>-<widget-id>`).

Three design rules shape everything below:

1. **Your response order is your ranking.** The client displays search
   results in exactly the order you return them. It never re-sorts, and it
   deduplicates by first occurrence. Relevance scores you include are
   informational only. Own your ranking algorithm - the client will not
   second-guess it.
2. **Published versions are immutable.** There is no re-publish of an
   existing version. Fix and bump.
3. **The client is tolerant; degradation is silent.** Malformed widget rows
   are dropped with a client-side warning log, not an error. A broken
   registry is the registry owner's problem - but your users will see
   missing results, not failure messages. Conform.

## Identity and the prefix handshake

Every registry has a short **prefix** (e.g. `myorg`). It namespaces install
commands (`cartograph install myorg-retry-backoff-python`) and scopes search
(`cartograph search retry --registry myorg`).

- `GET /info` (registry root, NOT under /v1) must return JSON with at least
  `{"prefix": "<your-prefix>"}`. `cartograph registry add <url>` calls this
  to discover the prefix; the server's value wins over anything the user
  passes.
- The prefix `cg` is reserved for the public registry.
- Widget IDs in your responses use the form `@owner/widget-id`
  (e.g. `@alice/backend-retry-python`). The client rewrites them to
  `@owner/<prefix>-widget-id` for display and install routing - never
  include your own prefix in the IDs you return.

## Capabilities

- `GET /v1/registry/info` returns capability flags, e.g.
  `{"validates": true, "allow_blueprints": false, "supports_visibility": true}`.
  Optional: if absent, the client assumes `{"validates": false}` and treats
  `allow_blueprints` as true.
- `validates`: whether the registry re-validates uploads server-side.
- `allow_blueprints`: whether blueprint publishes are accepted. The public
  registry refuses blueprints (they are personal/org-internal by policy);
  company registries may choose to accept them.

## Read tier (minimum viable registry)

A read-only registry needs four endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /info` | Prefix handshake |
| `GET /v1/widgets/search` | Search |
| `GET /v1/widgets/{owner}/{widget_id}` | Inspect (`?include_source=true` for src/ contents, `?include_manifest=true` for raw widget.json) |
| `GET /v1/widgets/{owner}/{widget_id}/download` | Install (zip) |

### Search

`GET /v1/widgets/search?q=<query>&top_k=<n>[&domain=<d>][&language=<l>][&languages=<l1,l2,...>]`

- Return at most `top_k` results as `{"widgets": [<row>, ...]}` in ranked
  order (rule 1 above).
- `domain` and `language` are hard filters when present.
- `languages` (comma-separated) is a hard filter to the set of languages
  the client can use locally (`show-unavailable false`). Apply it BEFORE
  ranking and truncating to `top_k` so the page fills with installable
  widgets. A registry that ignores it stays correct: the client re-filters
  client-side as a backstop, it just wastes payload. `language` (singular,
  the user's `--language`) and `languages` may both be present; honor both.
- How you rank is entirely yours: lexical, embeddings, popularity-weighted,
  hand-curated. The client-side budget decides how many of your rows are
  shown next to local and other-registry results, but never their order.

### Widget row contract

Each element of `widgets`:

Required - the row is dropped client-side if missing or mistyped:

- `id` (str) - `@owner/widget-id`
- `version` (str) - semver

Expected - the client falls back to defaults but UX degrades:

- `name`, `domain`, `language`, `description`, `tags`, `rating`, `owner`,
  `install_count`

Optional - passed through untouched; the registry may add fields freely:

- `relevance_score` (informational only), `stale`, `deprecated`,
  `last_updated`, or any future annotations

Notes:

- The client truncates `description` to 200 characters in search displays.
  Front-load the first sentence; the full text shows on inspect.
- `dependencies` should be present (empty list if none) - agents check
  whether a dependency exists before inspecting.

### Download

- Respond with the widget zip (`application/zip`).
- `X-Widget-Version` and `X-Widget-Governance` response headers carry
  metadata the client records at install time.
- Zip contents must only use file extensions of registered language
  engines. The client sends the allowed set as an `allowed_extensions`
  field on publish (derived from its engines via `allowed_extensions()`),
  so registries enforce it without hardcoding - new languages are accepted
  automatically.

## Write tier

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/widgets/{widget_id}/publish` | Publish a version (multipart: metadata fields + zip as `file`) |
| `DELETE /v1/widgets/{widget_id}` | Remove a widget |
| `PATCH /v1/widgets/{owner}/{widget_id}` | Update settings (governance, visibility) |
| `GET /v1/widgets/{owner}/{widget_id}/versions` | List published versions |
| `POST /v1/widgets/{owner}/{widget_id}/rollback` | Roll back to an earlier version |
| `GET /v1/widgets` | List all widgets (`top_k` capped) |

Publishing rules the client relies on:

- Reject a version that already exists (immutability, rule 2).
- Widgets carry a validation stamp from the client-side pipeline; a
  registry with `validates: true` re-checks server-side, but the stamp is
  the baseline quality floor either way.

## Social tier (optional)

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/widgets/{owner}/{widget_id}/reviews` | List reviews |
| `POST /v1/widgets/{owner}/{widget_id}/rate` | Rate 1-5 with optional comment |
| `GET /v1/users/search` | Search users by handle |
| `POST /v1/widgets/{owner}/{widget_id}/contribute` | Submit a change proposal (protected governance) |
| `GET/POST .../proposals[/{id}/diff,accept,reject]` | Proposal review flow |
| `GET /v1/auth/my-widgets`, `GET /v1/auth/my-proposals` | Per-user listings |

A registry without these simply has no ratings or proposal flow - the
client degrades gracefully.

## Auth

- The client sends `Authorization: Bearer <token>` on authenticated calls.
  Read-tier endpoints should work unauthenticated for public widgets.
- Token issuance is the registry's business. Users store a token per
  registry with `cartograph login --registry <url> --token <token>`.
- `GET /v1/auth/me` returns the current user's profile (at least an
  `owner`/`username` handle). The client caches this for 24h.
- `GET /v1/auth/tos` / `POST /v1/auth/accept-tos` are optional terms-of-
  service gates.

## Errors

Return JSON `{"error": "<human-readable message>"}` with an appropriate
HTTP status. The client surfaces registry errors per-prefix in search
(`registry_errors`) and verbatim elsewhere - write messages a human (or an
agent) can act on.

## Conformance

Run the probe from a checkout of this repo:

```bash
python scripts/registry_check.py https://your-registry.example.com [--query term] [--token t]
```

It checks the prefix handshake, capabilities, search shape, the widget row
contract (judged by the same validator the client uses), inspect, download,
and error shape, and reports pass/warn/fail per check. It is a dev tool by
design - it ships in the repo, not the package, and is not part of the
agent-facing CLI surface.

Note: the hosted public registry does not serve `GET /info` - its prefix
(`cg`) is hardcoded in the client and `registry add` refuses the public
URL, so the handshake never fires for it. Third-party registries MUST
serve `/info`; the probe's failure on the public registry is expected.
