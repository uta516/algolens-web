from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    secret_key: str = "dev-secret-key"
    database_url: str = "sqlite:///./data/algolens.db"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    atcoder_username: str = ""
    atcoder_password: str = ""
    # ChromaDB の保存先（未設定なら backend/data/chroma/）
    chroma_dir: str = ""
    # 振り返りで使う提出コードの置き場所（ファイル名に問題IDを含める。例: abc476_d.py）
    submissions_dir: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
