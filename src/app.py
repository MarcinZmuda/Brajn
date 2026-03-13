"""
Brajn SEO — Unified Application
================================
Consolidates gpt-ngram-api (S1), article pipeline (BRAJEN_PROMPTS_v1.0),
and optional modules from master-seo-api into a single FastAPI app.

Deploy: Render.com (render.yaml included)
"""
import json
import uuid
import threading
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.common.config import VERSION, APP_NAME, CORS_ORIGINS, MAX_CONTENT_LENGTH
from src.common.auth import require_api_key
from src.common.firebase import save_project, load_project
from src.s1.analysis import run_s1_analysis
from src.article_pipeline.orchestrator import ArticleOrchestrator

# ══════════════════════════════════════════════════════════════
# App Initialization
# ══════════════════════════════════════════════════════════════
app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description="Unified SEO content pipeline: SERP analysis → article generation → validation",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job storage for SSE workflows
_jobs = {}
_jobs_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════
# Request/Response Models
# ══════════════════════════════════════════════════════════════
class S1AnalysisRequest(BaseModel):
    main_keyword: str = Field(..., min_length=1, description="Main SEO keyword to analyze")
    sources: Optional[list[dict]] = Field(default=None, description="Pre-scraped sources (auto-fetch from SerpAPI if empty)")
    top_n: int = Field(default=30, ge=5, le=100, description="Number of top n-grams to return")
    project_id: Optional[str] = Field(default=None, description="Firestore project ID for persistence")


class ArticleStartRequest(BaseModel):
    main_keyword: str = Field(..., min_length=1)
    s1_data: Optional[dict] = Field(default=None, description="Pre-computed S1 data (auto-runs S1 if empty)")
    engine: str = Field(default="claude", description="LLM engine: claude or openai")
    model: Optional[str] = Field(default=None, description="Model override")
    project_id: Optional[str] = Field(default=None)
    h2_structure: Optional[list[str]] = Field(default=None, description="Custom H2 structure")
    nw_terms: Optional[list[str]] = Field(default=None, description="NW/Surfer terms for coverage analysis")


class ArticleEditRequest(BaseModel):
    text: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1)
    engine: str = Field(default="claude")


class ArticleValidateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    s1_data: Optional[dict] = Field(default=None)


# ══════════════════════════════════════════════════════════════
# Health & Info
# ══════════════════════════════════════════════════════════════
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": APP_NAME,
        "version": VERSION,
        "features": {
            "s1_analysis": True,
            "article_pipeline": True,
            "cloudflare_browser_rendering": True,
            "brajen_prompts_v1": True,
        },
    }


@app.get("/api/version")
async def version_info():
    return {"version": VERSION, "app": APP_NAME}


# ══════════════════════════════════════════════════════════════
# S1 Analysis Endpoints
# ══════════════════════════════════════════════════════════════
@app.post("/api/s1_analysis", dependencies=[Depends(require_api_key)])
async def s1_analysis(req: S1AnalysisRequest):
    """Run full S1 SERP analysis: n-grams, entities, causal triplets, content gaps."""
    result = run_s1_analysis(
        main_keyword=req.main_keyword,
        sources=req.sources,
        top_n=req.top_n,
        project_id=req.project_id,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# Backward compatibility alias
@app.post("/api/ngram_entity_analysis", dependencies=[Depends(require_api_key)])
async def ngram_entity_analysis(req: S1AnalysisRequest):
    """Alias for s1_analysis (backward compatibility with gpt-ngram-api)."""
    return await s1_analysis(req)


# ══════════════════════════════════════════════════════════════
# Article Pipeline Endpoints
# ══════════════════════════════════════════════════════════════
@app.post("/api/start", dependencies=[Depends(require_api_key)])
async def start_workflow(req: ArticleStartRequest):
    """Start article generation workflow. Returns job_id for SSE streaming."""
    job_id = str(uuid.uuid4())[:8]

    s1_data = req.s1_data
    if not s1_data:
        # Run S1 first
        s1_data = run_s1_analysis(main_keyword=req.main_keyword)
        if "error" in s1_data:
            raise HTTPException(status_code=400, detail=s1_data["error"])

    model = req.model or "claude-sonnet-4-6"
    orchestrator = ArticleOrchestrator(s1_data=s1_data, engine=req.engine, model=model, nw_terms=req.nw_terms)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "orchestrator": orchestrator,
            "events": [],
            "main_keyword": req.main_keyword,
            "project_id": req.project_id,
        }

    # Run pipeline in background thread
    def _run():
        try:
            for event in orchestrator.run_full_pipeline():
                with _jobs_lock:
                    _jobs[job_id]["events"].append(event)
                    if event.get("event") == "complete":
                        _jobs[job_id]["status"] = "complete"
                        _jobs[job_id]["result"] = event.get("data", {})
                        # Save to Firestore
                        if req.project_id:
                            save_project(req.project_id, {
                                "article": event["data"].get("full_text", ""),
                                "validation": event["data"].get("validation_score", 0),
                                "s1_data": s1_data,
                            })
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(e)
                _jobs[job_id]["events"].append({"event": "error", "data": {"message": str(e)}})

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "started", "main_keyword": req.main_keyword}


@app.get("/api/stream/{job_id}")
async def stream_workflow(job_id: str):
    """SSE stream for article generation progress."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    def generate():
        last_idx = 0
        import time
        while True:
            with _jobs_lock:
                job = _jobs.get(job_id)
                if not job:
                    break
                events = job["events"][last_idx:]
                last_idx = len(job["events"])
                status = job["status"]

            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if status in ("complete", "error"):
                break

            time.sleep(0.5)

        yield "data: {\"event\": \"stream_end\"}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/export/{job_id}/{fmt}")
async def export_article(job_id: str, fmt: str):
    """Export generated article in various formats."""
    job = _jobs.get(job_id)
    if not job or job["status"] != "complete":
        raise HTTPException(status_code=404, detail="Job not found or not complete")

    article = job.get("result", {}).get("full_text", "")
    if not article:
        raise HTTPException(status_code=404, detail="No article text")

    if fmt == "html":
        import re
        html = article
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        paragraphs = html.split("\n\n")
        html = "\n".join(
            f"<p>{p}</p>" if not p.startswith("<h") else p
            for p in paragraphs
            if p.strip()
        )
        return HTMLResponse(content=html)

    elif fmt == "txt":
        return JSONResponse(content={"text": article})

    elif fmt == "json":
        return JSONResponse(content={
            "text": article,
            "word_count": len(article.split()),
            "validation": job.get("result", {}).get("validation_score", 0),
        })

    raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")


@app.post("/api/edit", dependencies=[Depends(require_api_key)])
async def edit_article(req: ArticleEditRequest):
    """Edit article text with AI instruction."""
    from src.common.llm import claude_call

    system = "Jesteś redaktorem tekstu SEO. Edytuj poniższy tekst zgodnie z instrukcją. Zwróć TYLKO zmodyfikowany tekst."
    user = f"INSTRUKCJA: {req.instruction}\n\nTEKST DO EDYCJI:\n{req.text}"

    result, usage = claude_call(
        system_prompt=system,
        user_prompt=user,
        max_tokens=8000,
        temperature=0.5,
    )

    return {"edited_text": result, "usage": usage}


@app.post("/api/validate", dependencies=[Depends(require_api_key)])
async def validate_article(req: ArticleValidateRequest):
    """Validate article against BRAJEN quality criteria."""
    from src.article_pipeline.validators import validate_global
    from src.article_pipeline.variables import extract_global_variables

    variables = {}
    if req.s1_data:
        variables = extract_global_variables(req.s1_data)

    result = validate_global(req.text, variables)
    return result


# ══════════════════════════════════════════════════════════════
# Optional Modules — activated post-generation
# ══════════════════════════════════════════════════════════════
@app.get("/api/optional_modules")
async def list_optional_modules():
    """List available optional post-processing modules."""
    modules = []

    try:
        from src.optional_modules.ai_detection import check_ai_detection
        modules.append({"id": "ai_detection", "name": "AI Detection Check", "available": True})
    except ImportError:
        modules.append({"id": "ai_detection", "name": "AI Detection Check", "available": False})

    try:
        from src.optional_modules.editorial_review import run_editorial
        modules.append({"id": "editorial_review", "name": "Editorial Review", "available": True})
    except ImportError:
        modules.append({"id": "editorial_review", "name": "Editorial Review", "available": False})

    try:
        from src.optional_modules.compliance_report import run_compliance
        modules.append({"id": "compliance_report", "name": "Compliance Report", "available": True})
    except ImportError:
        modules.append({"id": "compliance_report", "name": "Compliance Report", "available": False})

    try:
        from src.optional_modules.export_module import export_docx
        modules.append({"id": "export_docx", "name": "Export DOCX", "available": True})
    except ImportError:
        modules.append({"id": "export_docx", "name": "Export DOCX", "available": False})

    return {"modules": modules}


@app.post("/api/optional/{module_id}", dependencies=[Depends(require_api_key)])
async def run_optional_module(module_id: str, request: Request):
    """Run an optional post-processing module."""
    body = await request.json()
    text = body.get("text", "")
    s1_data = body.get("s1_data", {})

    if module_id == "ai_detection":
        try:
            from src.optional_modules.ai_detection import check_ai_detection
            return check_ai_detection(text)
        except ImportError:
            raise HTTPException(status_code=501, detail="AI Detection module not installed")

    elif module_id == "editorial_review":
        try:
            from src.optional_modules.editorial_review import run_editorial
            return run_editorial(text, s1_data)
        except ImportError:
            raise HTTPException(status_code=501, detail="Editorial Review module not installed")

    elif module_id == "compliance_report":
        try:
            from src.optional_modules.compliance_report import run_compliance
            return run_compliance(text, s1_data)
        except ImportError:
            raise HTTPException(status_code=501, detail="Compliance Report module not installed")

    elif module_id == "export_docx":
        try:
            from src.optional_modules.export_module import export_docx
            return export_docx(text)
        except ImportError:
            raise HTTPException(status_code=501, detail="Export module not installed")

    raise HTTPException(status_code=404, detail=f"Unknown module: {module_id}")


# ══════════════════════════════════════════════════════════════
# Engines Info
# ══════════════════════════════════════════════════════════════
@app.get("/api/engines")
async def get_engines():
    """List available LLM engines."""
    engines = [{"id": "claude", "name": "Claude (Anthropic)", "available": True}]
    try:
        import openai
        from src.common.config import OPENAI_API_KEY
        engines.append({"id": "openai", "name": "OpenAI GPT-4o", "available": bool(OPENAI_API_KEY)})
    except ImportError:
        engines.append({"id": "openai", "name": "OpenAI GPT-4o", "available": False})
    return {"engines": engines}


# ══════════════════════════════════════════════════════════════
# Panel (served at root)
# ══════════════════════════════════════════════════════════════
@app.get("/")
async def index():
    """Serve the panel HTML."""
    try:
        with open("src/panel/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content=f"<h1>{APP_NAME} v{VERSION}</h1><p>Panel not installed. Use API endpoints.</p>")
