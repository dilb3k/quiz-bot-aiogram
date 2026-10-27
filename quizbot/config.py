from zoneinfo import ZoneInfo
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    bot_token: SecretStr = SecretStr("")
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "nb_420"
    db_user: str = "postgres"
    db_password: SecretStr = SecretStr("")
    superadmin_id: int = 5583276966
    timezone: str = "Asia/Tashkent"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    def require_token(self) -> str:
        token = self.bot_token.get_secret_value().strip()
        if not token or token == "YOUR_BOTFATHER_TOKEN":
            raise ValueError("BOT_TOKEN bo‘sh. .env fayliga BotFather bergan tokenni kiriting.")
        return token

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+asyncpg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )
