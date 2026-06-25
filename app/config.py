from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"
    database_url: str = f"sqlite:///{BASE_DIR}/data/mikro_busway.db"
    data_dir: Path = BASE_DIR / "data"
    projects_dir: Path = BASE_DIR / "data/projects"
    templates_dir: Path = BASE_DIR / "data/templates"
    price_list_dir: Path = BASE_DIR / "data/price_list"

    class Config:
        env_file = ".env"


settings = Settings()

# Ensure data directories exist
for d in [settings.projects_dir, settings.templates_dir, settings.price_list_dir]:
    d.mkdir(parents=True, exist_ok=True)
