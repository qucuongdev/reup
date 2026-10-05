import os
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.process import JobLog, ProcessRunner
from app.main import create_app
from app.schemas.jobs import JobCreate
from app.services.downloader.ytdlp import YtDlpDownloader
from app.services.probe import probe
from app.services.renderer.ffmpeg import FFmpegRenderer


@pytest.mark.integration
def test_real_chinese_to_vietnamese_pipeline():
    video = os.environ.get("LOCALIZER_TEST_VIDEO")
    if not video:
        pytest.skip("Set LOCALIZER_TEST_VIDEO to a rights-cleared spoken Chinese clip")
    result = subprocess.run(
        [sys.executable, "-m", "app.smoke", "--input", video],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=Path(__file__).resolve().parents[1],
        timeout=14400,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.integration
def test_real_http_video_download(tmp_path):
    video_value = os.environ.get("LOCALIZER_TEST_VIDEO")
    if not video_value:
        pytest.skip("Set LOCALIZER_TEST_VIDEO to a rights-cleared video file")
    video = Path(video_value).resolve()
    assert video.is_file()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(video.parent))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/{quote(video.name)}"
        settings = Settings()
        result = YtDlpDownloader(settings, ProcessRunner(JobLog(tmp_path / "logs"))).download(
            url, tmp_path / "source"
        )
        assert result.video.read_bytes() == video.read_bytes()
        assert result.metadata_file.is_file()
        assert result.metadata["source_url"] == url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.integration
def test_real_url_job_full_pipeline(tmp_path):
    value = os.environ.get("LOCALIZER_TEST_VIDEO")
    if not value:
        pytest.skip("Set LOCALIZER_TEST_VIDEO to a rights-cleared spoken Chinese clip")
    video = Path(value).resolve()
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(video.parent))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TestClient(create_app(Settings(workspace_dir=tmp_path))) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "source_type": "url",
                    "source_url": f"http://127.0.0.1:{server.server_port}/{quote(video.name)}",
                    "output_ratio": "16:9",
                    "fit_mode": "pad",
                    "thumbnail_mode": "timestamp",
                    "thumbnail_timestamp": 1,
                },
            )
            assert response.status_code == 201
            identifier = response.json()["id"]
            assert client.post(f"/api/jobs/{identifier}/start").status_code == 202
            assert client.post(f"/api/jobs/{identifier}/start").status_code == 409
            assert client.delete(f"/api/jobs/{identifier}").status_code == 409
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                job = client.get(f"/api/jobs/{identifier}").json()
                if job["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.5)
            assert job["status"] == "completed", job.get("error")
            assert job["progress"] == 100
            files = client.get(f"/api/jobs/{identifier}/files").json()
            assert {f["name"] for f in files} == {
                "final.mp4",
                "thumbnail.jpg",
                "subtitle.srt",
                "metadata.json",
            }
            for file in files:
                download = client.get(file["url"])
                assert download.status_code == 200 and len(download.content) == file["size"]
            metadata = client.get(f"/api/jobs/{identifier}/files/metadata.json").json()
            assert metadata["output"]["width"] == 1920
            assert metadata["output"]["height"] == 1080
            assert metadata["output"]["has_audio"]
            logs = client.get(f"/api/jobs/{identifier}/logs?limit=500").json()
            for step in ["transcribing", "translating", "dubbing", "rendering", "done"]:
                assert any(record["step"] == step for record in logs)
            ranges = client.get(
                f"/api/jobs/{identifier}/files/final.mp4", headers={"Range": "bytes=0-31"}
            )
            assert ranges.status_code == 206 and len(ranges.content) == 32
            assert client.post(f"/api/jobs/{identifier}/retry").status_code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.integration
@pytest.mark.parametrize(
    "ratio,mode,expected",
    [
        ("original", "crop", (640, 360)),
        ("1:1", "crop", (1080, 1080)),
        ("1:1", "pad", (1080, 1080)),
        ("9:16", "pad", (1080, 1920)),
    ],
)
def test_real_ffmpeg_ratios(tmp_path, ratio, mode, expected):
    video = os.environ.get("LOCALIZER_TEST_VIDEO")
    if not video:
        pytest.skip("Set LOCALIZER_TEST_VIDEO for real FFmpeg checks")
    settings = Settings()
    runner = ProcessRunner(JobLog(tmp_path / "logs"))
    short = tmp_path / "source.mp4"
    runner.run(
        [
            settings.ffmpeg_path,
            "-nostdin",
            "-y",
            "-i",
            video,
            "-t",
            "0.4",
            "-c",
            "copy",
            str(short),
        ],
        "fixture-trim",
    )
    config = JobCreate(
        source_type="local",
        source_file=uuid4(),
        output_ratio=ratio,
        fit_mode=mode,
        subtitle_enabled=False,
        thumbnail_enabled=False,
    )
    final = tmp_path / "final.mp4"
    FFmpegRenderer(settings, runner).render(short, final, config, 640, tmp_path)
    metadata = probe(final, settings.ffprobe_path, runner)
    assert (metadata["width"], metadata["height"]) == expected
    assert metadata["has_audio"] and metadata["duration"] > 0


@pytest.mark.integration
def test_real_worker_failure_retry_keeps_source(tmp_path):
    settings = Settings(workspace_dir=tmp_path)
    if not settings.pyvideotrans_path:
        pytest.skip("Configure external dependencies for real API worker verification")
    with TestClient(create_app(settings)) as client:
        upload = client.post("/api/uploads", files={"file": ("broken.mp4", b"not a video")})
        assert upload.status_code == 201
        job = client.post(
            "/api/jobs", json={"source_type": "local", "source_file": upload.json()["id"]}
        ).json()
        identifier = job["id"]
        for attempt, endpoint in [(1, "start"), (2, "retry")]:
            assert client.post(f"/api/jobs/{identifier}/{endpoint}").status_code == 202
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                job = client.get(f"/api/jobs/{identifier}").json()
                if job["status"] == "failed":
                    break
                time.sleep(0.1)
            assert job["status"] == "failed"
            assert job["attempt"] == attempt and "probe exited" in job["error"]
            assert (
                tmp_path / "jobs" / identifier / "source/source.mp4"
            ).read_bytes() == b"not a video"
            assert client.get(f"/api/jobs/{identifier}/files").json() == []
        records = client.get(f"/api/jobs/{identifier}/logs").json()
        assert any("return_code=" in record["message"] for record in records)
        assert any(record["level"] == "ERROR" for record in records)
