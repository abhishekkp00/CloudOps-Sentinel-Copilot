from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# =========================
# Chat Request
# =========================

class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=2,
        max_length=2000,
        description="User question",
    )

    thread_id: str = Field(
        ...,
        min_length=3,
        max_length=120,
        description="Conversation thread identifier",
    )


# =========================
# Source
# =========================

class SourceItem(BaseModel):
    type: Literal["internal", "web"]

    title: str = ""

    source: str = ""

    url: Optional[str] = None

    page: Optional[int] = None


# =========================
# Chat Response
# =========================

class ChatResponse(BaseModel):
    answer: str

    # How the question was handled
    # Examples:
    # "direct"
    # "internal"
    # "web"
    # "internal_then_web"
    route: str

    used_web_search: bool = False

    # Self-RAG support evaluation
    support_status: str = ""

    # Self-RAG answer usefulness evaluation
    usefulness: str = ""

    # Retrieved sources
    sources: List[SourceItem] = Field(
        default_factory=list
    )

    # Execution trace for debugging/UI
    trace: List[str] = Field(
        default_factory=list
    )

    # Conversation identifier
    thread_id: str

    # Number of previous/current conversation turns
    memory_turns: int = 0


# =========================
# Document Upload Response
# =========================

class UploadResponse(BaseModel):
    filename: str

    chunks_indexed: int

    namespace: str