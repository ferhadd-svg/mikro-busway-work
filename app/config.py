from pydantic_settings import BaseSettings
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# On Render/Railway the data volume is mounted at /opt/render/project/src/data
# Fall back to local data/ when running locally
_data_root = Path(os.environ.get("RENDER_PROJECT_DIR", str(BASE_DIR))) / "data"


class Settings(BaseSettings):
    anthropic_api_key: str = ""   # optional — only needed for AI drawing read
    claude_model: str = "claude-sonnet-4-6"
    database_url: str = f"sqlite:///{_data_root}/mikro_busway.db"
    data_dir: Path = _data_root
    projects_dir: Path = _data_root / "projects"
    templates_dir: Path = _data_root / "templates"
    price_list_dir: Path = _data_root / "price_list"

    # Auth — session cookie is a random token looked up in the DB on every
    # request (see app/services/auth.py), so secret_key does NOT sign or
    # protect it. It's kept only as a general-purpose app secret for future
    # use (e.g. CSRF tokens), not part of the current auth security boundary.
    secret_key: str = "dev-insecure-secret-change-me"
    session_cookie_name: str = "mikro_session"
    session_lifetime_days: int = 14
    cookie_secure: bool = False   # set True in production once served over HTTPS

    class Config:
        env_file = ".env"


settings = Settings()

if settings.secret_key == "dev-insecure-secret-change-me":
    print("[startup] WARNING: SECRET_KEY is using the insecure default. Set SECRET_KEY in .env for production.")

# Ensure data directories exist
for d in [settings.projects_dir, settings.templates_dir, settings.price_list_dir]:
    d.mkdir(parents=True, exist_ok=True)
