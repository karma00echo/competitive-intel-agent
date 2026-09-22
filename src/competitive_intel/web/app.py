"""FastAPI application factory for the loopback-only local console."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from competitive_intel.api.router import router as api_router
from competitive_intel.api.intelligence import router as intelligence_router
from competitive_intel.config import Settings
from competitive_intel.persistence import Database, Persistence

from .runtime import AnalysisTaskManager, build_runner


WEB_ROOT = Path(__file__).resolve().parent


def create_app(
    *,
    settings: Settings | None = None,
    persistence: Persistence | None = None,
    task_manager: AnalysisTaskManager | None = None,
) -> FastAPI:
    configured = settings or Settings.from_env()
    owns_database = persistence is None
    store = persistence or Persistence(Database(configured.database))
    manager = task_manager or AnalysisTaskManager(
        store,
        lambda payload, sink: build_runner(configured, store, payload, sink),
        max_workers=configured.web.max_concurrent_analyses,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        manager.shutdown()
        if owns_database:
            store.database.dispose()

    app = FastAPI(
        title="Universal Competitive Intelligence Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = configured
    app.state.persistence = store
    app.state.task_manager = manager
    templates = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
    app.state.templates = templates

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        messages = "; ".join(
            str(error.get("msg", "Invalid request.")) for error in exc.errors()
        )
        code = (
            "REAL_CONTENT_FIXTURE_FACTS_FORBIDDEN"
            if "skip_fact_extraction=true" in messages
            else "INVALID_REQUEST"
        )
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error_code": code, "error_message": messages[:1000]},
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        del request
        detail = exc.detail if isinstance(exc.detail, dict) else {
            "ok": False,
            "error_code": "HTTP_ERROR",
            "error_message": str(exc.detail),
        }
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error_code": "INTERNAL_ERROR",
                "error_message": "The local service could not complete the request.",
            },
        )

    app.include_router(api_router)
    app.include_router(intelligence_router)
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT / "static")), name="static")

    @app.get("/workspace")
    def workspace(request: Request):
        return templates.TemplateResponse(
            request=request, name="workspace.html", context={"page": "workspace"}
        )

    @app.get("/developer/runs/{run_id}")
    def developer_run(request: Request, run_id: int):
        return templates.TemplateResponse(request=request, name="audit.html",
            context={"page": "audit", "resource_id": run_id})

    @app.get("/")
    @app.get("/analyst")
    @app.get("/history")
    def chat_page(request: Request):
        section = "history" if request.url.path == "/history" else "chat"
        return templates.TemplateResponse(request=request, name="chat.html",
            context={"page": section})

    @app.get("/command-center")
    @app.get("/signals")
    @app.get("/competitors")
    @app.get("/reports")
    def product_page(request: Request):
        section = request.url.path.strip("/") or "command-center"
        return templates.TemplateResponse(request=request, name="intelligence.html",
            context={"page": section})

    @app.get("/dashboard")
    @app.get("/developer")
    def home(request: Request):
        return templates.TemplateResponse(
            request=request, name="index.html", context={"page": "home"}
        )

    @app.get("/runs/{run_id}")
    def run_page(request: Request, run_id: int):
        return templates.TemplateResponse(
            request=request,
            name="audit.html",
            context={"page": "audit", "resource_id": run_id},
        )

    @app.get("/competitors/{competitor_id}")
    def competitor_page(request: Request, competitor_id: int):
        return templates.TemplateResponse(
            request=request,
            name="intelligence.html",
            context={"page": "intelligence-profile", "resource_id": competitor_id},
        )

    @app.get("/reports/{report_id}")
    def report_page(request: Request, report_id: int):
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={"page": "report", "resource_id": report_id},
        )

    return app
