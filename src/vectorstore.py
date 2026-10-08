from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from pinecone import Pinecone

from .config import get_settings

settings = get_settings()

_embeddings = HuggingFaceEmbeddings(model_name=settings.embedding_model)
_pinecone = Pinecone(api_key=settings.pinecone_api_key)


def get_index():
    """Return the configured Pinecone index client."""
    return _pinecone.Index(settings.pinecone_index_name)


def get_vector_store() -> PineconeVectorStore:
    """Return the application vector store without re-indexing documents."""
    return PineconeVectorStore(
        index_name=settings.pinecone_index_name,
        namespace=settings.pinecone_namespace,
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
