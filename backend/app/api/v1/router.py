"""API v1 router assembly. Every versioned route is mounted here."""

from __future__ import annotations

from fastapi import APIRouter

api_router = APIRouter()


def _include_all() -> None:
    # Each domain router is imported explicitly (importing the package alone does
    # not expose its `router` submodule), so a missing module fails loudly at
    # start-up instead of silently dropping a route group.
    from app.admin.router import router as admin_router
    from app.ai.router import router as ai_router
    from app.auth.router import router as auth_router
    from app.community.router import router as community_router
    from app.crops.router import router as crops_router
    from app.farmers.router import router as farmers_router
    from app.farms.router import router as farms_router
    from app.knowledge.analytics import analytics_router
    from app.knowledge.router import router as knowledge_router
    from app.markets.router import router as markets_router
    from app.media.router import router as media_router
    from app.moderation.router import router as moderation_router
    from app.notifications.router import router as notifications_router
    from app.schemes.router import router as schemes_router
    from app.search.router import router as search_router
    from app.users.router import router as users_router
    from app.weather.router import router as weather_router

    api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
    api_router.include_router(users_router, prefix="/users", tags=["users"])
    api_router.include_router(farmers_router, prefix="/farmers", tags=["farmers"])
    api_router.include_router(farms_router, prefix="/farms", tags=["farms"])
    api_router.include_router(crops_router, prefix="/crops", tags=["crops"])
    api_router.include_router(media_router, prefix="/media", tags=["media"])
    api_router.include_router(community_router, prefix="/community", tags=["community"])
    api_router.include_router(moderation_router, prefix="/moderation", tags=["moderation"])
    api_router.include_router(weather_router, prefix="/weather", tags=["weather"])
    api_router.include_router(markets_router, prefix="/markets", tags=["markets"])
    api_router.include_router(schemes_router, prefix="/schemes", tags=["schemes"])
    api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
    api_router.include_router(search_router, prefix="/search", tags=["search"])
    api_router.include_router(ai_router, prefix="/ai", tags=["ai"])
    api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
    api_router.include_router(admin_router, prefix="/admin", tags=["admin"])
    api_router.include_router(analytics_router, prefix="/analytics", tags=["analytics"])


_include_all()
