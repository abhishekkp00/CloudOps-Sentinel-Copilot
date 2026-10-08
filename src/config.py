import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


GROQ_API_KEY = _required("GROQ_API_KEY")
TAVILY_API_KEY = _required("TAVILY_API_KEY")
PINECONE_API_KEY = _required("PINECONE_API_KEY")

PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "cloudops-sentinel")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "cloudops")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
