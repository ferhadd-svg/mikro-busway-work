import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
_data_root = Path(os.environ.get("RENDER_PROJECT_DIR", str(BASE_DIR))) / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "*"

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    claude_max_tokens: int = 4096
    claude_timeout_seconds: float = 90.0
    claude_max_retries: int = 3
    claude_max_file_bytes: int = 10 * 1024 * 1024
    claude_max_image_px: int = 2000
    max_extracted_text_chars: int = 60000
    max_upload_bytes: int = 25 * 1024 * 1024

    database_url: str = f"sqlite:///{_data_root}/mikro_busway.db"
    data_dir: Path = _data_root
    projects_dir: Path = _data_root / "projects"
    templates_dir: Path = _data_root / "templates"
    price_list_dir: Path = _data_root / "price_list"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


settings = Settings()

for directory in [
    settings.projects_dir,
    settings.templates_dir,
    settings.price_list_dir,
]:
    directory.mkdir(parents=True, exist_ok=True)
