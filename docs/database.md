# Database design

PostgreSQL 16+ is the system of record. Extensions: `vector` (pgvector, semantic
search) and `pg_trgm` (fuzzy keyword search). Migrations are managed by Alembic;
production deployments run `alembic upgrade head` as a release step and the API
never calls `create_all` when `APP_ENV=production`.

## Design rules

1. **UUIDv7-ish primary keys** — all tables use `uuid` PKs (generated app-side,
   `uuid4` where v7 is unavailable) so IDs are safe to expose in URLs.
2. **Timestamps** — `created_at`, `updated_at` (`server_default=now()`),
   `deleted_at` for soft deletion. Soft-deleted rows are filtered by repository
   defaults, not by ad-hoc query code.
3. **Audit** — mutating tables carry `created_by_id` / `updated_by_id`.
   Consequential actions (moderation, admin edits, scheme changes) also append to
   `audit_logs`.
4. **Constraints** — FKs everywhere, `CHECK` for enums that can't be native
   (`area_value > 0`, `confidence BETWEEN 0 AND 1`), partial unique indexes for
   "one active thing per user" rules.
5. **No destructive auto-migration** in production: `APP_ENV=production` +
   `alembic` only. `data/seed` refuses to run when `APP_ENV=production` unless
   `ALLOW_PROD_SEED=true`.
6. **No big binaries in Postgres** — images live in object storage; the DB stores
   key, MIME, size, checksum, dimensions.

## ERD (text)

```
users ─1───1 farmer_profiles            users ─1───n user_roles (role scoped)
  │  │  └──1──n auth_identities (phone/email, verified_at)
  │  └─────1──n refresh_tokens / sessions
  │        └──1──n otp_challenges (hashed code)
  │
  ├──1──n farms ─1──n crops ─1──n crop_events        (activities, treatments)
  │           └──1──n soil_tests
  ├──1──n posts ─1──n post_media (→ media_assets)
  │        │       └──1──n comments (self-referential parent_id for replies)
  │        │       └──1──n reactions (unique per user+post)
  │        │       └──1──n saved_posts
  │        └──1──n reports (polymorphic target: post|comment|user)
  ├──1──n follows (follower_id, followee_id) unique pair
  ├──1──n notifications ─1──n notification_deliveries
  ├──1──n notification_preferences (1 per user)
  ├──1──n device_tokens
  ├──1──n agent_conversations ─1──n agent_messages
  ├──1──n ai_requests ─1──1 ai_outputs (predictions, assistant answers)
  │           └──1──n ai_feedback
  ├──1──n search_events, product_events (analytics, privacy-light)

knowledge_documents ─1──n knowledge_chunks (embedding vector(384), metadata)
  └── indexing status, source provenance, verification status
posts ─1──1 post_embeddings (vector(384), model/version stamped)

market_crops, markets, market_prices (source-tagged, actual vs estimate)
weather_observations, weather_forecasts, weather_alerts (cache mirror + provenance)
schemes, scheme_documents, scheme_eligibility_rules, scheme_states
moderation_cases ─1──n moderation_actions; audit_logs (actor, action, target)
model_registry_entries, model_evaluations, model_inference_events (monitoring)
background_jobs, ai_jobs
```

## Table groups and key columns

### Identity & access
| Table | Notable columns | Notes |
|---|---|---|
| `users` | `id uuid pk`, `phone_e164 unique null`, `email unique null`, `password_hash null`, `primary_role`, `preferred_language`, `status`, `is_demo`, `last_login_at`, `failed_login_count`, `locked_until` | a user may have phone only, email only, or both |
| `auth_identities` | `user_id fk`, `kind (phone|email)`, `value unique`, `verified_at`, `is_primary` | supports linking two identities to one account |
| `refresh_tokens` | `user_id fk`, `token_hash unique`, `expires_at`, `revoked_at`, `replaced_by_id`, `ip`, `user_agent` | rotation on use; hash only, never the raw token |
| `otp_challenges` | `user_id fk`, `purpose`, `code_hash`, `expires_at`, `consumed_at`, `attempt_count`, `channel`, `ip` | Argon2id hash, `attempt_count` capped, single-use |
| `user_roles` | `user_id fk`, `role enum`, `granted_by_id`, `unique(user_id, role)` | a user can be FARMER and EXPERT |

### Farms & crops
| Table | Notable columns |
|---|---|
| `farms` | `owner_id fk`, `name`, `area_value numeric(12,4)`, `area_unit enum`, `village`, `district`, `state`, `lat`, `lon`, `soil_type enum`, `soil_ph numeric(3,1) CHECK 0..14`, `irrigation_type enum`, `ownership_type enum`, `notes`, soft delete |
| `crops` | `farm_id fk`, `crop_code fk crops_catalog`, `variety`, `sowing_date`, `expected_harvest_date`, `area_value`, `area_unit`, `stage enum`, `irrigation_method`, `notes`, `status` |
| `crop_events` | `crop_id fk`, `event_type`, `event_date`, `notes`, `quantity`, `unit`, `cost`, `created_by_id` |
| `soil_tests` | `farm_id fk`, `tested_on`, `ph`, `n/p/k mg/kg`, `organic_carbon`, `lab_name`, `report_media_id` |
| `crops_catalog` | `code unique`, `name_en/mr/hi`, `season enum`, `category`, `default_area_unit`, `is_demo` |

### Community
| Table | Notable columns |
|---|---|
| `posts` | `author_id fk`, `title`, `body`, `category enum (12 values)`, `crop_code`, `region/district/state`, `farm_id null`, `crop_id null`, `status enum`, `trust_label`, `is_demo`, counters cache: `reaction_count`, `comment_count`, `save_count`, `view_count` |
| `comments` | `post_id fk`, `parent_id fk self null` (1-level replies + nesting allowed), `author_id`, `body`, `status`, `trust_label` |
| `reactions` | `post_id`/`comment_id` (exactly one), `user_id`, `kind enum (support|helpful|insightful)`, unique per (user,target) |
| `saved_posts` | `user_id`, `post_id`, `unique` |
| `follows` | `follower_id`, `followee_id`, `unique`, CHECK `follower_id <> followee_id` |
| `reports` | `reporter_id`, `target_type`, `target_id`, `reason enum`, `details`, `status enum`, `resolved_by_id`, `resolution_note` |
| `post_media` | `post_id`, `media_id` → `media_assets(storage_key, mime, size_bytes, width, height, checksum_sha256, owner_id)` |

### Knowledge, AI, market, weather, schemes
| Table | Notable columns |
|---|---|
| `knowledge_documents` | `title`, `source_name`, `source_url`, `publication_date`, `language`, `doc_type`, `crop_codes[]`, `region`, `verification_status enum (unverified|community_reviewed|expert_reviewed|official)`, `license`, `is_demo` |
| `knowledge_chunks` | `document_id fk`, `chunk_index`, `content`, `token_count`, `embedding vector(384)`, `embedding_model`, `embedding_version`, `tsv tsvector` |
| `post_embeddings` | `post_id pk fk`, `embedding vector(384)`, `embedding_model`, `embedding_version`, `source_text_hash` |
| `schemes` | `slug unique`, `name_en/mr/hi`, `description_*`, `benefits_*`, `eligibility_summary_*`, `documents_required jsonb`, `application_process_*`, `official_source_url`, `official_source_name`, `state_codes[]`, `category`, `last_verified_on date`, `verification_status`, `is_demo` |
| `scheme_eligibility_rules` | `scheme_id fk`, `field`, `operator`, `value jsonb`, `is_hard_requirement`, `note` |
| `markets` / `market_crops` | `name`, `state`, `district`, `code`; crop codes + units |
| `market_prices` | `market_id`, `crop_code`, `price_date`, `min_price`, `max_price`, `modal_price`, `unit`, `source` (`provider` name), `is_estimate bool`, `is_demo bool`, `retrieved_at`; unique `(market, crop, date, source, is_estimate)` |
| `weather_observations` / `weather_forecasts` / `weather_alerts` | `lat`, `lon` (rounded key), `observed_at`/`forecast_for`, payload columns (temp, humidity, rainfall, wind, condition), `provider`, `is_demo`, `retrieved_at`; unique `(lat, lon, time, provider)` |
| `ai_requests` | `user_id`, `kind enum`, `status enum (queued|running|succeeded|failed)`, `input jsonb`, `model_name`, `model_version`, `error_code`, `latency_ms`, `is_demo` |
| `ai_outputs` | `ai_request_id fk`, `output jsonb`, `confidence numeric`, `evidence jsonb`, `disclaimer`, `model_name`, `model_version` |
| `ai_feedback` | `ai_output_id fk`, `user_id`, `verdict enum (helpful|not_helpful|incorrect|report)`, `correction_text`, `ground_truth jsonb`, `consent_to_train bool` |
| `model_registry_entries` | `name`, `version`, `stage enum (staging|production|archived)`, `mlflow_run_id`, `artifact_uri`, `metrics jsonb`, `trained_on`, `training_data_description`, `is_active` |
| `model_inference_events` | `model_name`, `model_version`, `latency_ms`, `outcome`, `input_fingerprint` (hashed, non-reversible), `output_summary jsonb`, `created_at` — power source for drift/latency monitoring |
| `background_jobs` | `kind`, `status`, `payload`, `attempts`, `max_attempts`, `scheduled_at`, `started_at`, `finished_at`, `last_error`, `progress` |
| `product_events` | `user_id null`, `name`, `props jsonb`, `session_id`, `created_at` — no PII in props (enforced by a schema allow-list) |
| `audit_logs` | `actor_id`, `action`, `target_type`, `target_id`, `before jsonb`, `after jsonb`, `ip`, `created_at` |

## Indexes (the ones that matter)

```sql
-- feed & profile
CREATE INDEX ix_posts_status_created       ON posts (status, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX ix_posts_category_created     ON posts (category, created_at DESC);
CREATE INDEX ix_posts_crop_region          ON posts (crop_code, state);
CREATE INDEX ix_comments_post              ON comments (post_id, created_at);
CREATE INDEX ix_reactions_target           ON reactions (post_id, comment_id);
-- semantic search (HNSW; build after bulk ingest in production)
CREATE INDEX ix_knowledge_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
CREATE INDEX ix_post_embeddings_hnsw       ON post_embeddings USING hnsw (embedding vector_cosine_ops);
-- keyword
CREATE INDEX ix_knowledge_chunks_tsv       ON knowledge_chunks USING gin (tsv);
CREATE INDEX ix_posts_title_trgm           ON posts USING gin (title gin_trgm_ops);
-- market
CREATE INDEX ix_market_prices_lookup       ON market_prices (crop_code, market_id, price_date DESC);
-- ops
CREATE INDEX ix_ai_requests_kind_status    ON ai_requests (kind, status, created_at DESC);
CREATE INDEX ix_model_inference_events     ON model_inference_events (model_name, created_at DESC);
CREATE INDEX ix_notifications_user_unread  ON notifications (user_id, read_at) WHERE read_at IS NULL;
```

## Portability note (tests / sqlite)

The schema above targets PostgreSQL. The test suite can run against either:
`TEST_DATABASE_URL` set → PostgreSQL (used by default in CI and in this repo's
verification run), unset → in-memory SQLite with a JSON fallback for the
`vector` column and Python-side cosine similarity. Vector-specific features
(HNSW index, `<=>` operator) are PostgreSQL-only and are skipped in SQLite mode
by a capability flag (`db.capabilities.supports_vector_index`), so a SQLite run
never silently pretends to test them.
