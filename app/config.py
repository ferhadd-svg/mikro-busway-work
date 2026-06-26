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

    class Config:
        env_file = ".env"


settings = Settings()

# Ensure data directories exist
for d in [settings.projects_dir, settings.templates_dir, settings.price_list_dir]:
    d.mkdir(parents=True, exist_ok=True)
