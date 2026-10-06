"""Shared enumerations.

All enums are stored as VARCHAR + CHECK (native_enum=False) so migrations stay
portable and adding a value never requires a PostgreSQL type rewrite.
"""

from __future__ import annotations

from enum import StrEnum

import sqlalchemy as sa


def enum_col(enum_cls: type[StrEnum], name: str, length: int = 48) -> sa.Enum:
    """Portable enum column type storing the enum *value* (not its name)."""
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


class Role(StrEnum):
    FARMER = "farmer"
    EXPERT = "expert"
    MODERATOR = "moderator"
    ADMIN = "admin"


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class Language(StrEnum):
    EN = "en"
    MR = "mr"
    HI = "hi"


class AuthIdentityKind(StrEnum):
    PHONE = "phone"
    EMAIL = "email"


class OTPPurpose(StrEnum):
    REGISTER = "register"
    LOGIN = "login"
    PASSWORD_RESET = "password_reset"
    PHONE_VERIFY = "phone_verify"


class AreaUnit(StrEnum):
    ACRE = "acre"
    HECTARE = "hectare"
    GUNTHA = "guntha"
    BIGHa = "bigha"
    SQUARE_METRE = "square_metre"


class SoilType(StrEnum):
    ALLUVIAL = "alluvial"
    BLACK_COTTON = "black_cotton"
    RED = "red"
    LATERITE = "laterite"
    SANDY = "sandy"
    CLAY = "clay"
    LOAMY = "loamy"
    SALINE = "saline"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class IrrigationType(StrEnum):
    RAINFED = "rainfed"
    CANAL = "canal"
    BOREWELL = "borewell"
    OPEN_WELL = "open_well"
    DRIP = "drip"
    SPRINKLER = "sprinkler"
    TANK = "tank"
    OTHER = "other"


class OwnershipType(StrEnum):
    OWNED = "owned"
    LEASED = "leased"
    SHARED = "shared"
    GOVERNMENT_LEASED = "government_leased"


class Season(StrEnum):
    KHARIF = "kharif"
    RABI = "rabi"
    ZAID = "zaid"
    PERENNIAL = "perennial"
    ANY = "any"


class CropStage(StrEnum):
    PLANNED = "planned"
    LAND_PREPARATION = "land_preparation"
    SOWING = "sowing"
    GERMINATION = "germination"
    VEGETATIVE = "vegetative"
    FLOWERING = "flowering"
    FRUITING = "fruiting"
    MATURITY = "maturity"
    HARVEST = "harvest"
    POST_HARVEST = "post_harvest"


class CropStatus(StrEnum):
    ACTIVE = "active"
    HARVESTED = "harvested"
    FAILED = "failed"
    PLANNED = "planned"


class CropEventType(StrEnum):
    SOWING = "sowing"
    IRRIGATION = "irrigation"
    FERTILIZER = "fertilizer"
    PESTICIDE = "pesticide"
    WEEDING = "weeding"
    HARVEST = "harvest"
    OBSERVATION = "observation"
    OTHER = "other"


class PostCategory(StrEnum):
    CROP_PROBLEM = "crop_problem"
    DISEASE = "disease"
    PEST = "pest"
    IRRIGATION = "irrigation"
    SOIL = "soil"
    FERTILIZER = "fertilizer"
    WEATHER = "weather"
    MARKET = "market"
    MACHINERY = "machinery"
    GOVERNMENT_SCHEME = "government_scheme"
    FARMING_TECHNIQUE = "farming_technique"
    GENERAL = "general"


class ContentStatus(StrEnum):
    PUBLISHED = "published"
    UNDER_REVIEW = "under_review"
    HIDDEN = "hidden"
    REMOVED = "removed"


class ReactionKind(StrEnum):
    SUPPORT = "support"
    HELPFUL = "helpful"
    INSIGHTFUL = "insightful"


class ReportTargetType(StrEnum):
    POST = "post"
    COMMENT = "comment"
    USER = "user"


class ReportReason(StrEnum):
    SPAM = "spam"
    ABUSE = "abuse"
    MISINFORMATION = "misinformation"
    OFF_TOPIC = "off_topic"
    DUPLICATE = "duplicate"
    OTHER = "other"


class ReportStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ModerationActionType(StrEnum):
    DISMISS = "dismiss"
    HIDE = "hide"
    REMOVE = "remove"
    WARN_AUTHOR = "warn_author"
    RESTRICT_AUTHOR = "restrict_author"
    NOTE = "note"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    COMMUNITY_REVIEWED = "community_reviewed"
    EXPERT_REVIEWED = "expert_reviewed"
    OFFICIAL = "official"


class NotificationType(StrEnum):
    COMMENT_REPLY = "comment_reply"
    MENTION = "mention"
    POST_IN_FEED = "post_in_feed"
    WEATHER_ALERT = "weather_alert"
    MARKET_UPDATE = "market_update"
    CROP_REMINDER = "crop_reminder"
    SCHEME_UPDATE = "scheme_update"
    AI_JOB_COMPLETE = "ai_job_complete"
    MODERATION_ACTION = "moderation_action"
    SYSTEM = "system"


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    PUSH = "push"


class AIRequestKind(StrEnum):
    DISEASE_DETECTION = "disease_detection"
    CROP_RECOMMENDATION = "crop_recommendation"
    YIELD_PREDICTION = "yield_prediction"
    PRICE_ESTIMATE = "price_estimate"
    RISK_ASSESSMENT = "risk_assessment"
    ASSISTANT_CHAT = "assistant_chat"
    AGENT_RUN = "agent_run"
    EMBEDDING = "embedding"


class AIRequestStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FeedbackVerdict(StrEnum):
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    INCORRECT = "incorrect"
    REPORT = "report"


class ModelStage(StrEnum):
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobKind(StrEnum):
    DISEASE_DETECTION = "disease_detection"
    EMBED_POST = "embed_post"
    EMBED_DOCUMENT = "embed_document"
    INGEST_DOCUMENT = "ingest_document"
    NOTIFICATION_FANOUT = "notification_fanout"
    WEATHER_ALERT_SCAN = "weather_alert_scan"
    MARKET_SYNC = "market_sync"
    CROP_REMINDER_SCAN = "crop_reminder_scan"
    MODEL_EVALUATION = "model_evaluation"
    EMBEDDING_REINDEX = "embedding_reindex"


class DocumentType(StrEnum):
    ARTICLE = "article"
    CROP_GUIDE = "crop_guide"
    DISEASE_INFO = "disease_info"
    GOVERNMENT_INFO = "government_info"
    INSTITUTION_CONTENT = "institution_content"
    RESEARCH_PAPER = "research_paper"
    FAQ = "faq"
    ADVISORY = "advisory"


class PriceSourceKind(StrEnum):
    ACTUAL = "actual"
    ESTIMATE = "estimate"


class SearchMode(StrEnum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class ConsentKind(StrEnum):
    """Purposes the platform asks a user to decide about, individually.

    Consent is per purpose and per policy version: granting analytics does not
    grant permission to train models on the user's content, and a user who
    accepted an older policy version is asked again when the version changes.
    """

    ANALYTICS = "analytics"
    MODEL_TRAINING = "model_training"
    RESEARCH = "research"
    PERSONALISATION = "personalisation"
    MARKETING = "marketing"
    LOCATION = "location"


class ConsentSource(StrEnum):
    """Where a consent decision came from — needed for an audit trail."""

    MOBILE_APP = "mobile_app"
    WEB = "web"
    ADMIN_CONSOLE = "admin_console"
    SUPPORT = "support"
    SEED = "seed"
    IMPORT = "import"
