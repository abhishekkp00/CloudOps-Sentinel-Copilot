from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from .config import (
    EMBEDDING_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
)

_embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
_pinecone = Pinecone(api_key=PINECONE_API_KEY)


def get_index():
    """Return the configured Pinecone index client."""
    return _pinecone.Index(PINECONE_INDEX_NAME)


def get_vector_store() -> PineconeVectorStore:
    """Return the application vector store without re-indexing documents."""
    return PineconeVectorStore(
        index_name=PINECONE_INDEX_NAME,
        namespace=PINECONE_NAMESPACE,
        embedding=_embeddings,
    )


def get_retriever(k: int = 4):
    """Return the Pinecone-backed retriever used by Self-RAG."""
    return get_vector_store().as_retriever(search_kwargs={"k": k})


def index_documents(documents: Sequence[Document]) -> list[str]:
    """Embed and upsert documents into the configured Pinecone namespace."""
    if not documents:
        return []

    return get_vector_store().add_documents(list(documents))
