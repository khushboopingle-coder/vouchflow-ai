"""
Deployment and Configuration Tests (Phase 6)
============================================
Validates:
1. .env.example defines and documents every setting field in Settings (backend.config).
2. render.yaml exists, parses as valid YAML, and specifies python 3.12, uvicorn on $PORT, /health check.
3. docker-compose.yml exists, parses as valid YAML, and includes api (8000), dashboard (8501), n8n (5678 -> http://api:8000).
4. Dockerfile and .dockerignore exist and ignore secrets/databases.
5. .streamlit/secrets.toml.example exists, parses as valid TOML, and defines expected secrets.
6. backend/startup_check.py correctly distinguishes development warnings from production errors and blocks unsafe starts.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
import yaml
import tomllib

from backend.config import Settings
from backend.startup_check import check_environment, run_startup_check, Problem

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_env_example_covers_all_settings():
    """Every field in Settings must be present in .env.example."""
    env_example_path = ROOT_DIR / ".env.example"
    assert env_example_path.exists(), ".env.example file must exist in repository root"
    
    content = env_example_path.read_text(encoding="utf-8")
    
    # Extract keys defined in .env.example (e.g., KEY=val or # KEY=val)
    found_keys = set()
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading comment marker if line starts with # KEY=
        if line.startswith("#"):
            candidate = line.lstrip("#").strip()
        else:
            candidate = line
        if "=" in candidate:
            key = candidate.split("=", 1)[0].strip()
            if key and key.isupper():
                found_keys.add(key)
                
    settings_keys = set(Settings.model_fields.keys())
    missing_keys = settings_keys - found_keys
    assert not missing_keys, f".env.example is missing the following Settings fields: {missing_keys}"


def test_render_yaml_valid_and_complete():
    """render.yaml must parse as valid YAML with python runtime, build, start commands and health check."""
    render_path = ROOT_DIR / "render.yaml"
    assert render_path.exists(), "render.yaml must exist in repository root"
    
    data = yaml.safe_load(render_path.read_text(encoding="utf-8"))
    assert "services" in data, "render.yaml must define services list"
    assert len(data["services"]) >= 1, "render.yaml must have at least one service defined"
    
    api_service = next((s for s in data["services"] if s.get("name") == "vouchflow-api"), None)
    assert api_service is not None, "render.yaml must have a service named 'vouchflow-api'"
    assert api_service.get("type") == "web"
    assert api_service.get("runtime") == "python"
    assert "pip install -r requirements.txt" in api_service.get("buildCommand", "")
    assert "uvicorn backend.main:app" in api_service.get("startCommand", "")
    assert "$PORT" in api_service.get("startCommand", "")
    assert api_service.get("healthCheckPath") == "/health"
    
    env_vars = {item["key"]: item for item in api_service.get("envVars", [])}
    assert "PYTHON_VERSION" in env_vars
    assert str(env_vars["PYTHON_VERSION"].get("value", "")).startswith("3.12")
    assert "DATABASE_URL" in env_vars
    assert "VOUCHFLOW_SECRET_KEY" in env_vars
    assert "GEMINI_API_KEY" in env_vars
    assert "DASHBOARD_URL" in env_vars


def test_docker_compose_valid_and_complete():
    """docker-compose.yml must parse as valid YAML with api, dashboard, and n8n services."""
    dc_path = ROOT_DIR / "docker-compose.yml"
    assert dc_path.exists(), "docker-compose.yml must exist in repository root"
    
    data = yaml.safe_load(dc_path.read_text(encoding="utf-8"))
    services = data.get("services", {})
    
    assert "api" in services, "docker-compose.yml must define 'api' service"
    assert "dashboard" in services, "docker-compose.yml must define 'dashboard' service"
    assert "n8n" in services, "docker-compose.yml must define 'n8n' service"
    
    # Check port mappings
    api_ports = [str(p) for p in services["api"].get("ports", [])]
    assert any("8000:8000" in p for p in api_ports), "api must expose port 8000"
    
    dash_ports = [str(p) for p in services["dashboard"].get("ports", [])]
    assert any("8501:8501" in p for p in dash_ports), "dashboard must expose port 8501"
    
    n8n_ports = [str(p) for p in services["n8n"].get("ports", [])]
    assert any("5678:5678" in p for p in n8n_ports), "n8n must expose port 5678"
    
    # n8n must point to api service http://api:8000
    n8n_env = services["n8n"].get("environment", {})
    if isinstance(n8n_env, list):
        n8n_env_dict = dict(item.split("=", 1) for item in n8n_env if "=" in item)
    else:
        n8n_env_dict = n8n_env
    assert n8n_env_dict.get("VOUCHFLOW_API_URL") == "http://api:8000", "n8n must communicate with api at http://api:8000"


def test_dockerfile_and_dockerignore():
    """Dockerfile and .dockerignore must exist and configure production containerization."""
    dockerfile = ROOT_DIR / "Dockerfile"
    dockerignore = ROOT_DIR / ".dockerignore"
    
    assert dockerfile.exists(), "Dockerfile must exist"
    assert dockerignore.exists(), ".dockerignore must exist"
    
    df_content = dockerfile.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in df_content or "FROM python:3.12" in df_content
    assert "COPY requirements.txt" in df_content
    assert "pip install" in df_content
    assert "EXPOSE" in df_content and "8000" in df_content
    
    di_content = dockerignore.read_text(encoding="utf-8")
    assert ".env" in di_content
    assert "vouchflow.db" in di_content
    assert "__pycache__" in di_content


def test_streamlit_secrets_example():
    """secrets.toml.example must parse as valid TOML and list all expected secret keys."""
    secrets_path = ROOT_DIR / ".streamlit" / "secrets.toml.example"
    assert secrets_path.exists(), ".streamlit/secrets.toml.example must exist"
    
    content = secrets_path.read_text(encoding="utf-8")
    data = tomllib.loads(content)
    
    expected_keys = [
        "DATABASE_URL",
        "VOUCHFLOW_SECRET_KEY",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_MODEL_LIST",
        "DASHBOARD_URL",
        "ENVIRONMENT",
        "DATA_DIR",
    ]
    for key in expected_keys:
        assert key in data, f"Key {key} must be in secrets.toml.example"


def test_deploy_md_documentation_complete():
    """DEPLOY.md must cover all required targets and pre-flight checklist."""
    deploy_path = ROOT_DIR / "DEPLOY.md"
    assert deploy_path.exists(), "DEPLOY.md must exist in repository root"
    
    content = deploy_path.read_text(encoding="utf-8").lower()
    for keyword in ["neon", "render", "streamlit", "n8n", "checklist"]:
        assert keyword in content, f"DEPLOY.md must document {keyword}"


def test_startup_check_development_mode():
    """In development mode, missing settings are warnings, not errors."""
    mock_cfg = SimpleNamespace(
        ENVIRONMENT="development",
        is_sqlite=True,
        VOUCHFLOW_SECRET_KEY="",
        GEMINI_API_KEY="",
        DASHBOARD_URL="http://localhost:8501",
    )
    problems = check_environment(mock_cfg)
    errors = [p for p in problems if p.level == "error"]
    assert len(errors) == 0, "Development mode should produce 0 error-level problems"
    
    # Startup check should run without raising in development mode
    with patch("backend.startup_check.check_environment", return_value=problems):
        with patch("backend.startup_check.is_production", return_value=False):
            result = run_startup_check(exit_on_error=True)
            assert result == problems


def test_startup_check_production_requires_postgres_and_secret():
    """In production mode, SQLite or missing secret key causes stopping errors."""
    mock_cfg = SimpleNamespace(
        ENVIRONMENT="production",
        is_sqlite=True,
        VOUCHFLOW_SECRET_KEY="short",
        GEMINI_API_KEY="",
        DASHBOARD_URL="http://localhost:8501",
    )
    problems = check_environment(mock_cfg)
    errors = [p for p in problems if p.level == "error"]
    error_vars = [p.variable for p in errors]
    
    assert "DATABASE_URL" in error_vars, "Production with SQLite must produce DATABASE_URL error"
    assert "VOUCHFLOW_SECRET_KEY" in error_vars, "Production with short secret key must produce VOUCHFLOW_SECRET_KEY error"
    
    with patch("backend.startup_check.check_environment", return_value=problems):
        with patch("backend.startup_check.is_production", return_value=True):
            with pytest.raises(RuntimeError) as exc_info:
                run_startup_check(exit_on_error=True)
            assert "VouchFlow cannot start" in str(exc_info.value)
            assert "DATABASE_URL" in str(exc_info.value)
            assert "VOUCHFLOW_SECRET_KEY" in str(exc_info.value)


def test_startup_check_production_clean_passes():
    """In production mode with proper Postgres and secret key, zero errors are returned."""
    mock_cfg = SimpleNamespace(
        ENVIRONMENT="production",
        is_sqlite=False,
        VOUCHFLOW_SECRET_KEY="a" * 36,
        GEMINI_API_KEY="valid-key",
        DASHBOARD_URL="https://vouchflow.example.com",
    )
    problems = check_environment(mock_cfg)
    errors = [p for p in problems if p.level == "error"]
    assert len(errors) == 0, "Proper production configuration must have 0 errors"



# ---------------------------------------------------------------------------
# Example files must never contain a usable secret (a copied-but-unedited file must be harmless)
# ---------------------------------------------------------------------------
def _env_example_values():
    values = {}
    for line in (ROOT_DIR / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def test_env_example_has_no_usable_secrets():
    values = _env_example_values()
    assert values["VOUCHFLOW_SECRET_KEY"] == "", "the example must not ship a signing key"
    assert values["GEMINI_API_KEY"] == "", "the example must not ship (or fake) an API key"
    assert "@" not in values["DATABASE_URL"], "the example must not contain a database password"


def test_secrets_example_has_no_usable_secrets():
    data = tomllib.loads((ROOT_DIR / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8"))
    for key in ("DATABASE_URL", "VOUCHFLOW_SECRET_KEY", "GEMINI_API_KEY"):
        assert data[key] == "", f"{key} must be empty in the example"


@pytest.mark.parametrize("text", [
    "replace_with_a_secure_random_string_at_least_32_characters_long",
    "your_gemini_api_key_here", "", "   ", "change_me",
])
def test_placeholder_text_counts_as_not_set(text):
    from backend.config import Settings, is_placeholder

    assert is_placeholder(text)
    cfg = Settings(_env_file=None, VOUCHFLOW_SECRET_KEY=text, GEMINI_API_KEY=text)
    assert cfg.VOUCHFLOW_SECRET_KEY == "" and cfg.GEMINI_API_KEY == ""


def test_real_looking_values_are_kept():
    from backend.config import Settings

    cfg = Settings(_env_file=None, VOUCHFLOW_SECRET_KEY="x" * 40, GEMINI_API_KEY="AIzaFakeKeyForThisTest")
    assert cfg.VOUCHFLOW_SECRET_KEY == "x" * 40 and cfg.GEMINI_API_KEY == "AIzaFakeKeyForThisTest"


def test_production_refuses_a_placeholder_secret_key():
    from backend.config import Settings

    cfg = Settings(_env_file=None, ENVIRONMENT="production", DATABASE_URL="postgresql://u:p@host/db",
                   VOUCHFLOW_SECRET_KEY="replace_with_a_secure_random_string_at_least_32_characters_long")
    errors = [p.variable for p in check_environment(cfg) if p.level == "error"]
    assert errors == ["VOUCHFLOW_SECRET_KEY"]


# ---------------------------------------------------------------------------
# Container files
# ---------------------------------------------------------------------------
def test_compose_keeps_data_in_dedicated_volumes_and_has_health_checks():
    data = yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("api", "dashboard"):
        service = data["services"][name]
        mounts = [str(v) for v in service["volumes"]]
        assert any(m.endswith(":/app/db") for m in mounts) and any(m.endswith(":/app/data/workspaces") for m in mounts)
        assert not any(m.endswith(":/app/data") for m in mounts), "never hide the sample data under a volume"
        assert "healthcheck" in service
    assert data["services"]["dashboard"]["depends_on"]["api"]["condition"] == "service_healthy"
    text = (ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    assert "sslmode" not in text and "AIza" not in text and "vf_" not in text.replace("vouchflow", "")


def test_dockerfile_runs_as_a_normal_user():
    content = (ROOT_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "USER vouchflow" in content and "useradd" in content


def test_render_start_command_uses_python_module():
    data = yaml.safe_load((ROOT_DIR / "render.yaml").read_text(encoding="utf-8"))
    assert data["services"][0]["startCommand"].startswith("python -m uvicorn backend.main:app")
    secret = next(e for e in data["services"][0]["envVars"] if e["key"] == "VOUCHFLOW_SECRET_KEY")
    assert secret.get("generateValue") is True and "value" not in secret
    for key in ("DATABASE_URL", "GEMINI_API_KEY"):
        env = next(e for e in data["services"][0]["envVars"] if e["key"] == key)
        assert env.get("sync") is False and "value" not in env  # typed in on Render, never in the file
