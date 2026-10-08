from pathlib import Path

from src.config import get_settings
from src.ingestion import ingest_directory, SUPPORTED
from src.vectorstore import get_index


ROOT = Path(__file__).resolve().parent
DOCUMENTS_DIR = ROOT / "documents"


def main():
    settings = get_settings()

    # =========================
    # Validate configuration
    # =========================
    if not settings.pinecone_api_key:
        raise RuntimeError(
            "PINECONE_API_KEY is missing. "
            "Add it to your .env file."
        )

    if not settings.pinecone_index_name:
        raise RuntimeError(
            "PINECONE_INDEX_NAME is missing. "
            "Add it to your .env file."
        )

    print("=" * 68)
    print("CloudOps Sentinel - Pinecone Knowledge Base Ingestion")
    print("=" * 68)

    print(
        f"Embedding model        : "
        f"{settings.embedding_model}"
    )

    print(
        f"Embedding dimension    : "
        f"{settings.embedding_dimension}"
    )

    print(
        f"Pinecone index         : "
        f"{settings.pinecone_index_name}"
    )

    print(
        f"Pinecone namespace     : "
        f"{settings.pinecone_namespace}"
    )

    print(
        f"Documents directory    : "
        f"{DOCUMENTS_DIR}"
    )

    print()

    # =========================
    # Check Pinecone index
    # =========================
    try:
        index = get_index()

        description = index.describe_index_stats()

        print("[1/2] Pinecone connection successful.")

        print(
            f"      Current vectors    : "
            f"{description.total_vector_count}"
        )

    except Exception as exc:
        raise RuntimeError(
            "Could not connect to Pinecone. "
            "Check your API key, index name, and Pinecone configuration."
        ) from exc

    print()

    # =========================
    # Find documents
    # =========================
    files = (
        [
            path
            for path in sorted(DOCUMENTS_DIR.iterdir())
            if path.is_file()
            and path.suffix.lower() in SUPPORTED
        ]
        if DOCUMENTS_DIR.exists()
        else []
    )

    if not files:
        print(
            "[2/2] No supported documents found."
        )

        print(
            "      Add PDF, TXT, MD, or DOCX files "
            "to ./documents and run again."
        )

        return

    print(
        f"[2/2] Ingesting {len(files)} document(s)..."
    )

    for path in files:
        print(f"      - {path.name}")

    print()

    # =========================
    # Ingest documents
    # =========================
    total_chunks = ingest_directory(
        DOCUMENTS_DIR
    )

    print()
    print("=" * 68)
    print("Knowledge base is ready.")
    print("=" * 68)

    print(
        f"Indexed chunks        : {total_chunks}"
    )

    print(
        f"Pinecone index        : "
        f"{settings.pinecone_index_name}"
    )

    print(
        f"Pinecone namespace    : "
        f"{settings.pinecone_namespace}"
    )

    print(
        f"Embedding model       : "
        f"{settings.embedding_model}"
    )


if __name__ == "__main__":
    main()