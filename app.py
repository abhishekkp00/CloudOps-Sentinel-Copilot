from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import uuid

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.concurrency import run_in_threadpool

from src.models import ChatRequest, ChatResponse, UploadResponse
from src.self_rag import (
    run_self_rag,
    init_checkpointer,
    close_checkpointer,
)
from src.ingestion import ingest_file, namespace, SUPPORTED
from src.db import init_db, save_audit, latest_audits
from src.config import get_settings


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

settings = get_settings()

ROOT = Path(__file__).resolve().parent

UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# Application startup
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize application dependencies at startup.
    """
    init_db()
    init_checkpointer()

    try:
        yield
    finally:
        close_checkpointer()


# ---------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------

app = FastAPI(
    title="CloudOps Sentinel — Enterprise Incident Response Self-RAG Copilot",
    version="2.0.0",
    description=(
        "Self-RAG copilot for cloud operations, "
        "production troubleshooting, and incident-response runbooks."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------
# Static files / templates
# ---------------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory=str(ROOT / "static")),
    name="static",
)

templates = Jinja2Templates(
    directory=str(ROOT / "templates")
)


# ---------------------------------------------------------
# Web UI
# ---------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={},
    )


# ---------------------------------------------------------
# Health check
# ---------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "cloudops-sentinel-self-rag",
        "version": app.version,
    }


# ---------------------------------------------------------
# Chat
# ---------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest):

    question = payload.question.strip()
    thread_id = payload.thread_id.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    if not thread_id:
        raise HTTPException(
            status_code=400,
            detail="Thread ID cannot be empty.",
        )

    try:
        # Run synchronous Self-RAG workflow outside
        # the FastAPI event loop.
        result = await run_in_threadpool(
            run_self_rag,
            question,
            thread_id,
        )

        # Audit logging should not destroy an otherwise
        # successful chat response.
        try:
            await run_in_threadpool(
                save_audit,
                question,
                result,
            )
        except Exception as audit_error:
            print(f"[WARNING] Audit logging failed: {audit_error}")

        return ChatResponse(**result)

    except HTTPException:
        raise

    except Exception as e:
        print(f"[ERROR] Chat failed: {e}")

        raise HTTPException(
            status_code=500,
            detail="Internal error while processing the request.",
        )


# ---------------------------------------------------------
# Document upload
# ---------------------------------------------------------

@app.post(
    "/api/upload",
    response_model=UploadResponse,
)
async def upload(file: UploadFile = File(...)):

    original_name = file.filename or ""

    if not original_name:
        raise HTTPException(
            status_code=400,
            detail="Filename is required.",
        )

    suffix = Path(original_name).suffix.lower()

    if suffix not in SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail="Supported file types: PDF, TXT, MD, DOCX.",
        )

    # Prevent path traversal and filename collisions.
    original_path = Path(original_name)

    safe_stem = original_path.stem
    safe_suffix = original_path.suffix.lower()

    unique_name = f"{safe_stem}_{uuid.uuid4().hex[:8]}{safe_suffix}"

    target = UPLOADS / unique_name

    try:

        # Save uploaded file.
        with target.open("wb") as f:
            shutil.copyfileobj(file.file, f)

        # Ingest into Pinecone.
        count = await run_in_threadpool(
            ingest_file,
            target,
        )

        return UploadResponse(
            filename=original_name,
            chunks_indexed=count,
            namespace=namespace(),
        )

    except Exception as e:

        print(f"[ERROR] Document ingestion failed: {e}")

        # Remove failed upload.
        if target.exists():
            target.unlink(missing_ok=True)

        raise HTTPException(
            status_code=500,
            detail="Document ingestion failed.",
        )

    finally:
        await file.close()


# ---------------------------------------------------------
# Audit history
# ---------------------------------------------------------

@app.get("/api/audits")
def audits(limit: int = 20):

    limit = min(
        max(limit, 1),
        100,
    )

    return latest_audits(limit)


# ---------------------------------------------------------
# Local development
# ---------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )