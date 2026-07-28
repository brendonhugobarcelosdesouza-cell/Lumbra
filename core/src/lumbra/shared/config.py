"""Gerenciamento de configuração tipada.

Fonte única de configuração do sistema. Regras:

* Toda configuração vem de variáveis de ambiente prefixadas ``LUMBRA_``
  (aninhamento com ``__``, ex.: ``LUMBRA_DATABASE__DSN``) ou de um
  arquivo ``.env`` em desenvolvimento.
* Segredos usam ``SecretStr`` — nunca aparecem em ``repr``/logs.
* Nenhum módulo lê ``os.environ`` diretamente: recebe ``Settings``
  (ou sub-seção) por injeção de dependência.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class DatabaseSettings(BaseModel):
    """PostgreSQL (+pgvector)."""

    dsn: SecretStr = SecretStr("postgresql+asyncpg://lumbra:lumbra@localhost:5432/lumbra")
    pool_size: int = Field(default=10, ge=1, le=100)
    echo: bool = False


class RedisSettings(BaseModel):
    """Redis (cache, filas e Event Bus)."""

    url: SecretStr = SecretStr("redis://localhost:6379/0")
    stream_prefix: str = "lumbra"
    consumer_block_ms: int = Field(default=5_000, ge=100)
    consumer_concurrency: int = Field(default=4, ge=1)  # workers por consumidor (L2-1)
    max_delivery_attempts: int = Field(default=5, ge=1)
    retry_min_idle_ms: int = Field(default=30_000, ge=100)  # reentrega após este idle
    dedup_ttl_seconds: int = Field(default=86_400, ge=60)  # janela de idempotência
    stream_maxlen: int = Field(default=100_000, ge=1_000)  # retenção aproximada
    dlq_maxlen: int = Field(default=10_000, ge=100)  # DLQ limitada (L2-2)
    # resiliência a queda de conexão (L2-2): backoff exponencial com teto
    reconnect_backoff_base_ms: int = Field(default=200, ge=10)
    reconnect_backoff_cap_ms: int = Field(default=30_000, ge=100)
    publish_max_retries: int = Field(default=3, ge=0)  # reentrega de publish em blip de rede


class SecuritySettings(BaseModel):
    """Parâmetros de segurança. Presentes desde o dia 1 (segurança por padrão)."""

    jwt_secret: SecretStr = SecretStr(
        "dev-only-insecure-secret-change-in-prod-0000"
    )  # >=32 bytes (RFC 7518)
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = Field(default=900, ge=60)  # 15 min
    refresh_token_ttl_seconds: int = Field(default=1_209_600, ge=3600)  # 14 dias
    # origins autorizados a chamar a API de um navegador (CORS). Fora de
    # produção, o Nó libera "*" automaticamente; em produção, só o que
    # estiver aqui (ex.: LUMBRA_SECURITY__CORS_ALLOW_ORIGINS=["https://app…"]).
    cors_allow_origins: tuple[str, ...] = ()


class AISettings(BaseModel):
    """AI Gateway (ADR-025/ADR-028). Privacy first: local por padrão."""

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dim: int = 384
    embedding_cache_dir: str | None = None  # padrão da lib se None

    # chat/completions (E2-1): Ollama sempre disponível (é local); Anthropic
    # só entra como provedor se uma api_key for configurada (opt-in explícito)
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen2.5:7b"
    anthropic_api_key: SecretStr | None = None
    anthropic_chat_model: str = "claude-haiku-4-5-20251001"


class StorageSettings(BaseModel):
    """Onde ficam os blobs do usuário (anexos de conversa, uploads).

    Local por padrão — arquivos pessoais não saem da máquina (princípio
    nº 14). Trocar para S3/MinIO é implementar outro ``BlobStorePort``."""

    attachments_dir: str = "./data/attachments"


class ObservabilitySettings(BaseModel):
    """Telemetria é opt-in (privacy first): desligada por padrão."""

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    telemetry_enabled: bool = False


class Settings(BaseSettings):
    """Configuração raiz do Lumbra."""

    model_config = SettingsConfigDict(
        env_prefix="LUMBRA_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "local"
    eventbus: Literal["memory", "redis"] = "memory"
    persistence: Literal["memory", "postgres"] = "memory"
    database: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    security: SecuritySettings = SecuritySettings()
    ai: AISettings = AISettings()
    storage: StorageSettings = StorageSettings()
    observability: ObservabilitySettings = ObservabilitySettings()

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Instância de processo. Em testes, construa ``Settings`` diretamente."""
    return Settings()
