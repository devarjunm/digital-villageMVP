"""Shared pytest fixtures.

Design decisions, in order of importance:

1. **A real PostgreSQL database, not SQLite.** The schema uses pgvector columns,
   JSONB-ish behaviour, `pg_trgm` fuzzy search and check constraints; running the
   tests against SQLite would test a different system than production. A separate
   database (`digital_village_test`, override with TEST_DATABASE_URL) is created
   and migrated once per session with the same Alembic revisions that production
   uses — so the test suite fails if a migration is broken or missing.
2. **Per-test rollback.** Each test runs inside an outer transaction that is
   rolled back afterwards; the app's own `session.commit()` calls become
   savepoint releases (`join_transaction_mode="create_savepoint"`). Tests can
   therefore call endpoints that commit (register, post, upload) without leaking
   data into the next test.
3. **No mocked services.** Only the *database session* is redirected; every
   provider stays the one configured for development (mock weather/market/LLM
   providers), which is exactly what the demo configuration ships with.
4. **Isolated cache.** Redis database 15 is used and flushed around the session
   so rate-limit counters and cached weather cannot make tests order-dependent.
   If Redis is unavailable the app's in-memory fallback is used and a notice is
   printed — the suite still runs.
"""

from __future__ import annotations

import contextlib
import os
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Environment must be configured *before* app.core.config is imported anywhere.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://dv:dv_password@localhost:5432/digital_village_test"
)
os.environ.setdefault("TEST_DATABASE_URL", os.environ["DATABASE_URL"])
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-used-anywhere-else-0123456789")
os.environ.setdefault("STORAGE_LOCAL_DIR", str(REPO_ROOT / "data" / "uploads-test"))
os.environ.setdefault("ML_MODELS_DIR", str(REPO_ROOT / "artifacts" / "models"))
os.environ.setdefault("ALLOW_PROD_SEED", "0")

# The repository root holds `ai/` and `genai/`, which the API imports at runtime;
# pytest's `pythonpath` setting normally covers this, but conftest must not depend
# on the caller's invocation style (e.g. `pytest path/to/file.py` from elsewhere).
for _path in (str(BACKEND_ROOT), str(REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.enums import Role, UserStatus  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.database.session import get_db  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "postgres_only: requires a PostgreSQL database with pgvector"
    )


# ---------------------------------------------------------------- database setup
def _admin_connection_url() -> str:
    """A connection string for the `postgres` maintenance database.

    `str(URL)` masks the password (``***``), which would produce a valid-looking
    URL that always fails authentication — render the password explicitly.
    """
    url = sa.engine.make_url(settings.database_url)
    return url.set(database="postgres").render_as_string(hide_password=False)


def _target_database() -> str:
    return sa.engine.make_url(settings.database_url).database or "digital_village_test"


def _database_exists() -> bool:
    try:
        engine = sa.create_engine(_admin_connection_url(), isolation_level="AUTOCOMMIT")
    except Exception:
        return False
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    sa.text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": _target_database()},
                ).scalar()
            )
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def postgres_available() -> bool:
    try:
        engine = sa.create_engine(_admin_connection_url(), isolation_level="AUTOCOMMIT")
    except Exception:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _ensure_extensions() -> None:
    """Make sure `vector` and `pg_trgm` exist in the test database.

    On a developer machine the application role is usually *not* a superuser, so
    extension creation goes through the postgres superuser when we can reach it
    (this is the same step `scripts/dev_bootstrap.sh` performs for the dev
    database). Inside docker-compose the application role *is* the cluster
    superuser, in which case the direct path succeeds and the sudo path is never
    used. If neither works the tests skip with an actionable message rather than
    failing on a privilege error nobody can read.
    """
    import shutil
    import subprocess

    engine = sa.create_engine(_admin_connection_url(), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for extension in ("vector", "pg_trgm"):
                try:
                    conn.execute(sa.text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
                except sa.exc.ProgrammingError:
                    raise _NeedsSuperuser(extension) from None
        return
    except _NeedsSuperuser as needs:
        if shutil.which("sudo") is None:
            pytest.skip(f"extension {needs.extension} is missing and this role cannot create it")
        result = subprocess.run(
            [
                "sudo",
                "-u",
                "postgres",
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                _target_database(),
                "-c",
                "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(
                "could not create the vector/pg_trgm extensions in the test database: "
                + (result.stderr or result.stdout or "").strip()[:200]
            )
    finally:
        engine.dispose()


class _NeedsSuperuser(Exception):
    def __init__(self, extension: str) -> None:
        super().__init__(extension)
        self.extension = extension


@pytest.fixture(scope="session")
def test_database(postgres_available: bool) -> Iterator[str]:
    """Create the test database if needed and migrate it to head."""
    if not postgres_available:
        pytest.skip("PostgreSQL is not reachable; start it with scripts/dev_bootstrap.sh")

    if not _database_exists():
        engine = sa.create_engine(_admin_connection_url(), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{_target_database()}"'))
        engine.dispose()

    # Extensions must exist before the first migration (it creates vector columns).
    _ensure_extensions()

    # Migrate with Alembic so the test schema is the schema production gets.
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")

    yield settings.database_url


@pytest.fixture(scope="session")
def engine(test_database: str) -> Iterator[sa.Engine]:
    eng = sa.create_engine(test_database, poolclass=sa.pool.NullPool)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def _flush_test_cache() -> Iterator[None]:
    """Keep the cache out of the way: flush Redis db 15 before and after the run."""
    cache = None
    try:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(settings.redis_url)
        client.ping()
        client.flushdb()
        cache = client
    except Exception:
        try:
            from app.core.cache import get_cache

            get_cache().flush_prefix("dv:")
        except Exception:
            pass
    yield
    if cache is not None:
        with contextlib.suppress(Exception):
            cache.flushdb()


@pytest.fixture(scope="session")
def reference_data(test_database: str) -> None:
    """Load the production reference data (crop catalog) into the test database once.

    Reference data is not demo data: the application cannot function without it
    (a crop cannot be created for a code that is not in the catalog), so the test
    database gets it exactly the way a production database does — by running the
    same loader script.
    """
    import sys as _sys

    scripts_dir = str(REPO_ROOT / "scripts")
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    from load_reference_data import load

    from app.database.session import get_session_factory

    with get_session_factory()() as session:
        load(session)


@pytest.fixture
def db(engine: sa.Engine, reference_data: None) -> Iterator[Session]:
    """A session whose writes are rolled back after the test."""
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    """TestClient whose requests share the test's transaction."""
    from app.main import app

    def _override() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = _override
    # Rate limits are keyed per user/IP; the suite reuses the same test client IP,
    # so raise the ceilings rather than weakening the production defaults.
    previous = settings.rate_limit_enabled
    settings.rate_limit_enabled = False
    with TestClient(app) as test_client:
        yield test_client
    settings.rate_limit_enabled = previous
    app.dependency_overrides.pop(get_db, None)


# ------------------------------------------------------------------ data factories
@dataclass(slots=True)
class TestAccount:
    user_id: uuid.UUID
    phone: str
    email: str
    password: str
    role: Role
    headers: dict[str, str]


@pytest.fixture
def account_factory(db: Session):
    """Create a real user row (with profile, role and a valid access token)."""
    from app.farmers.models import FarmerProfile
    from app.users.models import User, UserRole

    counter = {"n": 0}

    def _create(
        *,
        role: Role = Role.FARMER,
        password: str = "TestPass!234",
        status: UserStatus = UserStatus.ACTIVE,
        full_name: str = "Test User",
        district: str = "Nashik",
        state: str = "Maharashtra",
        phone: str | None = None,
        email: str | None = None,
    ) -> TestAccount:
        counter["n"] += 1
        n = counter["n"]
        phone = phone or f"+9190001{n:05d}"
        email = email or f"test{n}.{uuid.uuid4().hex[:6]}@example.com"
        user = User(
            phone_e164=phone,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            primary_role=role,
            status=status,
            phone_verified_at=sa.func.now() if status == UserStatus.ACTIVE else None,
            email_verified_at=sa.func.now()
            if role in {Role.MODERATOR, Role.ADMIN, Role.EXPERT}
            else None,
            is_demo=True,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role=role, granted_by_id=None))
        db.add(
            FarmerProfile(
                user_id=user.id,
                display_name=full_name,
                district=district,
                state=state,
                is_public=True,
            )
        )
        db.flush()
        token, _expires = create_access_token(
            user_id=user.id,
            role=role.value,
            roles=[role.value],
            token_version=user.token_version or 0,
        )
        return TestAccount(
            user_id=user.id,
            phone=phone,
            email=email,
            password=password,
            role=role,
            headers={"Authorization": f"Bearer {token}"},
        )

    return _create


@pytest.fixture
def farmer(account_factory) -> TestAccount:
    return account_factory(role=Role.FARMER)


@pytest.fixture
def expert(account_factory) -> TestAccount:
    return account_factory(role=Role.EXPERT, full_name="Test Expert")


@pytest.fixture
def moderator(account_factory) -> TestAccount:
    return account_factory(role=Role.MODERATOR, full_name="Test Moderator")


@pytest.fixture
def admin(account_factory) -> TestAccount:
    return account_factory(role=Role.ADMIN, full_name="Test Admin")


@pytest.fixture
def other_farmer(account_factory) -> TestAccount:
    """A second farmer, used for authorisation tests (cannot edit my rows)."""
    return account_factory(role=Role.FARMER, full_name="Other Farmer")


def grant_consent(db: Session, user_id: uuid.UUID, *kinds: str) -> None:
    """Helper for tests that exercise endpoints gated behind consent."""
    from app.core.enums import ConsentKind, ConsentSource
    from app.users.consent import ConsentService

    service = ConsentService(db)
    for kind in kinds or ("analytics",):
        service.record(
            user_id=user_id,
            kind=ConsentKind(kind),
            granted=True,
            source=ConsentSource.SEED,
            note="test fixture",
        )
