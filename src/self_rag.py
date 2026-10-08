from typing import List, TypedDict, Literal, Annotated
import operator

import psycopg
from psycopg.rows import dict_row

from pydantic import BaseModel, Field

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

from tavily import TavilyClient

from src.config import get_settings
from src.vectorstore import get_retriever


# ============================================================
# RAG STATE
# ============================================================

class RAGState(TypedDict, total=False):
    user_question: str
    question: str

    memory: Annotated[List[str], operator.add]

    retrieval_query: str
    web_query: str

    need_retrieval: bool

    docs: List[Document]
    relevant_docs: List[Document]

    context: str
    answer: str

    support_status: Literal[
        "fully_supported",
        "partially_supported",
        "no_support",
        "",
    ]

    evidence: List[str]

    usefulness: Literal[
        "useful",
        "not_useful",
        "",
    ]

    use_reason: str

    support_retries: int
    retrieval_rewrites: int
    web_rewrites: int

    source_mode: Literal[
        "internal",
        "web",
        "direct",
        "none",
    ]

    used_web_search: bool

    trace: List[str]


# ============================================================
# STRUCTURED OUTPUT MODELS
# ============================================================

class RetrieveDecision(BaseModel):
    should_retrieve: bool


class RelevanceDecision(BaseModel):
    is_relevant: bool


class SupportDecision(BaseModel):
    status: Literal[
        "fully_supported",
        "partially_supported",
        "no_support",
    ]

    evidence: List[str] = Field(
        default_factory=list
    )


class UsefulnessDecision(BaseModel):
    status: Literal[
        "useful",
        "not_useful",
    ]

    reason: str


class QueryRewrite(BaseModel):
    query: str


# ============================================================
# LLM
# ============================================================

def _llm():
    settings = get_settings()

    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured."
        )

    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=0,
        max_tokens=1024,
    )


# ============================================================
# TRACE
# ============================================================

def _trace(
    state: RAGState,
    item: str,
):
    return [
        *(state.get("trace") or []),
        item,
    ]


# ============================================================
# CONTEXT FORMATTING
# ============================================================

def _format_context(
    docs: List[Document],
) -> str:

    blocks = []

    for i, document in enumerate(docs, 1):

        metadata = document.metadata or {}

        if metadata.get("source_type") == "web":

            head = (
                f"[WEB {i}] "
                f"{metadata.get('title', '')} | "
                f"{metadata.get('url', '')}"
            )

        else:

            title_val = (
                metadata.get("title")
                or metadata.get("document_name")
                or metadata.get("source", "")
            )
            head = f"[INTERNAL {i}] {title_val}"

            if metadata.get("page") is not None:

                head += (
                    f" | page "
                    f"{int(metadata['page']) + 1}"
                )

        blocks.append(
            f"{head}\n{document.page_content}"
        )

    return "\n\n---\n\n".join(blocks)


# ============================================================
# MEMORY
# ============================================================

def _memory_text(
    state: RAGState,
    limit: int = 4,
) -> str:

    items = state.get("memory") or []

    if not items:
        return "No previous conversation context."

    return "\n\n".join(
        items[-limit:]
    )


def contextualize_question(
    state: RAGState,
):

    history = _memory_text(state)

    user_question = (
        state.get("user_question")
        or state.get("question", "")
    )

    if not state.get("memory"):

        return {
            "question": user_question,
            "trace": _trace(
                state,
                "Memory: new incident session",
            ),
        }

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Rewrite the newest user message as a standalone
cloud-operations question using the previous
conversation only when needed.

Preserve:
- service names
- symptoms
- errors
- constraints

If the message already stands alone,
return it unchanged.

Do not answer the question.
""",
            ),
            (
                "human",
                """
Previous conversation:
{history}

Newest message:
{question}
""",
            ),
        ]
    )

    out = (
        _llm()
        .with_structured_output(
            QueryRewrite,
            method="json_schema",
        )
        .invoke(
            prompt.format_messages(
                history=history,
                question=user_question,
            )
        )
    )

    return {
        "question": out.query,
        "trace": _trace(
            state,
            f"Memory contextualized question: {out.query}",
        ),
    }


def commit_memory(
    state: RAGState,
):

    user_question = (
        state.get("user_question")
        or state.get("question", "")
    )

    answer = state.get(
        "answer",
        "",
    )

    route = state.get(
        "source_mode",
        "none",
    )

    entry = (
        f"User: {user_question}\n"
        f"Assistant ({route}): {answer}"
    )

    return {
        "memory": [entry],
        "trace": _trace(
            state,
            "PostgreSQL memory checkpoint updated",
        ),
    }


# ============================================================
# RETRIEVAL DECISION
# ============================================================

def decide_retrieval(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
You decide whether the question needs retrieval.

Choose true for:
- cloud operations
- production incidents
- service runbooks
- deployment procedures
- infrastructure behavior
- troubleshooting steps
- specific/current technical facts
- questions where evidence is needed

Choose false only for generic technical
explanations that can safely be answered
from general knowledge.

If unsure, choose true.
""",
            ),
            (
                "human",
                "Question: {question}",
            ),
        ]
    )

    out = (
        _llm()
        .with_structured_output(
            RetrieveDecision,
            method="json_schema",
        )
        .invoke(
            prompt.format_messages(
                question=state["question"]
            )
        )
    )

    return {
        "need_retrieval": out.should_retrieve,
        "trace": _trace(
            state,
            f"Retrieval decision: {out.should_retrieve}",
        ),
    }


def route_after_decide(
    state: RAGState,
) -> Literal["direct", "retrieve"]:

    if state.get(
        "need_retrieval",
        True,
    ):
        return "retrieve"

    return "direct"


# ============================================================
# DIRECT ANSWER
# ============================================================

def generate_direct(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Answer briefly from general technical
knowledge only.

Do not invent:
- organization-specific infrastructure
- runbooks
- credentials
- incident history
- deployment procedures
""",
            ),
            (
                "human",
                "{question}",
            ),
        ]
    )

    answer = (
        _llm()
        .invoke(
            prompt.format_messages(
                question=state["question"]
            )
        )
        .content
    )

    return {
        "answer": answer,
        "source_mode": "direct",
        "trace": _trace(
            state,
            "Generated direct answer",
        ),
    }


# ============================================================
# INTERNAL RETRIEVAL
# ============================================================

def retrieve_internal(
    state: RAGState,
):

    query = (
        state.get("retrieval_query")
        or state["question"]
    )

    docs = get_retriever().invoke(query)

    for document in docs:

        document.metadata = {
            **(document.metadata or {}),
            "source_type": "internal",
        }

    return {
        "docs": docs,
        "relevant_docs": [],
        "source_mode": "internal",
        "trace": _trace(
            state,
            f"Internal retrieval: {len(docs)} chunks",
        ),
    }


# ============================================================
# RELEVANCE GRADING
# ============================================================

def grade_relevance(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Judge relevance at the topic/evidence level.

A document is relevant when it contains
information useful for answering the user's
question.

Do not require the exact final answer.

Be strict about unrelated content.
""",
            ),
            (
                "human",
                """
Question:
{question}

Document:
{document}
""",
            ),
        ]
    )

    grader = (
        _llm()
        .with_structured_output(
            RelevanceDecision,
            method="json_schema",
        )
    )

    relevant = []

    for document in state.get(
        "docs",
        [],
    ):

        try:

            decision = grader.invoke(
                prompt.format_messages(
                    question=state["question"],
                    document=document.page_content[:7000],
                )
            )

            if decision.is_relevant:
                relevant.append(document)

        except Exception:

            continue

    mode = state.get(
        "source_mode",
        "internal",
    )

    return {
        "relevant_docs": relevant,
        "trace": _trace(
            state,
            (
                f"Relevance grade ({mode}): "
                f"{len(relevant)}/"
                f"{len(state.get('docs', []))} relevant"
            ),
        ),
    }


# ============================================================
# RELEVANCE ROUTING
# ============================================================

def route_after_relevance(
    state: RAGState,
) -> Literal[
    "generate",
    "rewrite_internal",
    "rewrite_web",
    "no_answer",
]:

    if state.get("relevant_docs"):
        return "generate"

    settings = get_settings()

    if state.get("source_mode") == "web":

        if (
            state.get("web_rewrites", 0)
            < settings.max_web_rewrites
        ):
            return "rewrite_web"

        return "no_answer"

    if (
        state.get("retrieval_rewrites", 0)
        < settings.max_retrieval_rewrites
    ):
        return "rewrite_internal"

    return "rewrite_web"


# ============================================================
# INTERNAL QUERY REWRITE
# ============================================================

def rewrite_internal_query(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Rewrite the operations question for semantic
vector retrieval over internal:

- cloud runbooks
- SOPs
- postmortems
- architecture notes
- troubleshooting documents

Use 6-18 words.

Preserve service names and error symptoms.

Add useful operations keywords.

Remove filler.

Do not answer.
""",
            ),
            (
                "human",
                """
Question:
{question}

Previous query:
{previous}
""",
            ),
        ]
    )

    out = (
        _llm()
        .with_structured_output(
            QueryRewrite,
            method="json_schema",
        )
        .invoke(
            prompt.format_messages(
                question=state["question"],
                previous=state.get(
                    "retrieval_query",
                    "",
                ),
            )
        )
    )

    return {
        "retrieval_query": out.query,
        "retrieval_rewrites": (
            state.get(
                "retrieval_rewrites",
                0,
            ) + 1
        ),
        "docs": [],
        "relevant_docs": [],
        "trace": _trace(
            state,
            f"Rewrote internal query: {out.query}",
        ),
    }


# ============================================================
# WEB QUERY REWRITE
# ============================================================

def rewrite_web_query(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Rewrite the question into a concise
internet search query of 6-14 words.

Preserve important entities.

Add recency wording when the question
asks for latest/current/today.

Do not answer.
""",
            ),
            (
                "human",
                """
Question:
{question}

Previous web query:
{previous}
""",
            ),
        ]
    )

    out = (
        _llm()
        .with_structured_output(
            QueryRewrite,
            method="json_schema",
        )
        .invoke(
            prompt.format_messages(
                question=state["question"],
                previous=state.get(
                    "web_query",
                    "",
                ),
            )
        )
    )

    return {
        "web_query": out.query,
        "web_rewrites": (
            state.get(
                "web_rewrites",
                0,
            ) + 1
        ),
        "docs": [],
        "relevant_docs": [],
        "trace": _trace(
            state,
            f"Prepared internet search query: {out.query}",
        ),
    }


# ============================================================
# TAVILY WEB SEARCH
# ============================================================

def web_search(
    state: RAGState,
):

    settings = get_settings()

    if not settings.tavily_api_key:

        return {
            "docs": [],
            "source_mode": "web",
            "used_web_search": True,
            "trace": _trace(
                state,
                "Internet search unavailable: "
                "TAVILY_API_KEY missing",
            ),
        }

    client = TavilyClient(
        api_key=settings.tavily_api_key
    )

    query = (
        state.get("web_query")
        or state["question"]
    )

    response = client.search(
        query=query,
        search_depth="advanced",
        max_results=5,
        include_answer=False,
    )

    docs = []

    for result in response.get(
        "results",
        [],
    ):

        content = result.get(
            "content",
            "",
        )

        docs.append(
            Document(
                page_content=content,
                metadata={
                    "source_type": "web",
                    "source": result.get(
                        "url",
                        "",
                    ),
                    "url": result.get(
                        "url",
                        "",
                    ),
                    "title": result.get(
                        "title",
                        "",
                    ),
                },
            )
        )

    return {
        "docs": docs,
        "source_mode": "web",
        "used_web_search": True,
        "trace": _trace(
            state,
            f"Internet search: {len(docs)} results",
        ),
    }


# ============================================================
# GENERATE FROM EVIDENCE
# ============================================================

def generate_from_context(
    state: RAGState,
):

    context = _format_context(
        state.get(
            "relevant_docs",
            [],
        )
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
You are CloudOps Sentinel, an enterprise
cloud operations and incident-response copilot.

Answer using only the supplied evidence.

Prefer:
- private runbooks
- SOPs
- architecture notes
- postmortems

when present.

If the evidence comes from the web,
clearly label it as external guidance and
never present it as an organization-specific
procedure.

Do not invent:
- infrastructure facts
- credentials
- commands
- incident history

Provide concise, actionable troubleshooting
guidance.

Preserve any cautions contained in the evidence.
""",
            ),
            (
                "human",
                """
Question:
{question}

Evidence:
{context}
""",
            ),
        ]
    )

    answer = (
        _llm()
        .invoke(
            prompt.format_messages(
                question=state["question"],
                context=context,
            )
        )
        .content
    )

    return {
        "answer": answer,
        "context": context,
        "support_retries": 0,
        "trace": _trace(
            state,
            (
                "Generated answer from "
                f"{state.get('source_mode', '')} evidence"
            ),
        ),
    }


# ============================================================
# SUPPORT CHECK
# ============================================================

def check_support(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Verify whether every meaningful claim in the
answer is supported by the supplied evidence.

Return fully_supported only when all important
claims are grounded.

Return partially_supported when some claims
are grounded but some are not.

Return no_support when key claims are
unsupported.

Evidence excerpts should be short.
""",
            ),
            (
                "human",
                """
Question:
{question}

Answer:
{answer}

Evidence:
{context}
""",
            ),
        ]
    )

    out = (
        _llm()
        .with_structured_output(
            SupportDecision,
            method="json_schema",
        )
        .invoke(
            prompt.format_messages(
                question=state["question"],
                answer=state.get(
                    "answer",
                    "",
                ),
                context=state.get(
                    "context",
                    "",
                ),
            )
        )
    )

    return {
        "support_status": out.status,
        "evidence": out.evidence,
        "trace": _trace(
            state,
            f"Support check: {out.status}",
        ),
    }


def route_after_support(
    state: RAGState,
) -> Literal[
    "usefulness",
    "revise",
]:

    if (
        state.get("support_status")
        == "fully_supported"
    ):
        return "usefulness"

    if (
        state.get("support_retries", 0)
        >= get_settings().max_support_retries
    ):
        return "usefulness"

    return "revise"


# ============================================================
# ANSWER REVISION
# ============================================================

def revise_answer(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Rewrite the answer so every factual claim
is directly supported by the provided evidence.

Remove unsupported interpretation and speculation.

Still answer the question naturally.

Do not mention this verification process.
""",
            ),
            (
                "human",
                """
Question:
{question}

Current answer:
{answer}

Evidence:
{context}
""",
            ),
        ]
    )

    answer = (
        _llm()
        .invoke(
            prompt.format_messages(
                question=state["question"],
                answer=state.get(
                    "answer",
                    "",
                ),
                context=state.get(
                    "context",
                    "",
                ),
            )
        )
        .content
    )

    return {
        "answer": answer,
        "support_retries": (
            state.get(
                "support_retries",
                0,
            ) + 1
        ),
        "trace": _trace(
            state,
            "Revised answer for grounding",
        ),
    }


# ============================================================
# USEFULNESS CHECK
# ============================================================

def check_usefulness(
    state: RAGState,
):

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
Judge only whether the answer directly
addresses the user's question.

Do not re-grade factual grounding.

Return useful or not_useful and
a one-line reason.
""",
            ),
            (
                "human",
                """
Question:
{question}

Answer:
{answer}
""",
            ),
        ]
    )

    out = (
        _llm()
        .with_structured_output(
            UsefulnessDecision,
            method="json_schema",
        )
        .invoke(
            prompt.format_messages(
                question=state["question"],
                answer=state.get(
                    "answer",
                    "",
                ),
            )
        )
    )

    return {
        "usefulness": out.status,
        "use_reason": out.reason,
        "trace": _trace(
            state,
            f"Usefulness check: {out.status}",
        ),
    }


def route_after_usefulness(
    state: RAGState,
) -> Literal[
    "end",
    "rewrite_internal",
    "rewrite_web",
    "no_answer",
]:

    if (
        state.get("usefulness")
        == "useful"
    ):
        return "end"

    settings = get_settings()

    if state.get("source_mode") == "internal":

        if (
            state.get(
                "retrieval_rewrites",
                0,
            )
            < settings.max_retrieval_rewrites
        ):
            return "rewrite_internal"

        return "rewrite_web"

    if (
        state.get("source_mode") == "web"
        and state.get(
            "web_rewrites",
            0,
        )
        < settings.max_web_rewrites
    ):
        return "rewrite_web"

    return "no_answer"


# ============================================================
# NO ANSWER
# ============================================================

def no_answer(
    state: RAGState,
):

    return {
        "answer": (
            "I could not find enough reliable "
            "runbook or external evidence to "
            "recommend a safe troubleshooting action."
        ),
        "source_mode": "none",
        "trace": _trace(
            state,
            "Stopped: no reliable answer found",
        ),
    }


# ============================================================
# GRAPH
# ============================================================

def build_graph(
    checkpointer,
):

    graph = StateGraph(RAGState)

    graph.add_node(
        "contextualize",
        contextualize_question,
    )

    graph.add_node(
        "decide_retrieval",
        decide_retrieval,
    )

    graph.add_node(
        "direct",
        generate_direct,
    )

    graph.add_node(
        "retrieve",
        retrieve_internal,
    )

    graph.add_node(
        "grade",
        grade_relevance,
    )

    graph.add_node(
        "rewrite_internal",
        rewrite_internal_query,
    )

    graph.add_node(
        "rewrite_web",
        rewrite_web_query,
    )

    graph.add_node(
        "web_search",
        web_search,
    )

    graph.add_node(
        "generate",
        generate_from_context,
    )

    graph.add_node(
        "support",
        check_support,
    )

    graph.add_node(
        "revise",
        revise_answer,
    )

    graph.add_node(
        "usefulness",
        check_usefulness,
    )

    graph.add_node(
        "no_answer",
        no_answer,
    )

    graph.add_node(
        "commit_memory",
        commit_memory,
    )

    graph.add_edge(
        START,
        "contextualize",
    )

    graph.add_edge(
        "contextualize",
        "decide_retrieval",
    )

    graph.add_conditional_edges(
        "decide_retrieval",
        route_after_decide,
        {
            "direct": "direct",
            "retrieve": "retrieve",
        },
    )

    graph.add_edge(
        "direct",
        "commit_memory",
    )

    graph.add_edge(
        "retrieve",
        "grade",
    )

    graph.add_conditional_edges(
        "grade",
        route_after_relevance,
        {
            "generate": "generate",
            "rewrite_internal": "rewrite_internal",
            "rewrite_web": "rewrite_web",
            "no_answer": "no_answer",
        },
    )

    graph.add_edge(
        "rewrite_internal",
        "retrieve",
    )

    graph.add_edge(
        "rewrite_web",
        "web_search",
    )

    graph.add_edge(
        "web_search",
        "grade",
    )

    graph.add_edge(
        "generate",
        "support",
    )

    graph.add_conditional_edges(
        "support",
        route_after_support,
        {
            "usefulness": "usefulness",
            "revise": "revise",
        },
    )

    graph.add_edge(
        "revise",
        "support",
    )

    graph.add_conditional_edges(
        "usefulness",
        route_after_usefulness,
        {
            "end": "commit_memory",
            "rewrite_internal": "rewrite_internal",
            "rewrite_web": "rewrite_web",
            "no_answer": "no_answer",
        },
    )

    graph.add_edge(
        "no_answer",
        "commit_memory",
    )

    graph.add_edge(
        "commit_memory",
        END,
    )

    return graph.compile(
        checkpointer=checkpointer
    )


# ============================================================
# SOURCES
# ============================================================

def _sources(
    docs: List[Document],
):

    seen = set()
    output = []

    for document in docs or []:

        metadata = document.metadata or {}

        source_type = (
            "web"
            if metadata.get(
                "source_type"
            ) == "web"
            else "internal"
        )

        key = (
            source_type,
            metadata.get("url")
            or metadata.get("source"),
            metadata.get("page"),
        )

        if key in seen:
            continue

        seen.add(key)

        page = None

        if (
            source_type == "internal"
            and metadata.get("page") is not None
        ):
            page = int(
                metadata["page"]
            ) + 1

        output.append(
            {
                "type": source_type,
                "title": (
                    metadata.get("title")
                    or metadata.get(
                        "document_name"
                    )
                    or ""
                ),
                "source": metadata.get(
                    "source",
                    "",
                ),
                "url": (
                    metadata.get("url")
                    if source_type == "web"
                    else None
                ),
                "page": page,
            }
        )

    return output


# ============================================================
# POSTGRESQL CHECKPOINTER
# ============================================================

_checkpointer = None
_graph = None
_db_connection = None


def init_checkpointer():
    global _checkpointer
    global _graph
    global _db_connection

    if _graph is not None:
        return _graph

    settings = get_settings()

    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    _db_connection = psycopg.connect(
        settings.database_url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )

    _checkpointer = PostgresSaver(
        _db_connection
    )

    _checkpointer.setup()

    _graph = build_graph(
        checkpointer=_checkpointer
    )

    return _graph


def close_checkpointer():
    global _checkpointer
    global _graph
    global _db_connection

    _graph = None
    _checkpointer = None

    if _db_connection is not None:
        _db_connection.close()
        _db_connection = None


def _get_graph():
    if _graph is None:
        return init_checkpointer()

    return _graph


# ============================================================
# PUBLIC SELF-RAG FUNCTION
# ============================================================

def run_self_rag(
    question: str,
    thread_id: str,
) -> dict:

    graph = _get_graph()

    initial_state: RAGState = {
        "user_question": question,
        "question": question,
        "memory": [],
        "retrieval_query": question,
        "web_query": "",
        "need_retrieval": True,
        "docs": [],
        "relevant_docs": [],
        "context": "",
        "answer": "",
        "support_status": "",
        "evidence": [],
        "usefulness": "",
        "use_reason": "",
        "support_retries": 0,
        "retrieval_rewrites": 0,
        "web_rewrites": 0,
        "source_mode": "internal",
        "used_web_search": False,
        "trace": [],
    }

    result = graph.invoke(
        initial_state,
        config={
            "configurable": {
                "thread_id": thread_id,
            },
            "recursion_limit": 60,
        },
    )

    mode = result.get(
        "source_mode",
        "none",
    )

    route = {
        "internal": "Private Runbooks",
        "web": "Internet Search",
        "direct": "General Knowledge",
        "none": "No Reliable Evidence",
    }.get(
        mode,
        mode,
    )

    return {
        "answer": result.get(
            "answer",
            "",
        ),
        "route": route,
        "used_web_search": bool(
            result.get(
                "used_web_search"
            )
        ),
        "support_status": result.get(
            "support_status",
            "",
        ),
        "usefulness": result.get(
            "usefulness",
            "",
        ),
        "sources": _sources(
            result.get(
                "relevant_docs",
                [],
            )
        ),
        "trace": result.get(
            "trace",
            [],
        ),
        "thread_id": thread_id,
        "memory_turns": len(
            result.get(
                "memory",
                [],
            )
        ),
    }