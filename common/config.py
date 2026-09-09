from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "ab_testing_db"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@db:5432/ab_testing_db"
    SYNC_DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/ab_testing_db"
    REDIS_URL: str = "redis://cache:6379/0"
    RABBITMQ_URL: str = "amqp://guest:guest@queue:5672/"
    EVENT_API_URL: str = "http://event-api:8000/events"

    REDIS_CHANNEL: str = "experiment_updates"
    RABBITMQ_QUEUE: str = "analytics_events"
    CONFIG_API_PORT: int = 8001
    DECISION_ENGINE_PORT: int = 8002
    EVENT_API_PORT: int = 8000


settings = Settings()
