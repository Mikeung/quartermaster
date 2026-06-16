from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "quartermaster"
    app_env: str = "development"
    app_version: str = "0.1.0"
    debug: bool = False

    host: str = "0.0.0.0"
    port: int = 8000

    log_level: str = "INFO"
    log_format: str = "json"

    db_path: str = "data/operational_memory.db"

    scan_interval_seconds: int = 300
    max_scan_history: int = 100
    scan_targets: str = "."
    reports_dir: str = "data/reports"

    # Telegram delivery
    telegram_enabled: bool = False
    telegram_bot_token: str = ""          # never logged or exposed
    telegram_chat_id: str = ""
    telegram_daily_digest_enabled: bool = True
    telegram_critical_alerts_enabled: bool = True
    telegram_quiet_hours_start: str = "22:00"   # UTC HH:MM
    telegram_quiet_hours_end: str = "08:00"     # UTC HH:MM


settings = Settings()
