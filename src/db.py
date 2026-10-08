import json
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from src.config import get_settings


def get_connection():
    """Create a PostgreSQL database connection."""

    settings = get_settings()

    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is missing. "
            "Add it to your .env file."
        )

    return psycopg.connect(
        settings.database_url,
        row_factory=dict_row,
    )


def init_db() -> None:
    """Create the RAG audit table if it does not already exist."""

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_audit (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                route TEXT,
                used_web BOOLEAN NOT NULL DEFAULT FALSE,
                support_status TEXT,
                usefulness TEXT,
                trace_json JSONB,
                sources_json JSONB
            )
            """
        )

        conn.commit()


def save_audit(question: str, result: dict) -> None:
    """Save a completed Self-RAG execution."""

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rag_audit (
                created_at,
                question,
                answer,
                route,
                used_web,
                support_status,
                usefulness,
                trace_json,
                sources_json
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s::jsonb
            )
            """,
            (
                datetime.now(timezone.utc),
                question,
                result.get("answer", ""),
                result.get("route", ""),
                bool(result.get("used_web_search", False)),
                result.get("support_status", ""),
                result.get("usefulness", ""),
                json.dumps(
                    result.get("trace", []),
                    ensure_ascii=False,
                ),
                json.dumps(
                    result.get("sources", []),
                    ensure_ascii=False,
                ),
            ),
        )

        conn.commit()


def latest_audits(limit: int = 25) -> list[dict]:
    """Return the latest Self-RAG audit records."""

    limit = max(1, min(limit, 100))

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                question,
                answer,
                route,
                used_web,
                support_status,
                usefulness,
                trace_json,
                sources_json
            FROM rag_audit
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()

    return rows