import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.editor import router as editor_router
from app.api.jobs import router
from app.core.config import Settings
from app.core.environment import check_environment
from app.jobs.pipeline import Pipeline
from app.jobs.worker import LocalWorker
from app.models.editor import EditorStore
from app.models.store import JobStore
from app.services.editor import EditorService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup happens once; request handlers do not perform media work.
        report = check_environment(settings, deep=True)
        app.state.environment = report
        app.state.store = JobStore(settings.workspace_dir / "jobs.sqlite3")
        app.state.worker = LocalWorker(app.state.store, Pipeline(settings, app.state.store).process)
        editor_store = EditorStore(app.state.store)
        editor_store.recover()
        app.state.editor = EditorService(settings, app.state.store, editor_store)
        app.state.worker.handlers["edit"] = app.state.editor.process
        app.state.worker.start()
        if not report["ready"]:
            for check in report["checks"]:
                if not check["available"]:
                    logging.warning("%s: %s. %s", check["name"], check["detail"], check["hint"])
        yield
        await asyncio.to_thread(app.state.worker.close)

    app = FastAPI(title="Video Localizer", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)
    app.include_router(editor_router)

    @app.get("/api/options")
    def options():
        return {
            "source_language": settings.default_source_language,
            "target_language": settings.default_target_language,
            "voice": settings.default_voice,
            "max_upload_bytes": settings.max_download_bytes,
        }

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "pipeline_ready": app.state.environment["ready"],
            "phase": "mvp",
        }

    @app.get("/api/environment")
    def environment() -> dict:
        return app.state.environment

    return app
