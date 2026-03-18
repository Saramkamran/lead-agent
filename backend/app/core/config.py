from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRE_HOURS: int = 8

    APP_SECRET_KEY: str = ""

    OPENAI_API_KEY: str = ""

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM_NAME: str = ""
    SMTP_FROM_EMAIL: str = ""

    IMAP_HOST: str = "imap.gmail.com"
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASS: str = ""
    IMAP_POLL_INTERVAL_SECONDS: int = 60
    IMAP_REPLY_FOLDER: str = "INBOX"

    BACKEND_URL: str = "http://localhost:8000"
    NEXT_PUBLIC_API_URL: str = "http://localhost:8000"

    SCHEDULER_TIMEZONE: str = "UTC"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
