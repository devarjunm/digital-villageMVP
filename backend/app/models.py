"""Aggregate model import map.

Alembic, the test fixtures and the seed script import this module to guarantee
that every mapped class is registered on `Base.metadata`. Domain packages keep
their own `models.py` so that a feature's tables live next to its service; this
file is the single place that knows the full set.
"""

from __future__ import annotations

from app.ai.models import (
    AgentConversation,
    AgentMessage,
    AIFeedback,
    AIOutput,
    AIRequest,
    ModelEvaluation,
    ModelInferenceEvent,
    ModelRegistryEntry,
    Prediction,
)
from app.analytics.models import ProductEvent, SearchEvent
from app.community.models import (
    Comment,
    Follow,
    Post,
    PostEmbedding,
    PostMedia,
    Reaction,
    Report,
    SavedPost,
)
from app.crops.models import Crop, CropCatalog, CropEvent
from app.farmers.models import FarmerProfile
from app.farms.models import Farm, SoilTest
from app.knowledge.models import KnowledgeChunk, KnowledgeDocument
from app.markets.models import Market, MarketCrop, MarketPrice
from app.media.models import MediaAsset
from app.moderation.models import (
    AuditLog,
    ModerationAction,
    ModerationCase,
    UserRestriction,
)
from app.notifications.models import Notification, NotificationPreference
from app.schemes.models import Scheme, SchemeEligibilityRule
from app.users.models import (
    AuthIdentity,
    DeviceToken,
    OTPChallenge,
    RefreshToken,
    User,
    UserRole,
)
from app.weather.models import WeatherAlert, WeatherForecast, WeatherObservation
from app.workers.models import BackgroundJob

__all__ = [
    "AIFeedback",
    "AIOutput",
    "AIRequest",
    "AgentConversation",
    "AgentMessage",
    "AuditLog",
    "AuthIdentity",
    "BackgroundJob",
    "Comment",
    "Crop",
    "CropCatalog",
    "CropEvent",
    "DeviceToken",
    "Farm",
    "FarmerProfile",
    "Follow",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Market",
    "MarketCrop",
    "MarketPrice",
    "MediaAsset",
    "ModelEvaluation",
    "ModelInferenceEvent",
    "ModelRegistryEntry",
    "ModerationAction",
    "ModerationCase",
    "Notification",
    "NotificationPreference",
    "OTPChallenge",
    "Post",
    "PostEmbedding",
    "PostMedia",
    "Prediction",
    "ProductEvent",
    "Reaction",
    "RefreshToken",
    "Report",
    "SavedPost",
    "Scheme",
    "SchemeEligibilityRule",
    "SearchEvent",
    "SoilTest",
    "User",
    "UserRestriction",
    "UserRole",
    "WeatherAlert",
    "WeatherForecast",
    "WeatherObservation",
]
