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


class BriefGenerateRequest(BaseModel):
    main_keyword: str = Field(..., min_length=1)
    s1_data: dict = Field(..., description="Pre-computed S1 data")


class TextAuditRequest(BaseModel):
    main_keyword: str = Field(..., min_length=1)
    text: str = Field(..., min_length=50, description="Article text to audit")


class ProofreadRequest(BaseModel):
    text: str = Field(..., min_length=50, description="Article text to proofread")
    s1_data: Optional[dict] = Field(default=None, description="S1 data for context")
    variables: Optional[dict] = Field(default=None, description="Article variables")
    brief: Optional[str] = Field(default=None, description="Brief text for context")
    auto_fix: bool = Field(default=True, description="Apply automatic fixes")


class ArticleEditRequest(BaseModel):
    text: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1)
    engine: str = Field(default="claude")


class FixIssueRequest(BaseModel):
    article_text: str = Field(..., min_length=50, description="Full article text")
    issue_text: str = Field(..., min_length=1, description="Original problematic text fragment")
    issue_type: str = Field(..., description="Type: hallucination, duplicate, fact, ai_artifact, unfulfilled_promise, language")
    issue_reason: str = Field(default="", description="Why this is flagged")
    issue_action: str = Field(default="", description="Suggested action from proofreader")


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
    orchestrator = ArticleOrchestrator(
        s1_data=s1_data, engine=req.engine, model=model,
        nw_terms=req.nw_terms, h2_keywords=req.h2_structure,
        project_id=req.project_id,
    )

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


@app.post("/api/generate_brief", dependencies=[Depends(require_api_key)])
async def generate_brief_endpoint(req: BriefGenerateRequest):
    """Generate content brief from S1 data without running full article pipeline."""
    try:
        from src.article_pipeline.variables import extract_global_variables
        from src.article_pipeline.brief_generator import generate_brief

        variables = extract_global_variables(req.s1_data)
        brief_data = generate_brief(
            s1_data=req.s1_data,
            variables=variables,
        )
        return {"brief": brief_data, "status": "ok"}
    except Exception as e:
        return {"brief": None, "status": "error", "error": str(e)}


@app.post("/api/audit", dependencies=[Depends(require_api_key)])
async def audit_text(req: TextAuditRequest):
    """Audit existing text against S1 SERP analysis. Returns job_id for SSE streaming."""
    job_id = str(uuid.uuid4())[:8]

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "events": [],
            "main_keyword": req.main_keyword,
        }

    def _run():
        try:
            from src.article_pipeline.text_auditor import run_text_audit
            for event in run_text_audit(req.main_keyword, req.text):
                with _jobs_lock:
                    _jobs[job_id]["events"].append(event)
                    if event.get("event") == "audit_complete":
                        _jobs[job_id]["status"] = "complete"
                        _jobs[job_id]["result"] = event.get("data", {})
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
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


@app.post("/api/proofread", dependencies=[Depends(require_api_key)])
async def proofread_article_endpoint(req: ProofreadRequest):
    """Run editorial proofreader on article text. Re-runs compliance after fixes."""
    try:
        from src.article_pipeline.editorial_proofreader import proofread_article
        result = proofread_article(
            article_text=req.text,
            s1_data=req.s1_data or {},
            variables=req.variables or {},
            auto_fix=req.auto_fix,
        )

        # Re-run compliance on corrected text so stats reflect final state
        corrected = result.get("corrected_text") or req.text
        if result.get("stats", {}).get("auto_fixed", 0) > 0 and req.s1_data:
            try:
                from src.article_pipeline.entity_seo_compliance import run_entity_seo_compliance
                from src.article_pipeline.ngram_patcher import check_ngram_coverage

                nlp = None
                try:
                    from src.common.nlp_singleton import get_nlp
                    nlp = get_nlp()
                except Exception:
                    pass

                ngrams = (req.s1_data.get("ngrams") or []) + (req.s1_data.get("extended_terms") or [])
                coverage = check_ngram_coverage(corrected, ngrams) if ngrams else None

                compliance = run_entity_seo_compliance(
                    article_text=corrected,
                    s1_data=req.s1_data,
                    ngram_coverage=coverage,
                    nlp=nlp,
                )
                result["updated_compliance"] = compliance
                result["compliance_score"] = compliance.get("overall_score", 0)
                print(f"[PROOFREAD] Compliance re-calculated after fixes: {compliance.get('overall_score', 0)}")
            except Exception as e:
                print(f"[PROOFREAD] Compliance re-run error: {e}")

        return result
    except Exception as e:
        import traceback
        print(f"[PROOFREAD API] Error: {traceback.format_exc()}")
        return {
            "error": str(e),
            "corrected_text": req.text,
            "applied": [],
            "flagged": [],
            "stats": {
                "auto_fixed": 0,
                "flagged_for_review": 0,
                "hallucinations_found": 0,
                "overall_quality": "error",
            },
        }


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


@app.post("/api/fix_issue", dependencies=[Depends(require_api_key)])
async def fix_issue(req: FixIssueRequest):
    """Fix a single proofreader-flagged issue using AI."""
    from src.common.llm import claude_call

    # Extract context: find the problematic fragment in the article
    # and grab surrounding text (±300 chars) for context
    issue_lower = req.issue_text.lower().strip()
    article_lower = req.article_text.lower()
    idx = article_lower.find(issue_lower[:60])

    if idx >= 0:
        ctx_start = max(0, idx - 300)
        ctx_end = min(len(req.article_text), idx + len(req.issue_text) + 300)
        context = req.article_text[ctx_start:ctx_end]
    else:
        context = req.issue_text

    # Type-specific prompts for optimal fixes
    type_instructions = {
        "hallucination": (
            "Fragment zawiera informacje bez pokrycia w danych referencyjnych. "
            "USUN caly fragment lub zastap go bezpiecznym, ogolnym stwierdzeniem. "
            "NIE wymyslaj nowych faktow."
        ),
        "duplicate": (
            "Fragment powtarza informacje z innej czesci artykulu. "
            "Przepisz go tak, by wniosl NOWA wartosc informacyjna albo usun go calkowicie. "
            "Zachowaj plynnosc tekstu."
        ),
        "fact": (
            "Fragment zawiera twierdzenie bez potwierdzenia w danych referencyjnych. "
            "Zlagodz sformulowanie (dodaj: 'moze', 'w wielu przypadkach', 'co do zasady') "
            "lub usun konkretna wartosc ktora nie jest potwierdzona."
        ),
        "ai_artifact": (
            "Fragment to artefakt AI: nienaturalna skladnia, zlepek fraz SEO lub sztuczne "
            "przejscie narracyjne. Przepisz na naturalny, czytelny polski tekst."
        ),
        "unfulfilled_promise": (
            "Naglowek obiecuje cos, czego tekst nie dostarcza. "
            "Uzupelnij tekst o brakujace elementy lub zmien naglowek na dokladniejszy."
        ),
        "language": (
            "Fragment zawiera blad jezykowy, gramatyczny lub stylistyczny. "
            "Popraw jezyk zachowujac sens i styl artykulu."
        ),
    }

    instruction = type_instructions.get(req.issue_type, type_instructions["language"])

    system = (
        "Jestes redaktorem polskiego tekstu SEO. Naprawiasz JEDEN konkretny problem.\n"
        "Zwroc TYLKO naprawiony fragment (ten sam zakres tekstu co 'FRAGMENT DO NAPRAWY').\n"
        "NIE dodawaj komentarzy, NIE zmieniaj reszty tekstu.\n"
        "Jesli najlepsza opcja to USUNAC fragment — zwroc pusty string.\n"
        "Odpowiedz TYLKO naprawionym tekstem, bez zadnych dodatkow."
    )

    user = (
        f"TYP PROBLEMU: {req.issue_type}\n"
        f"INSTRUKCJA: {instruction}\n"
        f"POWOD FLAGI: {req.issue_reason}\n"
        f"SUGEROWANA AKCJA: {req.issue_action}\n\n"
        f"KONTEKST (artykul wokol fragmentu):\n{context}\n\n"
        f"FRAGMENT DO NAPRAWY:\n{req.issue_text}"
    )

    try:
        result, usage = claude_call(
            system_prompt=system,
            user_prompt=user,
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            temperature=0.3,
        )

        fixed_text = result.strip()
        # Clean up potential markdown wrappers
        if fixed_text.startswith("```"):
            lines = fixed_text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            fixed_text = "\n".join(lines).strip()

        return {
            "original": req.issue_text,
            "fixed": fixed_text,
            "type": req.issue_type,
            "usage": usage,
            "was_deleted": len(fixed_text.strip()) < 10,
        }
    except Exception as e:
        return {"error": str(e), "original": req.issue_text, "fixed": req.issue_text}


class RecheckComplianceRequest(BaseModel):
    text: str = Field(..., min_length=50, description="Article text after proofreading")
    s1_data: Optional[dict] = Field(default=None, description="S1 data for context")


@app.post("/api/recheck_compliance", dependencies=[Depends(require_api_key)])
async def recheck_compliance(req: RecheckComplianceRequest):
    """Re-run compliance check on corrected article text (after proofreader)."""
    try:
        from src.article_pipeline.entity_seo_compliance import run_entity_seo_compliance
        from src.article_pipeline.ngram_patcher import check_ngram_coverage

        s1 = req.s1_data or {}

        # Re-check n-gram coverage on corrected text
        ngrams = (s1.get("ngrams") or []) + (s1.get("extended_terms") or [])
        coverage = check_ngram_coverage(req.text, ngrams) if ngrams else None

        nlp = None
        try:
            from src.common.nlp_singleton import get_nlp
            nlp = get_nlp()
        except Exception:
            pass

        compliance = run_entity_seo_compliance(
            article_text=req.text,
            s1_data=s1,
            ngram_coverage=coverage,
            nlp=nlp,
        )

        return {
            "entity_compliance": compliance,
            "overall_score": compliance.get("overall_score", 0),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "overall_score": 0}


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
