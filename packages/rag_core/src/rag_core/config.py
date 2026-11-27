"""Application configuration for rag_core, loaded from the environment / ``.env``."""

from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration for rag_core.

    Loads from environment variables or .env file.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Optional so components (docs, tests, etc.) can build without a real database.
    database_url: str | None = None

    # Default user for single-user local scope
    default_user_id: UUID = UUID("00000000-0000-0000-0000-000000000000")

    # The embedding model ingestion and retrieval use, and its vector dimension.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384
    # Text put in front of every search query before it is embedded. The bge v1.5 model card
    # recommends this instruction for short queries matched against longer passages.
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages: "

    # Reranking: whether retrieval reranks, the cross-encoder it uses, and how many dense-search
    # candidates it rescores before keeping the top results.
    rerank_enabled: bool = True
    reranker_model: str = "jinaai/jina-reranker-v1-tiny-en"
    rerank_candidates: int = 20

    # Hybrid retrieval: fuse lexical search with dense search by Reciprocal Rank Fusion.
    hybrid_enabled: bool = False


settings = Settings()
