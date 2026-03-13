from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRE_HOURS: int = 8

    OPENAI_API_KEY: str = ""

    BREVO_API_KEY: str = ""
    BREVO_FROM_EMAIL: str = ""
    BREVO_FROM_NAME: str = ""

    BACKEND_URL: str = "http://localhost:8000"
    NEXT_PUBLIC_API_URL: str = "http://localhost:8000"

    SCHEDULER_TIMEZONE: str = "UTC"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
