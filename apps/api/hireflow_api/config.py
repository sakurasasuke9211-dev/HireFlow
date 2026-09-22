from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env.example", ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    secret_key: str = "change-me"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_db_url: str = ""
    redis_url: str = ""

    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "hireflow"
    s3_region: str = "us-east-1"
    local_storage_dir: str = "./data/objects"

    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 168
    max_upload_bytes: int = 10 * 1024 * 1024

    llm_provider: str = "groq"
    llm_api_key: str = ""
    groq_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3
    llm_temperature: float = 0
    llm_json_mode: bool = True
    llm_disable_provider_training: bool = True
    llm_model_fast: str = "openai/gpt-oss-20b"
    llm_model_strong: str = "openai/gpt-oss-120b"
    llm_max_output_tokens_fast: int = 4096
    llm_max_output_tokens_strong: int = 8192
    llm_model_jd_parser: str = ""
    llm_model_resume_parser: str = ""
    llm_model_transcript_parser: str = ""
    llm_model_matcher: str = ""
    llm_model_gap_analyst: str = ""
    llm_model_interview_designer: str = ""
    llm_model_prober: str = ""
    llm_model_evidence_collector: str = ""
    llm_model_report: str = ""
    llm_model_file_locator: str = ""
    llm_model_file_summarizer: str = ""
    llm_azure_api_version: str = "2024-10-21"
    llm_azure_deployment_fast: str = ""
    llm_azure_deployment_strong: str = ""

    _FAST_AGENTS: ClassVar[frozenset[str]] = frozenset(
        {"jd_parser", "resume_parser", "transcript_parser", "file_locator", "file_summarizer"}
    )
    _STRONG_AGENTS: ClassVar[frozenset[str]] = frozenset(
        {
            "matcher",
            "gap_analyst",
            "interview_designer",
            "prober",
            "evidence_collector",
            "report",
        }
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def uses_s3(self) -> bool:
        return bool(self.s3_endpoint_url or self.s3_access_key)

    @property
    def uses_redis(self) -> bool:
        return bool(self.redis_url)

    @property
    def resolved_llm_api_key(self) -> str:
        return self.llm_api_key or self.groq_api_key

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "ollama":
            return bool(self.llm_base_url or self.llm_model_fast)
        return bool(self.resolved_llm_api_key)

    def llm_model_for(self, agent: str) -> str:
        override = getattr(self, f"llm_model_{agent}", "")
        if override:
            return override
        if agent in self._FAST_AGENTS:
            return self.llm_model_fast
        if agent in self._STRONG_AGENTS:
            return self.llm_model_strong
        raise ValueError(f"unknown agent for model routing: {agent}")

    def llm_max_output_tokens_for(self, agent: str) -> int:
        if agent in self._FAST_AGENTS:
            return self.llm_max_output_tokens_fast
        if agent in self._STRONG_AGENTS:
            return self.llm_max_output_tokens_strong
        raise ValueError(f"unknown agent for token routing: {agent}")

    def resolved_storage_dir(self) -> Path:
        path = Path(self.local_storage_dir)
        if not path.is_absolute():
            path = ROOT_DIR / path
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
