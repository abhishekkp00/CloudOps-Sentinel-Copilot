from functools import lru_cache
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    # =========================
    # Groq LLM
    # =========================
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-120b"
    )

    # =========================
    # Local HuggingFace Embeddings
    # =========================
    embedding_model: str = os.getenv(
        "EMBEDDING_MODEL",
        "BAAI/bge-small-en-v1.5"
    )

    # BAAI/bge-small-en-v1.5 produces 384-dimensional embeddings
    embedding_dimension: int = int(
        os.getenv("EMBEDDING_DIMENSION", "384")
    )

    # =========================
    # Pinecone
    # =========================
    pinecone_api_key: str = os.getenv(
        "PINECONE_API_KEY",
        ""
    )

    pinecone_index_name: str = os.getenv(
        "PINECONE_INDEX_NAME",
        "cloudops-sentinel"
    )

    pinecone_namespace: str = os.getenv(
        "PINECONE_NAMESPACE",
        "cloudops"
    )

    # These are useful for documentation/configuration,
    # but the existing index already has its cloud/region.
    pinecone_cloud: str = os.getenv(
        "PINECONE_CLOUD",
        "aws"
    )

    pinecone_region: str = os.getenv(
        "PINECONE_REGION",
        "us-east-1"
    )

    # =========================
    # Tavily Web Search
    # =========================
    tavily_api_key: str = os.getenv(
        "TAVILY_API_KEY",
        ""
    )

    # =========================
    # Self-RAG Controls
    # =========================
    top_k: int = int(
        os.getenv("TOP_K", "4")
    )

    max_support_retries: int = int(
        os.getenv("MAX_SUPPORT_RETRIES", "2")
    )

    max_retrieval_rewrites: int = int(
        os.getenv("MAX_RETRIEVAL_REWRITES", "2")
    )

    max_web_rewrites: int = int(
        os.getenv("MAX_WEB_REWRITES", "2")
    )

    # =========================
    # PostgreSQL
    # =========================
    database_url: str = os.getenv(
        "DATABASE_URL",
        ""
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()