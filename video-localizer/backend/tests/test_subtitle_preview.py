from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.paths import JobPaths
from app.main import create_app
from app.schemas.jobs import JobCreate, JobStatus


def test_preview_not_available_for_unfinished_job(tmp_path):
    settings = Settings(
        _env_file=None,
        workspace_dir=tmp_path,
        ffmpeg_path="missing",
        ffprobe_path="missing",
        ytdlp_path="missing",
    )
    with TestClient(create_app(settings)) as client:
        job = client.post(
            "/api/jobs", json={"source_type": "url", "source_url": "https://example.com/video.mp4"}
        ).json()
        assert client.get(f"/api/jobs/{job['id']}/subtitle.vtt").status_code == 404


def test_real_ffmpeg_webvtt_preview(tmp_path):
    # Only FFmpeg runs: no model or translation fixtures are claimed as engine proof.
    import shutil

    import pytest

    settings = Settings(workspace_dir=tmp_path)
    if not shutil.which(settings.ffmpeg_path):
        pytest.skip("FFmpeg required for actual subtitle conversion")
    with TestClient(create_app(settings)) as client:
        paths = JobPaths.create(tmp_path)
        config = JobCreate(source_type="local", source_file=uuid4())
        client.app.state.store.create(paths.id, config, "example.mp4")
        subtitle = paths.root / "final/subtitle.srt"
        subtitle.write_text(
            "1\n00:00:01,250 --> 00:00:03,000\nXin chào Việt Nam\n", encoding="utf-8"
        )
        client.app.state.store.stage(paths.id, JobStatus.completed, 100, "done")
        response = client.get(f"/api/jobs/{paths.id}/subtitle.vtt")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/vtt")
        assert response.text.startswith("WEBVTT")
        assert "00:01.250 --> 00:03.000" in response.text
        assert "Xin chào Việt Nam" in response.text
        assert "content-disposition" not in response.headers
        cached = paths.root / "postprocess/player/subtitle.vtt"
        previous = cached.stat().st_mtime_ns
        assert client.get(f"/api/jobs/{paths.id}/subtitle.vtt").text == response.text
        assert cached.stat().st_mtime_ns == previous
        assert [file["name"] for file in client.get(f"/api/jobs/{paths.id}/files").json()] == [
            "subtitle.srt"
        ]
