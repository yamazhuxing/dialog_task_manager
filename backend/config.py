from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "right_label_sample"

    secret_key: str = "change-me"
    admin_username: str = "admin"
    admin_password: str = "admin123"

    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"

    access_token_expire_minutes: int = 60 * 24

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def questions_path(self) -> Path:
        return self.project_root / "questions_1200.json"

    @property
    def database_url(self) -> str:
        password = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
