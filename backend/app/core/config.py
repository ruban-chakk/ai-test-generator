from pathlib import Path

from pydantic import BaseSettings


dirpath = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    environment: str = "development"
    postgres_dsn: str = "postgresql+asyncpg://ai_test_gen:ai_test_gen_pass@localhost:5432/ai_test_gen"
    pinecone_api_key: str = ""
    pinecone_environment: str = "local"
    pinecone_index_name: str = "ai-testgen-embeddings"

    class Config:
        env_file = dirpath / ".env"
        env_file_encoding = "utf-8"


settings = Settings()
