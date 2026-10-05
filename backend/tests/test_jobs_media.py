import io
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.models.store import JobConflict, JobStore
from app.schemas.jobs import JobCreate, JobStatus
from app.services.postprocess.processor import VideoProcessor
from app.services.renderer.ffmpeg import FFmpegRenderer


def config(**options):
    return JobCreate(source_type="local", source_file=uuid4(), **options)


def test_lifecycle_claim_retry_recovery(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    identifier = str(uuid4())
    store.create(identifier, config(), "demo.mp4")
    store.schedule(identifier)
    assert store.claim(identifier).attempt == 1
    with pytest.raises(JobConflict):
        store.schedule(identifier)
    with pytest.raises(JobConflict):
        store.delete(identifier)
    store.stage(identifier, JobStatus.transcribing, 14, "transcribing")
    with pytest.raises(JobConflict):
        store.stage(identifier, JobStatus.downloading, 0, "downloading")
    store.recover()
    assert store.get(identifier).status == JobStatus.failed
    store.schedule(identifier, retry=True)
    assert store.claim(identifier).attempt == 2
    store.stage(identifier, JobStatus.completed, 100, "done")
    with pytest.raises(JobConflict):
        store.schedule(identifier, retry=True)
    store.delete(identifier)
    with pytest.raises(KeyError):
        store.get(identifier)


@pytest.mark.parametrize(
    "options",
    [
        {"burn_subtitle": True, "subtitle_enabled": False},
        {"watermark_enabled": True},
        {"target_language": "en"},
        {"output_ratio": "4:3"},
        {"thumbnail_timestamp": -1},
    ],
)
def test_invalid_job_options(options):
    with pytest.raises(ValidationError):
        config(**options)


def test_ffmpeg_preserves_aspect_and_uses_safe_arguments(tmp_path):
    processor = VideoProcessor()
    assert "crop=1080:1920" in processor.resize("9:16", "crop")
    assert "force_original_aspect_ratio=decrease" in processor.resize("16:9", "pad")
    assert "pad=1920:1080" in processor.resize("16:9", "pad")
    assert "setsar=1" in processor.resize("original", "crop")
    settings = Settings(_env_file=None)
    options = config(
        output_ratio="1:1",
        burn_subtitle=True,
        watermark_enabled=True,
        watermark_file=uuid4(),
        watermark={"position": "top-left", "opacity": 0.5},
    )
    renderer = FFmpegRenderer(settings, None)
    input_video = tmp_path / "video tiếng Việt.mp4"
    command = renderer.build_command(input_video, tmp_path / "final.mp4", options, 640)
    assert str(input_video) in command
    filters = command[command.index("-filter_complex") + 1]
    assert "subtitle.srt" in filters and str(tmp_path) not in filters
    assert "overlay=24:24:shortest=1" in filters
    assert "colorchannelmixer=aa=0.5" in filters
    assert command[command.index("-map") + 1] == "[out]"


def test_api_upload_validation_and_dependency_failure(tmp_path):
    settings = Settings(
        _env_file=None,
        workspace_dir=tmp_path,
        ffmpeg_path="missing",
        ffprobe_path="missing",
        ytdlp_path="missing",
        max_download_bytes=8,
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/uploads", files={"file": ("bad.exe", b"x")}).status_code == 422
        assert (
            client.post("/api/uploads", files={"file": ("a.mp4", b"123456789")}).status_code == 413
        )
        assert (
            client.post(
                "/api/uploads?kind=watermark", files={"file": ("a.png", b"bad")}
            ).status_code
            == 422
        )
        token = client.post("/api/uploads", files={"file": ("../safe.mp4", b"123")}).json()["id"]
        created = client.post("/api/jobs", json={"source_type": "local", "source_file": token})
        assert created.status_code == 201
        job = created.json()
        assert job["source_name"] == "safe.mp4" and job["status"] == "queued"
        assert client.post(f"/api/jobs/{job['id']}/start").status_code == 503
        assert client.get(f"/api/jobs/{job['id']}/files").json() == []
        assert client.get(f"/api/jobs/{job['id']}/files/final.mp4").status_code == 404
        assert (
            client.post(
                "/api/jobs", json={"source_type": "local", "source_file": str(uuid4())}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/jobs", json={"source_type": "url", "source_url": "file:///tmp/a.mp4"}
            ).status_code
            == 422
        )
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
        assert client.get(f"/api/jobs/{job['id']}").status_code == 404
        png = io.BytesIO()
        Image.new("RGBA", (20, 20)).save(png, format="PNG")
        assert (
            client.post(
                "/api/uploads?kind=watermark", files={"file": ("a.png", png.getvalue())}
            ).status_code
            == 201
        )
