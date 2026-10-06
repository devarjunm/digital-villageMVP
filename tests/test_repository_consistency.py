"""Repository-level checks: configuration, documentation and deployment wiring.

These are the tests that catch the class of mistake no unit test sees — a key
added to `.env.example` that nothing reads, a compose service without a health
check, a document that tells an operator to run a script that does not exist, or
a secret accidentally committed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Keys that are read by the application but intentionally absent from the example
# file (computed, provider-specific or test-only).
ENV_EXEMPT = {
    "TEST_DATABASE_URL",
    "ALLOW_PROD_SEED",
    "DEMO_USER_PASSWORD",
    "PUSH_CREDENTIALS_FILE",
}


def _example_env_keys() -> set[str]:
    text = (REPO_ROOT / ".env.example").read_text()
    return {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }


def test_env_example_exists_and_declares_no_secrets():
    path = REPO_ROOT / ".env.example"
    assert path.exists(), ".env.example is the documented configuration surface"
    text = path.read_text()
    assert "JWT_SECRET" in text
    # Example values must be obviously fake placeholders.
    for line in text.splitlines():
        if line.startswith("JWT_SECRET="):
            value = line.split("=", 1)[1]
            assert (
                value == "" or "change" in value.lower() or len(value) < 40
            ), "JWT_SECRET in .env.example must be a placeholder, not a usable secret"


def test_every_settings_field_has_a_documented_env_key():
    """`app/core/config.py` is the source of truth; the example file must keep up."""
    config = (REPO_ROOT / "backend" / "app" / "core" / "config.py").read_text()
    fields = set(re.findall(r"^\s{4}([a-z_]+):\s", config, flags=re.MULTILINE))
    # `env_prefix` is set on the settings model, so field names map to upper-case keys.
    documented = {key.lower() for key in _example_env_keys()}
    undocumented = sorted(
        field
        for field in fields
        if field not in documented and field.upper() not in ENV_EXEMPT
    )
    assert (
        not undocumented
    ), f"settings fields missing from .env.example: {undocumented}"


def test_compose_services_have_healthchecks_and_named_volumes():
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    for service in ("postgres", "redis", "api", "worker", "nginx"):
        block = _service_block(text, service)
        assert block, f"service '{service}' is missing from docker-compose.yml"
        if service in {"postgres", "redis", "api"}:
            assert "healthcheck:" in block, f"service '{service}' needs a healthcheck"
    # A named volume for the model directory: artefacts must survive a redeploy.
    assert "models:" in text and "pgdata:" in text


def test_development_compose_starts_the_services_the_api_needs():
    text = (REPO_ROOT / "docker-compose.dev.yml").read_text()
    for service in ("postgres", "redis", "api"):
        assert _service_block(text, service), f"dev compose is missing '{service}'"


def test_deployment_docs_reference_scripts_that_exist():
    doc = (REPO_ROOT / "docs" / "deployment.md").read_text()
    referenced = set(re.findall(r"(scripts/[\w./-]+\.(?:py|sh))", doc))
    referenced |= set(re.findall(r"(mlops/[\w./-]+\.py)", doc))
    missing = sorted(ref for ref in referenced if not (REPO_ROOT / ref).exists())
    assert (
        not missing
    ), f"docs/deployment.md references files that do not exist: {missing}"


def test_deployment_docs_state_the_migration_and_reference_data_order():
    """The loader's own docstring documents the run order; the runbook must match it."""
    doc = (REPO_ROOT / "docs" / "deployment.md").read_text()
    alembic_at = doc.find("alembic upgrade head")
    loader_at = doc.find("load_reference_data.py")
    assert (
        alembic_at != -1 and loader_at != -1
    ), "the run order must appear in the runbook"
    assert alembic_at < loader_at, "migrations must be documented before reference data"


def test_readme_documents_the_required_top_level_components():
    readme = (REPO_ROOT / "README.md").read_text()
    for component in (
        "backend/",
        "ai/",
        "genai/",
        "mlops/",
        "mobile/flutter_app/",
        "infrastructure/",
        "docs/",
        "scripts/",
        "docker-compose.yml",
        ".env.example",
    ):
        assert component in readme, f"README does not mention {component}"


def test_docs_directory_covers_the_required_documents():
    docs = {path.name for path in (REPO_ROOT / "docs").glob("*.md")}
    for required in (
        "architecture.md",
        "database.md",
        "api.md",
        "deployment.md",
        "development.md",
    ):
        assert required in docs, f"docs/{required} is required"


def test_no_committed_secrets_or_real_env_file():
    """Only `.env.example` may be tracked; a real `.env` is a leak."""
    assert not _tracked(".env"), "a real .env file is tracked by git"
    example = (REPO_ROOT / ".env.example").read_text()
    for pattern in (
        r"AKIA[0-9A-Z]{16}",
        r"sk-[A-Za-z0-9]{20,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    ):
        assert not re.search(
            pattern, example
        ), f"a credential-looking value is committed: {pattern}"


def test_demo_seed_refuses_to_run_in_production():
    seed = (REPO_ROOT / "scripts" / "seed_demo.py").read_text()
    assert "production" in seed.lower(), "the seed script must guard against production"
    assert (
        "ALLOW_PROD_SEED" in seed
    ), "the documented override must be checked explicitly"


def test_ci_never_deploys_from_a_pull_request():
    deploy = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    assert (
        "pull_request" not in deploy
    ), "the deploy workflow must not trigger on pull requests"
    assert "workflow_dispatch" in deploy or "push" in deploy
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pytest" in ci and "ruff check" in ci, "CI must run lint and tests"


def test_ci_pins_no_floating_python_and_uses_the_same_version_as_the_image():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    dockerfile = (
        REPO_ROOT / "infrastructure" / "docker" / "backend.Dockerfile"
    ).read_text()
    ci_version = re.search(r'PYTHON_VERSION:\s*"([\d.]+)"', ci)
    assert ci_version, "CI must pin a Python version"
    major_minor = ".".join(ci_version.group(1).split(".")[:2])
    assert (
        f"python:{major_minor}" in dockerfile
        or f"python:{ci_version.group(1)}" in dockerfile
    ), "the image and CI must agree on the Python version"


# ------------------------------------------------------------------ helpers
def _service_block(text: str, service: str) -> str:
    """Return the YAML block for a top-level service in a compose file."""
    pattern = re.compile(
        rf"^  {re.escape(service)}:\n(?P<body>(?:^(?:    .*|\s*)$\n)*)", re.MULTILINE
    )
    match = pattern.search(text)
    return match.group("body") if match else ""


def _tracked(relative: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", relative],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:  # pragma: no cover - git always present in CI
        pytest.skip("git is not available")
    return result.returncode == 0
