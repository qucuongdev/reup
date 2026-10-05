import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.api.jobs import get_job
from app.core.process import PipelineError
from app.jobs.pipeline import OUTPUT_NAMES
from app.models.store import JobConflict
from app.schemas.editor import Clip, DraftSave, ExportRequest
from app.services.subtitles import preview_subtitle

router = APIRouter(prefix="/api/jobs/{job_id}/editor")


def service(request: Request, job_id: UUID):
    get_job(request, job_id)
    return request.app.state.editor


@router.get("")
def draft(job_id: UUID, request: Request):
    editor = service(request, job_id)
    try:
        sources = []
        source_errors = []
        for job in request.app.state.store.list(500):
            if job.status == "completed":
                try:
                    sources.append(editor.media(str(job.id)))
                except PipelineError as exc:
                    source_errors.append({"job_id": str(job.id), "error": str(exc)})
        saved = editor.draft(str(job_id))
        editor.validate([Clip.model_validate(clip) for clip in saved["clips"]])
        for clip in saved["clips"]:
            if not any(source["id"] == clip["job_id"] for source in sources):
                sources.append(editor.media(clip["job_id"]))
        return saved | {"sources": sources, "source_errors": source_errors}
    except (PipelineError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("")
def save(job_id: UUID, plan: DraftSave, request: Request):
    editor = service(request, job_id)
    try:
        with request.app.state.worker.lock:
            editor.media(str(job_id))
            editor.validate(plan.clips)
            return editor.store.save(str(job_id), plan)
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (PipelineError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/exports", status_code=202)
def export(job_id: UUID, config: ExportRequest, request: Request):
    editor = service(request, job_id)
    try:
        with request.app.state.worker.lock:
            saved = editor.store.draft(str(job_id))
            if not saved or saved["revision"] != config.revision:
                raise JobConflict("Save/reload the timeline before exporting")
            editor.validate([Clip.model_validate(clip) for clip in saved["clips"]])
            created = editor.store.enqueue(str(job_id), config.revision)
            try:
                request.app.state.worker.submit_task("edit", created["id"])
            except RuntimeError:
                editor.store.update(created["id"], "failed", 0, "failed", "Worker shutting down")
                raise
        return created
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (PipelineError, KeyError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/exports")
def exports(job_id: UUID, request: Request):
    return service(request, job_id).store.exports(str(job_id))


def owned_export(job_id: UUID, export_id: UUID, request: Request):
    editor = service(request, job_id)
    try:
        item = editor.store.export(str(export_id))
    except KeyError as exc:
        raise HTTPException(404, "Export not found") from exc
    if item["job_id"] != str(job_id):
        raise HTTPException(404, "Export not found in this job")
    return editor, item


@router.get("/exports/{export_id}")
def read_export(job_id: UUID, export_id: UUID, request: Request):
    return owned_export(job_id, export_id, request)[1]


@router.get("/exports/{export_id}/files")
def files(job_id: UUID, export_id: UUID, request: Request):
    editor, item = owned_export(job_id, export_id, request)
    if item["status"] != "completed":
        return []
    root = editor.export_root(item) / "final"
    return [
        {
            "name": name,
            "size": (root / name).stat().st_size,
            "url": f"/api/jobs/{job_id}/editor/exports/{export_id}/files/{name}",
        }
        for name in OUTPUT_NAMES
        if (root / name).is_file()
    ]


@router.get("/exports/{export_id}/files/{name}")
def download(job_id: UUID, export_id: UUID, name: str, request: Request):
    editor, item = owned_export(job_id, export_id, request)
    path = editor.export_root(item) / "final" / name
    if item["status"] != "completed" or name not in OUTPUT_NAMES or not path.is_file():
        raise HTTPException(404, "Export file not available")
    return FileResponse(path, filename=name)


@router.get("/exports/{export_id}/subtitle.vtt")
def track(job_id: UUID, export_id: UUID, request: Request):
    editor, item = owned_export(job_id, export_id, request)
    root = editor.export_root(item)
    srt = root / "final/subtitle.srt"
    if item["status"] != "completed" or not srt.is_file() or not srt.stat().st_size:
        raise HTTPException(404, "Export subtitles not available")
    try:
        path = preview_subtitle(root, request.app.state.settings)
    except PipelineError as exc:
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(path, media_type="text/vtt")


@router.get("/exports/{export_id}/logs")
def logs(job_id: UUID, export_id: UUID, request: Request, limit: int = Query(100, ge=1, le=500)):
    editor, item = owned_export(job_id, export_id, request)
    path = editor.export_root(item) / "logs/job.log"
    if not path.is_file():
        return []
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 256 * 1024))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # Partial first/last JSON record while process writes.
    return records
