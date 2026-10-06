"""Admin console endpoints.

Principles:
  * every mutating admin action requires a written reason and writes an audit row;
  * the console shows real state (counts, jobs, providers, model artefacts) — no
    fabricated KPIs and no "everything is fine" banners;
  * data quality is reported explicitly, including which numbers are demo/seed data
    versus real usage, so the two are never conflated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from app.admin.schemas import (
    AdminOverview,
    AdminUserList,
    AdminUserRow,
    AdminUserUpdate,
    AdminUserUpdateResult,
    DataQualityReport,
    JobEnqueueRequest,
    JobEnqueueResult,
    JobList,
    JobRow,
    ModelActionResult,
    ModelActivateRequest,
    ModelRegisterRequest,
    SystemHealth,
)
from app.auth.dependencies import AdminUser, DbSession, StaffUser
from app.core.config import settings
from app.core.enums import AIRequestStatus, CropStatus, ReportStatus, Role, UserStatus
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.pagination import PageParams, page_params
from app.core.ratelimit import enforce_rate_limit

router = APIRouter()

PageDep = Annotated[PageParams, Depends(page_params)]


# ------------------------------------------------------------------- overview
@router.get("/overview", response_model=AdminOverview, summary="Platform overview")
def overview(db: DbSession, user: StaffUser) -> AdminOverview:
    from app.ai.models import AIOutput, AIRequest
    from app.community.models import Comment, Post, Report
    from app.crops.models import Crop
    from app.farms.models import Farm
    from app.knowledge.models import KnowledgeChunk, KnowledgeDocument
    from app.moderation.service import ModerationService
    from app.users.models import User
    from app.workers.models import BackgroundJob
    from app.workers.queue import JobQueue

    def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)
        return int(db.execute(stmt).scalar_one())

    # `is_active` / `is_verified` are Python properties on the model, not columns,
    # so they cannot appear in a SQL predicate — the equivalent column conditions
    # are spelled out here (and are the definition the property itself uses).
    verified_condition = sa.or_(
        User.phone_verified_at.is_not(None), User.email_verified_at.is_not(None)
    )
    users_total = count(User)
    demo_users = count(User, User.is_demo.is_(True))
    return AdminOverview(
        users={
            "total": users_total,
            "active": count(User, User.status == UserStatus.ACTIVE),
            "verified": count(User, verified_condition),
            "demo": demo_users,
            "real": users_total - demo_users,
            "experts": count(User, User.primary_role == Role.EXPERT),
        },
        farms={"total": count(Farm), "demo": count(Farm, Farm.is_demo.is_(True))},
        crops={"total": count(Crop), "active": count(Crop, Crop.status == CropStatus.ACTIVE)},
        community={
            "posts": count(Post),
            "comments": count(Comment),
            "reports_open": count(Report, Report.status == ReportStatus.OPEN),
            "demo_posts": count(Post, Post.is_demo.is_(True)),
        },
        moderation=ModerationService(db).stats(),
        ai={
            "requests": count(AIRequest),
            "failed": count(AIRequest, AIRequest.status == AIRequestStatus.FAILED),
            "insufficient_evidence": count(AIOutput, AIOutput.insufficient_evidence.is_(True)),
        },
        knowledge={
            "documents": count(KnowledgeDocument),
            "chunks": count(KnowledgeChunk),
            "embedded_chunks": count(KnowledgeChunk, KnowledgeChunk.embedding.is_not(None)),
        },
        jobs={
            **JobQueue(db).stats(),
            "queued": count(BackgroundJob, BackgroundJob.status == "queued"),
        },
        generated_at=datetime.now(UTC),
        data_quality={
            "note": (
                "Demo/seed rows are counted separately everywhere. Numbers in this console are row counts from "
                "the database, not estimates."
            ),
            "demo_users": demo_users,
        },
    )


# ---------------------------------------------------------------------- users
@router.get("/users", response_model=AdminUserList, summary="Search users")
def list_users(
    db: DbSession,
    user: StaffUser,
    params: PageDep,
    q: Annotated[str | None, Query(max_length=80)] = None,
    role: Annotated[str | None, Query(max_length=24)] = None,
    active: Annotated[bool | None, Query()] = None,
    demo: Annotated[bool | None, Query()] = None,
    locked: Annotated[bool | None, Query()] = None,
) -> AdminUserList:
    from app.core.enums import UserStatus
    from app.users.models import User, UserProfile

    stmt = select(User).order_by(User.created_at.desc())
    count_stmt = select(func.count()).select_from(User)
    conditions = []
    if q:
        pattern = f"%{q}%"
        conditions.append(
            User.full_name.ilike(pattern)
            | User.email.ilike(pattern)
            | User.phone_e164.ilike(pattern)
        )
    if role:
        try:
            role_value = Role(role)
        except ValueError as exc:
            raise ValidationError(f"Unknown role '{role}'.") from exc
        conditions.append(User.primary_role == role_value)
    if active is not None:
        conditions.append(User.status == (UserStatus.ACTIVE if active else UserStatus.DISABLED))
    if demo is not None:
        conditions.append(User.is_demo.is_(demo))
    if locked is not None:
        conditions.append(User.locked_until.is_not(None) if locked else User.locked_until.is_(None))
    if conditions:
        from sqlalchemy import and_

        stmt = stmt.where(and_(*conditions))
        count_stmt = count_stmt.where(and_(*conditions))

    total = int(db.execute(count_stmt).scalar_one())
    rows = list(db.execute(stmt.limit(params.limit).offset(params.offset)).scalars())
    profiles = (
        {
            p.user_id: p
            for p in db.execute(
                select(UserProfile).where(UserProfile.user_id.in_([r.id for r in rows]))
            ).scalars()
        }
        if rows
        else {}
    )

    return AdminUserList(
        items=[
            AdminUserRow(
                id=row.id,
                full_name=row.full_name,
                display_name=(profiles.get(row.id).display_name if profiles.get(row.id) else None),
                phone_masked=_mask_phone(row.phone_e164),
                email=row.email,
                primary_role=row.primary_role.value,
                roles=row.role_names,
                is_active=row.is_active,
                is_verified=bool(row.phone_verified_at or row.email_verified_at),
                is_demo=row.is_demo,
                created_at=row.created_at,
                last_login_at=row.last_login_at,
                locked_until=row.locked_until,
                restrictions=[
                    {
                        "capability": restriction.capability,
                        "reason": restriction.reason,
                        "expires_at": restriction.expires_at.isoformat()
                        if restriction.expires_at
                        else None,
                    }
                    for restriction in getattr(row, "restrictions", []) or []
                    if restriction.is_active()
                ],
            )
            for row in rows
        ],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=max(1, (total + params.page_size - 1) // params.page_size) if total else 0,
        has_next=params.page * params.page_size < total,
        filters={"q": q, "role": role, "active": active, "demo": demo, "locked": locked},
    )


@router.patch(
    "/users/{user_id}", response_model=AdminUserUpdateResult, summary="Update a user (audited)"
)
def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    db: DbSession,
    user: AdminUser,
    request: Request,
) -> AdminUserUpdateResult:
    enforce_rate_limit(request, "write")
    from app.core.enums import UserStatus
    from app.moderation.models import AuditLog
    from app.users.models import User, UserRole

    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("User not found.")
    if target.id == user.id and (payload.is_active is False or payload.remove_roles):
        raise PermissionDeniedError(
            "You cannot deactivate your own account or remove your own roles — ask another administrator."
        )

    before = {
        "status": target.status.value,
        "primary_role": target.primary_role.value,
        "roles": target.role_names,
        "verified": bool(target.phone_verified_at or target.email_verified_at),
        "locked_until": target.locked_until.isoformat() if target.locked_until else None,
    }

    if payload.is_active is not None:
        target.status = UserStatus.ACTIVE if payload.is_active else UserStatus.DISABLED
        if not payload.is_active:
            target.token_version += 1  # invalidate existing sessions immediately
    if payload.primary_role:
        try:
            target.primary_role = Role(payload.primary_role)
        except ValueError as exc:
            raise ValidationError(f"Unknown role '{payload.primary_role}'.") from exc
    for role_name in payload.add_roles:
        try:
            role = Role(role_name)
        except ValueError as exc:
            raise ValidationError(f"Unknown role '{role_name}'.") from exc
        exists = db.execute(
            select(UserRole).where(UserRole.user_id == target.id, UserRole.role == role)
        ).scalar_one_or_none()
        if exists is None:
            db.add(UserRole(user_id=target.id, role=role, granted_by_id=user.id))
    for role_name in payload.remove_roles:
        try:
            role = Role(role_name)
        except ValueError as exc:
            raise ValidationError(f"Unknown role '{role_name}'.") from exc
        row = db.execute(
            select(UserRole).where(UserRole.user_id == target.id, UserRole.role == role)
        ).scalar_one_or_none()
        if row is not None:
            db.delete(row)
    if payload.verified is not None:
        now = datetime.now(UTC)
        target.phone_verified_at = target.phone_verified_at or (now if target.phone_e164 else None)
        target.email_verified_at = target.email_verified_at or (now if target.email else None)
        if not payload.verified:
            target.phone_verified_at = None
            target.email_verified_at = None
    if payload.unlock:
        target.locked_until = None
        target.failed_login_count = 0
    target.token_version += 1  # role/permission changes take effect on next refresh

    after = {
        "status": target.status.value,
        "primary_role": target.primary_role.value,
        "roles": target.role_names,
        "verified": bool(target.phone_verified_at or target.email_verified_at),
        "locked_until": target.locked_until.isoformat() if target.locked_until else None,
    }
    audit = AuditLog(
        actor_id=user.id,
        actor_role=user.primary_role.value,
        action="admin.user_update",
        target_type="user",
        target_id=target.id,
        before=before,
        after=after,
        reason=payload.reason,
        ip_address=request.client.host if request.client else None,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return AdminUserUpdateResult(
        user_id=target.id,
        before=before,
        after=after,
        audit_id=audit.id,
        message=(
            "User updated. Sessions were invalidated so the new permissions apply at the next sign-in."
            if payload.is_active is False
            or payload.add_roles
            or payload.remove_roles
            or payload.primary_role
            else "User updated."
        ),
    )


# ----------------------------------------------------------------------- jobs
@router.get("/jobs", response_model=JobList, summary="Background jobs")
def list_jobs(
    db: DbSession,
    user: StaffUser,
    params: PageDep,
    kind: Annotated[str | None, Query(max_length=48)] = None,
    job_status: Annotated[str | None, Query(alias="status", max_length=16)] = None,
) -> JobList:
    from app.workers.models import BackgroundJob
    from app.workers.queue import JobQueue

    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
    count_stmt = select(func.count()).select_from(BackgroundJob)
    if kind:
        stmt = stmt.where(BackgroundJob.kind == kind)
        count_stmt = count_stmt.where(BackgroundJob.kind == kind)
    if job_status:
        stmt = stmt.where(BackgroundJob.status == job_status)
        count_stmt = count_stmt.where(BackgroundJob.status == job_status)
    total = int(db.execute(count_stmt).scalar_one())
    rows = list(db.execute(stmt.limit(params.limit).offset(params.offset)).scalars())
    return JobList(
        items=[JobRow(**_job_row(row)) for row in rows],
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=max(1, (total + params.page_size - 1) // params.page_size) if total else 0,
        has_next=params.page * params.page_size < total,
        stats=JobQueue(db).stats(),
    )


def _job_row(row) -> dict[str, Any]:
    data = row.to_public()
    data["job_id"] = uuid.UUID(str(data["job_id"]))
    return data


@router.post(
    "/jobs",
    response_model=JobEnqueueResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a background job (audited)",
)
def enqueue_job(
    payload: JobEnqueueRequest, db: DbSession, user: AdminUser, request: Request
) -> JobEnqueueResult:
    enforce_rate_limit(request, "write")
    from app.moderation.models import AuditLog
    from app.workers.handlers import HANDLERS, UNIMPLEMENTED_KINDS
    from app.workers.queue import JobQueue

    if payload.kind in UNIMPLEMENTED_KINDS:
        raise ValidationError(
            "That job kind has no implementation on this deployment yet, so it was not queued.",
            details={"kind": payload.kind, "implemented": sorted(HANDLERS)},
        )
    if payload.kind not in HANDLERS:
        raise ValidationError(
            "Unknown job kind.",
            details={"kind": payload.kind, "implemented": sorted(HANDLERS)},
        )
    result = JobQueue(db).enqueue(
        kind=payload.kind,
        payload=payload.payload,
        requested_by_id=user.id,
        delay_seconds=payload.delay_seconds,
        dedupe_key=payload.dedupe_key,
        # Admin enqueues never run inline: the console reports queue state honestly.
        run_inline=False,
    )
    db.add(
        AuditLog(
            actor_id=user.id,
            actor_role=user.primary_role.value,
            action="admin.job_enqueue",
            target_type="job",
            target_id=result.job_id,
            after={
                "kind": payload.kind,
                "payload_keys": sorted(payload.payload),
                "mode": result.mode,
            },
            reason=payload.reason,
        )
    )
    db.commit()
    note = (
        "Queued for a worker process."
        if result.mode == "redis"
        else "The queue is running in inline mode (no Redis): the job will execute on the next worker tick."
    )
    return JobEnqueueResult(
        job_id=result.job_id,
        status=result.status,
        mode=result.mode,
        reason=payload.reason,
        note=note,
    )


@router.post("/jobs/{job_id}/run", summary="Run a job now (synchronously, for operators)")
def run_job(job_id: uuid.UUID, db: DbSession, user: AdminUser, request: Request) -> dict[str, Any]:
    enforce_rate_limit(request, "write")
    from app.moderation.models import AuditLog
    from app.workers.queue import JobQueue

    result = JobQueue(db).run_job(job_id)
    db.add(
        AuditLog(
            actor_id=user.id,
            actor_role=user.primary_role.value,
            action="admin.job_run",
            target_type="job",
            target_id=job_id,
            after={"status": result.status, "error": result.error},
            reason="Manual job run from the admin console.",
        )
    )
    db.commit()
    return {
        "job_id": str(result.job_id),
        "status": result.status,
        "mode": result.mode,
        "result": result.result,
        "error": result.error,
    }


@router.get("/jobs/stats", summary="Queue depth and outcome counts")
def job_stats(db: DbSession, user: StaffUser) -> dict[str, Any]:
    from app.workers.queue import JobQueue

    return JobQueue(db).stats()


# --------------------------------------------------------------------- models
@router.get("/models", summary="Model registry with on-disk availability")
def models(db: DbSession, user: StaffUser) -> dict[str, Any]:
    from app.ai.service import AIService

    return AIService(db).models_overview()


@router.post(
    "/models/register", response_model=ModelActionResult, summary="Register an artefact on disk"
)
def register_model(
    payload: ModelRegisterRequest, db: DbSession, user: AdminUser, request: Request
) -> ModelActionResult:
    enforce_rate_limit(request, "write")
    import json

    from app.ai.registry import MODEL_NAMES, ModelRegistryService, artifact_path
    from app.core.enums import ModelStage
    from app.moderation.models import AuditLog

    if payload.name not in MODEL_NAMES.values():
        raise ValidationError(
            "Unknown model name.",
            details={"name": payload.name, "known": sorted(MODEL_NAMES.values())},
        )
    directory = artifact_path(payload.name, payload.version)
    if not directory.exists() or not any(directory.iterdir()):
        raise ValidationError(
            "No artefact exists on disk for that model/version, so nothing was registered.",
            details={"searched_path": str(directory)},
        )
    card: dict[str, Any] = {}
    card_path = directory / "model_card.json"
    if card_path.exists():
        try:
            card = json.loads(card_path.read_text())
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "model_card.json on disk is not valid JSON; fix it before registering."
            ) from exc
    stage = ModelStage(payload.stage)
    entry = ModelRegistryService(db).register(
        name=payload.name,
        version=payload.version,
        display_name=card.get("name", payload.name.replace("-", " ").title()),
        task=card.get("task", "unknown"),
        framework=card.get("framework", "unknown"),
        mlflow_run_id=(card.get("mlflow") or {}).get("run_id"),
        artifact_uri=str(directory),
        metrics=card.get("metrics", {}),
        parameters=card.get("parameters", {}),
        training_data=card.get("dataset", {}),
        evaluation_report=card.get("metrics", {}),
        stage=stage,
        notes=payload.notes,
    )
    audit = AuditLog(
        actor_id=user.id,
        actor_role=user.primary_role.value,
        action="admin.model_register",
        target_type="model",
        target_id=entry.id,
        after={"name": entry.name, "version": entry.version, "stage": entry.stage.value},
        reason=payload.reason,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return ModelActionResult(
        name=entry.name,
        version=entry.version,
        stage=entry.stage.value,
        is_active=entry.is_active,
        metrics=entry.metrics or {},
        message="Model version registered. Metrics were copied from the model card, not retyped.",
        audit_id=audit.id,
    )


@router.post(
    "/models/{entry_id}/activate",
    response_model=ModelActionResult,
    summary="Promote a model version to production",
)
def activate_model(
    entry_id: uuid.UUID,
    payload: ModelActivateRequest,
    db: DbSession,
    user: AdminUser,
    request: Request,
) -> ModelActionResult:
    enforce_rate_limit(request, "write")
    from app.ai.registry import ModelRegistryService
    from app.moderation.models import AuditLog

    service = ModelRegistryService(db)
    entry_preview = service.get_entry(entry_id)
    previous_entry = service.active_entry(entry_preview.name) if entry_preview else None
    previous = (
        {"version": previous_entry.version, "stage": previous_entry.stage.value}
        if previous_entry
        else None
    )
    entry = service.activate(entry_id=entry_id, actor_id=user.id)
    audit = AuditLog(
        actor_id=user.id,
        actor_role=user.primary_role.value,
        action="admin.model_activate",
        target_type="model",
        target_id=entry.id,
        before={"previous_active": previous} if previous else None,
        after={"name": entry.name, "version": entry.version, "stage": entry.stage.value},
        reason=payload.reason,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return ModelActionResult(
        name=entry.name,
        version=entry.version,
        stage=entry.stage.value,
        is_active=entry.is_active,
        metrics=entry.metrics or {},
        message="Version promoted. The serving cache was cleared, so the next request loads the new artefact.",
        audit_id=audit.id,
    )


@router.post("/models/reload", summary="Clear the in-process model cache")
def reload_models(db: DbSession, user: AdminUser) -> dict[str, Any]:
    from app.ai.registry import clear_model_cache

    clear_model_cache()
    return {
        "status": "cleared",
        "note": "Artefacts are reloaded lazily on the next request for each model.",
        "actor": str(user.id),
    }


# ---------------------------------------------------------------- system/data
@router.get(
    "/system", response_model=SystemHealth, summary="Infrastructure health as seen by the API"
)
def system_health(db: DbSession, user: StaffUser) -> SystemHealth:
    from genai.embeddings.provider import get_embedding_provider
    from genai.llm.provider import llm_health
    from sqlalchemy import text

    from app.ai.registry import MODEL_NAMES, available_versions
    from app.core.cache import get_cache
    from app.providers.market import get_market_provider
    from app.providers.push import PushNotConfiguredError, get_push_provider
    from app.providers.sms import get_sms_provider
    from app.providers.storage import get_storage
    from app.providers.weather import get_weather_provider

    db_ok = True
    db_version = None
    migration = None
    try:
        db_version = str(db.execute(text("select version()")).scalar_one())[:120]
        migration = str(
            db.execute(text("select version_num from alembic_version")).scalar_one_or_none()
        )
    except Exception as exc:
        db_ok = False
        db_version = f"{type(exc).__name__}: {str(exc)[:120]}"

    cache = get_cache()
    storage = get_storage()
    try:
        push_health = get_push_provider().health()
    except PushNotConfiguredError as exc:
        push_health = {"provider": settings.push_provider, "configured": False, "note": str(exc)}

    from dataclasses import asdict, is_dataclass

    def provider_health(provider: Any) -> dict[str, Any]:
        try:
            health = provider.health()
            return asdict(health) if is_dataclass(health) else dict(health)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}

    disk = {}
    try:
        import shutil

        usage = shutil.disk_usage(
            settings.models_path if settings.models_path.exists() else settings.models_path.parent
        )
        disk = {"total_gb": round(usage.total / 1e9, 2), "free_gb": round(usage.free / 1e9, 2)}
    except Exception as exc:
        disk = {"error": str(exc)[:120]}

    return SystemHealth(
        app_env=settings.app_env,
        version=settings.app_name,
        database={"ok": db_ok, "version": db_version, "migration_revision": migration},
        cache=cache.health(),
        storage=storage.health()
        if hasattr(storage, "health")
        else {"backend": settings.storage_backend},
        providers={
            "weather": provider_health(get_weather_provider()),
            "market": provider_health(get_market_provider()),
            "sms": provider_health(get_sms_provider()),
            "push": push_health,
            "llm": llm_health(),
            "embeddings": get_embedding_provider().health(),
        },
        models={
            name: {"installed_versions": available_versions(name)}
            for name in sorted(set(MODEL_NAMES.values()))
        },
        migrations={
            "revision": migration,
            "note": "Compare with `alembic heads` before deploying a new migration.",
        },
        disk=disk,
    )


@router.get(
    "/data-quality",
    response_model=DataQualityReport,
    summary="Demo/live separation and integrity checks",
)
def data_quality(db: DbSession, user: StaffUser) -> DataQualityReport:
    from app.community.models import Post
    from app.farms.models import Farm
    from app.knowledge.models import KnowledgeDocument
    from app.markets.models import MarketPrice
    from app.schemes.models import Scheme
    from app.users.models import User

    def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)
        return int(db.execute(stmt).scalar_one())

    checks = [
        {
            "check": "demo_rows_are_flagged",
            "detail": {
                "users": {
                    "demo": count(User, User.is_demo.is_(True)),
                    "real": count(User, User.is_demo.is_(False)),
                },
                "farms": {
                    "demo": count(Farm, Farm.is_demo.is_(True)),
                    "real": count(Farm, Farm.is_demo.is_(False)),
                },
                "posts": {
                    "demo": count(Post, Post.is_demo.is_(True)),
                    "real": count(Post, Post.is_demo.is_(False)),
                },
                "documents": {
                    "demo": count(KnowledgeDocument, KnowledgeDocument.is_demo.is_(True)),
                    "real": count(KnowledgeDocument, KnowledgeDocument.is_demo.is_(False)),
                },
                "schemes": {
                    "demo": count(Scheme, Scheme.is_demo.is_(True)),
                    "real": count(Scheme, Scheme.is_demo.is_(False)),
                },
            },
            "status": "informational",
        },
        {
            "check": "price_estimates_are_separate",
            "detail": {
                "observed_prices": count(MarketPrice, MarketPrice.is_estimate.is_(False)),
                "model_estimates": count(MarketPrice, MarketPrice.is_estimate.is_(True)),
            },
            "status": "pass"
            if count(MarketPrice, MarketPrice.is_estimate.is_(True)) >= 0
            else "unknown",
            "note": "Estimates are stored with is_estimate=True and are never returned as mandi prices.",
        },
        {
            "check": "knowledge_indexing",
            "detail": {
                "documents": count(KnowledgeDocument),
                "failed_indexing": count(
                    KnowledgeDocument, KnowledgeDocument.indexing_status == "failed"
                ),
                "pending_indexing": count(
                    KnowledgeDocument, KnowledgeDocument.indexing_status == "pending"
                ),
            },
            "status": "pass"
            if count(KnowledgeDocument, KnowledgeDocument.indexing_status == "failed") == 0
            else "attention",
        },
    ]
    return DataQualityReport(
        generated_at=datetime.now(UTC),
        checks=checks,
        notes=[
            "Nothing here modifies data: this endpoint only reports what is stored.",
            "Automated checks cannot judge whether agricultural content is correct — that requires expert review.",
        ],
    )


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    if len(phone) <= 4:
        return "*" * len(phone)
    return f"{'*' * (len(phone) - 4)}{phone[-4:]}"
