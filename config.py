import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database Settings
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "luzo_local_db"

    # Queue Settings
    redis_url: str = "redis://localhost:6379/0"

    # AWS S3 Storage Settings
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"
    s3_bucket_name: str = "luzo-report-exports"

    # SMTP Email Settings
    smtp_host: str = "smtp.mailgun.org"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "reports@luzo.app"

    # Service Security
    api_secret_token: str = "super-secret-service-token"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
