import json
import shutil
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.core.paths import JobPaths
from app.core.process import PipelineError
from app.jobs.pipeline import OUTPUT_NAMES
from app.models.store import JobConflict
from app.schemas.jobs import JobCreate
from app.services.subtitles import preview_subtitle
from app.services.uploads import UploadStore

router = APIRouter(prefix="/api")


def get_job(request: Request, job_id: UUID):
    try:
        return request.app.state.store.get(str(job_id))
    except KeyError as exc:
        raise HTTPException(404, "Job not found") from exc


def job_root(request: Request, job_id: UUID) -> Path:
    root = request.app.state.settings.workspace_dir.resolve() / "jobs"
    target = (root / str(job_id)).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(400, "Invalid job path")
    return target


@router.post("/uploads", status_code=201)
def upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    kind: Literal["video", "watermark"] = "video",
):
    settings = request.app.state.settings
    uploads = UploadStore(settings.workspace_dir)
    name = Path((file.filename or "").replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    allowed = {".png"} if kind == "watermark" else {".mp4", ".mov", ".mkv", ".webm"}
    if suffix not in allowed:
        raise HTTPException(422, "Expected PNG watermark or MP4/MOV/MKV/WebM video")
    token = uuid4()
    directory = uploads.root / str(token)
    directory.mkdir()
    path = directory / ("asset" + suffix)
    limit = settings.max_watermark_bytes if kind == "watermark" else settings.max_download_bytes
    size = 0
    try:
        with path.open("wb") as destination:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Upload exceeds {limit} bytes")
                destination.write(chunk)
        if not size:
            raise HTTPException(422, "Upload is empty")
        if kind == "watermark":
            try:
                with Image.open(path) as image:
                    if image.format != "PNG" or max(image.size) > 4096:
                        raise HTTPException(
                            422, "Watermark must be PNG, maximum 4096 pixels per side"
                        )
                    image.verify()
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
                raise HTTPException(422, "Invalid PNG watermark") from exc
        uploads.register(directory, path.name, name, kind, size)
    except Exception as exc:
        target = directory.resolve()
        if not target.is_relative_to(uploads.root.resolve()):
            raise PipelineError("Refusing upload cleanup outside uploads directory") from exc
        shutil.rmtree(target)
        raise
    finally:
        file.file.close()
    return {"id": str(token), "name": name, "size": size, "kind": kind}


@router.post("/jobs", status_code=201)
def create_job(config: JobCreate, request: Request):
    uploads = UploadStore(request.app.state.settings.workspace_dir)
    try:
        name = (
            config.source_url
            if config.source_type == "url"
            else uploads.resolve(config.source_file, "video")[1]
        )
        if config.watermark_enabled or config.thumbnail_branding:
            uploads.resolve(config.watermark_file, "watermark")
    except PipelineError as exc:
        raise HTTPException(422, str(exc)) from exc
    paths = JobPaths.create(request.app.state.settings.workspace_dir)
    return request.app.state.store.create(paths.id, config, name)


@router.get("/jobs")
def list_jobs(
    request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    return request.app.state.store.list(limit, offset)


@router.get("/jobs/{job_id}")
def read_job(job_id: UUID, request: Request):
    return get_job(request, job_id)


def schedule(request: Request, job_id: UUID, retry: bool):
    get_job(request, job_id)
    if not request.app.state.environment["ready"]:
        raise HTTPException(503, "External dependencies missing; see /api/environment")
    try:
        request.app.state.worker.submit(str(job_id), retry)
    except JobConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return get_job(request, job_id)


@router.post("/jobs/{job_id}/start", status_code=202)
def start_job(job_id: UUID, request: Request):
    return schedule(request, job_id, False)


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: UUID, request: Request):
    return schedule(request, job_id, True)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: UUID, request: Request):
    get_job(request, job_id)
    with request.app.state.worker.lock:
        try:
            request.app.state.editor.store.assert_source_idle(str(job_id))
            request.app.state.store.delete(str(job_id))
            request.app.state.editor.store.delete_project(str(job_id))
        except JobConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        target = job_root(request, job_id)
        if target.exists():
            shutil.rmtree(target)


@router.get("/jobs/{job_id}/files")
def files(job_id: UUID, request: Request):
    job = get_job(request, job_id)
    if job.status != "completed":
        return []
    root = job_root(request, job_id) / "final"
    return [
        {
            "name": name,
            "size": (root / name).stat().st_size,
            "url": f"/api/jobs/{job_id}/files/{name}",
        }
        for name in OUTPUT_NAMES
        if (root / name).is_file()
    ]


@router.get("/jobs/{job_id}/files/{name}")
def download_file(job_id: UUID, name: str, request: Request):
    job = get_job(request, job_id)
    path = job_root(request, job_id) / "final" / name
    if job.status != "completed" or name not in OUTPUT_NAMES or not path.is_file():
        raise HTTPException(404, "Output not available")
    return FileResponse(path, filename=name)


@router.get("/jobs/{job_id}/logs")
def logs(job_id: UUID, request: Request, limit: int = Query(100, ge=1, le=500)):
    get_job(request, job_id)
    path = job_root(request, job_id) / "logs" / "job.log"
    if not path.exists():
        return []
    with path.open("rb") as handle:
        size = path.stat().st_size
        handle.seek(max(0, size - 256 * 1024))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # A truncated first line or an in-progress write isn't a log record.
    return records


@router.get("/jobs/{job_id}/subtitle.vtt")
def subtitle_track(job_id: UUID, request: Request):
    job = get_job(request, job_id)
    root = job_root(request, job_id)
    if job.status != "completed" or not (root / "final/subtitle.srt").is_file():
        raise HTTPException(404, "Subtitle not available")
    try:
        target = preview_subtitle(root, request.app.state.settings)
    except PipelineError as exc:
        raise HTTPException(503, str(exc)) from exc
    return FileResponse(target, media_type="text/vtt")
