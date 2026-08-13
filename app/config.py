from pydantic_settings import BaseSettings
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
_APP_DIR = Path(__file__).resolve().parent

# On Render/Railway the data volume is mounted at /opt/render/project/src/data
# Fall back to local data/ when running locally
_data_root = Path(os.environ.get("RENDER_PROJECT_DIR", str(BASE_DIR))) / "data"


class Settings(BaseSettings):
    anthropic_api_key: str = ""   # optional — only needed for AI drawing read
    # Reading a dense A0/A1 SLD is the hardest task in the app, so it defaults
    # to the strongest vision model. Override with CLAUDE_MODEL if needed.
    claude_model: str = "claude-opus-4-8"
    database_url: str = f"sqlite:///{_data_root}/mikro_busway.db"
    data_dir: Path = _data_root
    projects_dir: Path = _data_root / "projects"
    templates_dir: Path = _data_root / "templates"
    price_list_dir: Path = _data_root / "price_list"

    # Cold-start default price list. Render's free tier has no persistent disk,
    # so the uploaded price_list_dir is wiped on every deploy — leaving the app
    # with no prices until someone re-uploads. To avoid that, a canonical price
    # list is bundled in the repo (app/bundled_price_list/) and auto-loaded when
    # price_list_dir is empty. An admin uploading a newer list still overrides
    # it. Set PRICE_LIST_BUNDLED_FILE to an absolute path (e.g. a Render Secret
    # File) to source the default from outside the repo without a code change.
    bundled_price_list_dir: Path = _APP_DIR / "bundled_price_list"
    price_list_bundled_file: str = ""

    # Auth — session cookie is a random token looked up in the DB on every
    # request (see app/services/auth.py), so secret_key does NOT sign or
    # protect it. It's kept only as a general-purpose app secret for future
    # use (e.g. CSRF tokens), not part of the current auth security boundary.
    secret_key: str = "dev-insecure-secret-change-me"
    session_cookie_name: str = "mikro_session"
    session_lifetime_days: int = 14
    cookie_secure: bool = False   # set True in production once served over HTTPS

    # Email — optional, sent via the Brevo transactional email HTTP API (not
    # raw SMTP: Render's free plan blocks all outbound traffic on SMTP ports
    # 25/465/587 — confirmed live 2026-08-12, every send failed with "Network
    # unreachable" regardless of correct credentials — so this must go over
    # HTTPS instead). Empty brevo_api_key disables the "email quotation"
    # feature entirely; the endpoint returns a clear 400 and the UI shows a
    # "not configured" note. Set these as Render env vars (they persist
    # across deploys, unlike the ephemeral DB).
    brevo_api_key: str = ""
    email_from: str = ""          # must be a Brevo-verified sender address

    class Config:
        env_file = ".env"


settings = Settings()

if settings.secret_key == "dev-insecure-secret-change-me":
    print("[startup] WARNING: SECRET_KEY is using the insecure default. Set SECRET_KEY in .env for production.")

# Ensure data directories exist
for d in [settings.projects_dir, settings.templates_dir, settings.price_list_dir]:
    d.mkdir(parents=True, exist_ok=True)
