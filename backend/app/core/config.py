from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


dirpath = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=dirpath / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    postgres_dsn: str = "postgresql+asyncpg://ai_test_gen:ai_test_gen_pass@localhost:5432/ai_test_gen"
    llm_provider: str = "openai"
    llm_api_key: str = Field(default="", repr=False)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    provider_timeout_seconds: float = 30.0
    provider_max_attempts: int = 3
    auth_jwt_secret: str = Field(default="", repr=False)
    auth_jwt_algorithm: str = "HS256"
    auth_access_token_minutes: int = 30
    auth_issuer: str = "ai-test-generator"
    auth_audience: str = "ai-test-generator-api"
    auth_cookie_name: str = "atg_session"
    auth_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
    pinecone_api_key: str = ""
    pinecone_index_name: str = "ai-testgen-embeddings"
    pinecone_host: str = ""
    pinecone_namespace: str = "ai-test-generator"
    outbox_batch_size: int = 25
    outbox_max_attempts: int = 8
    outbox_lock_timeout_seconds: int = 300
    jira_base_url: str = ""
    jira_email: str = ""
    jira_api_token: str = Field(default="", repr=False)
    jira_timeout_seconds: float = 30.0
    test_repository_base_url: str = ""
    test_repository_token: str = Field(default="", repr=False)
    test_repository_provider: str = "generic"
    test_repository_timeout_seconds: float = 30.0
    xray_client_id: str = ""
    xray_client_secret: str = Field(default="", repr=False)
    xray_auth_url: str = "https://xray.cloud.getxray.app/api/v2/authenticate"
    xray_graphql_url: str = "https://xray.cloud.getxray.app/api/v2/graphql"
    testrail_username: str = ""
    testrail_api_key: str = Field(default="", repr=False)
    testrail_project_id: int | None = None
    testrail_section_id: int | None = None
    testrail_suite_id: int | None = None
    zephyr_base_url: str = "https://api.zephyrscale.smartbear.com/v2"
    zephyr_api_token: str = Field(default="", repr=False)
    execution_runner_base_url: str = ""
    execution_runner_token: str = Field(default="", repr=False)
    execution_runner_timeout_seconds: float = 120.0
    alert_webhook_url: str = ""
    alert_webhook_token: str = Field(default="", repr=False)
    alert_webhook_timeout_seconds: float = 10.0
    rate_limit_enabled: bool = True
    api_rate_limit_per_minute: int = 120
    auth_rate_limit_per_minute: int = 10
    upload_max_bytes: int = 2_000_000
    upload_max_requirements: int = 100
    health_probe_timeout_seconds: float = 5.0
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = Field(default="", repr=False)
    oidc_authorization_endpoint: str = ""
    oidc_token_endpoint: str = ""
    oidc_jwks_uri: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    oidc_frontend_redirect_url: str = "http://localhost:5173/requirements"
    oidc_allowed_email_domains: str = ""
    oidc_auto_provision: bool = False
    oidc_state_cookie_name: str = "atg_oidc_state"

    @field_validator("testrail_project_id", "testrail_section_id", "testrail_suite_id", mode="before")
    @classmethod
    def empty_optional_integer(cls, value):
        return None if value == "" else value


settings = Settings()
