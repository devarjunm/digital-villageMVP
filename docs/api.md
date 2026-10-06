# API contracts (v1)

Base URL: `{host}/api/v1`. All responses JSON. All list endpoints are paginated.
OpenAPI is served by the app itself at `/docs` (Swagger UI) and `/openapi.json`;
this document is the human summary and is kept in sync with the routers.

## Conventions

**Success envelope (lists)**
```json
{ "items": [...], "page": 1, "page_size": 20, "total": 137,
  "total_pages": 7, "has_next": true }
```
**Error envelope (every failure, any status)**
```json
{ "error": { "code": "not_found", "message": "Farm not found",
             "details": {"farm_id": "..."}, "request_id": "0f1c..." } }
```
Codes: `validation_error` (422), `unauthorized` (401), `forbidden` (403),
`not_found` (404), `conflict` (409), `rate_limited` (429),
`payload_too_large` (413), `unsupported_media_type` (415),
`provider_unavailable` (503), `model_unavailable` (503), `internal_error` (500).

**Data-provenance fields** (present on every data-bearing response):

| Field | Values | Meaning |
|---|---|---|
| `is_demo` | bool | true = demo/local provider or seeded demo row |
| `provider` | string | `mock` \| `openweathermap` \| `data_gov_in` \| model name … |
| `source` | string | human-readable source label |
| `retrieved_at` | ISO-8601 | when external data was fetched (not stored rows) |
| `model_name`, `model_version` | string | for model outputs |
| `confidence` | 0..1 or null | model confidence/score, never a calibrated probability unless stated |
| `disclaimer` | string | mandatory non-certainty text for AI outputs |
| `trust_label` | enum | `farmer_experience` \| `community_supported` \| `expert_information` \| `official_information` \| `ai_prediction` |

**Headers** — request: `Authorization: Bearer <access>`, `X-Request-ID` optional
(echoed), `Accept-Language` (en|mr|hi). Response: `X-Request-ID`,
`X-Process-Time`, `X-RateLimit-Limit/Remaining/Reset` on limited routes.

## Auth — `/api/v1/auth`
| Method & path | Purpose | Notes |
|---|---|---|
| `POST /register` | create account | phone or email; returns user + tokens |
| `POST /otp/request` | send OTP | rate limited 3/15 min per identifier |
| `POST /otp/verify` | verify OTP → tokens | single-use, max attempts enforced |
| `POST /login` | password login (email) | Argon2id verify, lockout after N failures |
| `POST /password/reset/request` \| `/confirm` | recovery | OTP-based, no user enumeration |
| `POST /refresh` | rotate refresh token | old token revoked, reuse detection |
| `POST /logout` | revoke session | deletes device token optionally |
| `GET  /me` | current user + roles + profile summary | |
| `GET  /sessions` · `DELETE /sessions/{id}` | session management | |

## Farmers & farms — `/api/v1/farmers`, `/api/v1/farms`, `/api/v1/crops`
`GET/PATCH /farmers/me` (profile, language, region, experience, interests) ·
`GET /farmers/{id}/public` (name, village, state, crops, role — no phone/email) ·
`GET/POST /farms` · `GET/PATCH/DELETE /farms/{id}` ·
`GET /farms/{id}/summary` (crops + stage + weather snapshot + latest insights) ·
`GET/POST /farms/{id}/crops` · `GET/PATCH /crops/{id}` · `POST /crops/{id}/events`
· `POST /farms/{id}/soil-tests`.

## Community — `/api/v1/community`
`GET /posts` (filters: `category`, `crop`, `state`, `district`, `author_id`,
`following`, `saved`, `q`, `sort=relevance|recent|popular`, pagination) ·
`POST /posts` · `GET/PATCH/DELETE /posts/{id}` ·
`POST /posts/{id}/reactions` · `DELETE /posts/{id}/reactions` ·
`POST /posts/{id}/save` · `GET /posts/{id}/comments` (threaded) ·
`POST /posts/{id}/comments` · `PATCH/DELETE /comments/{id}` ·
`POST /posts/{id}/report` · `POST /comments/{id}/report` ·
`POST /users/{id}/follow` · `DELETE /users/{id}/follow` ·
`GET /users/{id}/profile` (public activity).
Feed ranking is deterministic (see `docs/architecture.md` §6 and
`backend/app/community/ranking.py`): relevance + recency decay + interaction
prior + personalization, all weights configurable and unit-tested.

## Moderation — `/api/v1/moderation` (MODERATOR/ADMIN)
`GET /queue` · `GET /cases/{id}` · `POST /cases/{id}/resolve`
(`dismiss|hide|remove|warn_author|restrict_author`) · `GET /audit-logs`.
AI-assisted signals (`spam_score`, `duplicate_of`, `tone_flags`) are attached to
cases as *advisory* fields and can never set `scientifically_false`.

## Weather — `/api/v1/weather`
`GET /current?lat&lon` · `GET /forecast?lat&lon&days=7` ·
`GET /alerts?state` · `GET /farm/{farm_id}` (convenience). Responses always
include `provider`, `is_demo`, `retrieved_at`; Redis-cached with a short TTL.

## Markets — `/api/v1/markets`
`GET /crops` · `GET /markets?state&district&q` ·
`GET /prices?crop&state&district&market&from&to` (each row: `source`,
`is_estimate`, `is_demo`) · `GET /prices/trend?crop&market&days=90` ·
`GET /arrivals?crop&market` · `POST /prices/estimate` (model-based, returns
`model_version` + interval and is clearly marked as an estimate).

## Schemes — `/api/v1/schemes`
`GET /` (filters: `state`, `category`, `q`, `eligible_only`) ·
`GET /{slug}` · `POST /{slug}/eligibility-check` (deterministic rules, returns
per-rule pass/fail/unknown + `official_source_url` + `last_verified_on`) ·
`GET /categories`.

## Knowledge & RAG — `/api/v1/knowledge`
`GET /documents` · `GET /documents/{id}` · `POST /documents` (MODERATOR/ADMIN;
ingestion enqueues chunking + embedding jobs) ·
`POST /retrieve` (query + metadata filters → chunks with citations) ·
`POST /ask` (RAG answer: `answer`, `citations[]`, `insufficient_evidence` flag).

## Search — `/api/v1/search`
`GET /?q=&types=posts,farmers,crops,schemes,knowledge,markets&mode=keyword|semantic|hybrid`
returns per-type grouped results with the matched mode and score.

## AI — `/api/v1/ai`
| Path | Purpose |
|---|---|
| `POST /crop-recommendation` | inputs: soil N/P/K, pH, temp, humidity, rainfall, soil type, season → ranked crops + `model_version` + limitations |
| `POST /disease/detect` (multipart) | image + optional crop → screening result, confidence, model version, evidence links, similar community posts; `503 model_unavailable` when no artifact |
| `GET /disease/history` | user's past scans |
| `POST /yield-prediction` | crop, area, soil, weather, irrigation, history → estimate + interval + metrics provenance |
| `POST /assistant/chat` | RAG + context answer with citations and source types |
| `POST /agent/run` | tool-using agent; returns `tool_trace[]` |
| `GET /agent/conversations`, `GET /agent/conversations/{id}` | history |
| `POST /feedback` | helpful / not helpful / incorrect + correction + `consent_to_train` |
| `GET /models` | active model registry entries (public metadata) |
| `GET /requests/{id}` | status/result of a long-running AI job |

Every AI response includes `ai_request_id` so the answer, its evidence and later
feedback are traceable end-to-end.

## Notifications — `/api/v1/notifications`
`GET /` (unread filter) · `POST /{id}/read` · `POST /read-all` ·
`GET/PUT /preferences` · `POST /devices` (register push token) ·
`DELETE /devices/{token}`.

## Admin — `/api/v1/admin` (ADMIN; some read-only for MODERATOR)
`GET /stats/overview` · `GET /stats/timeseries?metric=&days=` ·
`GET /users` + `PATCH /users/{id}` (status, roles) ·
`GET /posts`, `POST /posts/{id}/status` · `GET /reports` ·
`GET/POST/PATCH /schemes` · `GET/POST/PATCH /knowledge/documents` ·
`GET /ai/usage` · `GET /ai/models`, `POST /ai/models/{id}/activate` ·
`GET /system/health` · `GET /audit-logs` · `POST /jobs/reindex-embeddings`.

## Ops (unversioned)
`GET /health` (liveness, cheap) · `GET /ready` (DB + Redis + model dir checks,
503 when a required dependency is down) · `GET /metrics` (Prometheus).
