from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "dev-secret-key"
    database_url: str = "sqlite:///./data/algolens.db"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    atcoder_username: str = ""
    atcoder_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
