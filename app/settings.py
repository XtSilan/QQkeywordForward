from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    database_path: str = "/app/data/nonebot/bot.sqlite3"
    log_dir: str = "/app/data/logs/nonebot"
    napcat_webui_url: str = "http://napcat:6099"
    napcat_webui_token: str = ""
    napcat_webui_credential: str = ""
    napcat_password_login_enabled: bool = False
    napcat_container_name: str = "qq-bot-napcat"
    nonebot_container_name: str = "qq-bot-nonebot"
    webui_container_name: str = "qq-bot-webui"
    docker_socket: str = "/var/run/docker.sock"
    control_enabled: bool = False
    admin_token: str = "change-me"
    environment: str = "prod"
    driver: str = "~fastapi"
    onebot_access_token: str = ""
    onebot_ws_url: str = "ws://napcat:3001"
    onebot_http_url: str = "http://napcat:3001"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout: int = 15
    auth_session_secret: str = "change-me-session-secret"
    auth_session_ttl: int = 86400
    upload_dir: str = "/app/data/nonebot/uploads"
    public_base_url: str = "http://localhost:8080"
    max_upload_size_mb: int = 10
    # Baked into the image at build time (compose build arg, maintained by the
    # updater helper). Shown in the WebUI sidebar so the running build is
    # identifiable after every auto-update.
    app_version: str = "dev"
    app_build_time: str = ""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.prod"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
