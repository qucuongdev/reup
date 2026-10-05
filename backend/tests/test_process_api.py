import json
import sys

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.environment import check_environment
from app.core.process import JobLog, PipelineError, ProcessRunner
from app.main import create_app


def test_real_subprocess_capture_and_redaction(tmp_path):
    log = JobLog(tmp_path, ("secret-value",))
    runner = ProcessRunner(log)
    result = runner.run(
        [sys.executable, "-c", "import sys; print('secret-value'); print('err', file=sys.stderr)"],
        "test",
    )
    assert result.return_code == 0
    assert result.stdout == "[REDACTED]"
    assert result.stderr == "err"
    contents = log.path.read_text(encoding="utf-8")
    assert "secret-value" not in contents
    assert all("timestamp" in json.loads(line) for line in contents.splitlines())


def test_real_subprocess_preserves_chinese_and_vietnamese(tmp_path):
    runner = ProcessRunner(JobLog(tmp_path))
    result = runner.run([sys.executable, "-c", "print('Xin chào 中文')"], "unicode")
    assert result.stdout == "Xin chào 中文"


def test_real_subprocess_failure_timeout_and_missing_executable(tmp_path):
    runner = ProcessRunner(JobLog(tmp_path), timeout=1)
    with pytest.raises(PipelineError, match="exited 7"):
        runner.run([sys.executable, "-c", "import sys; sys.exit(7)"], "failure")
    with pytest.raises(PipelineError, match="timed out"):
        runner.run([sys.executable, "-c", "import time; time.sleep(10)"], "slow")
    with pytest.raises(PipelineError, match="Cannot start"):
        runner.run(["nonexistent-localizer-command"], "missing")


def test_environment_and_api_handle_missing_dependencies(tmp_path):
    settings = Settings(
        _env_file=None,
        workspace_dir=tmp_path,
        ffmpeg_path="nonexistent-ffmpeg",
        ffprobe_path="nonexistent-ffprobe",
        ytdlp_path="nonexistent-ytdlp",
    )
    report = check_environment(settings)
    assert report["ready"] is False
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").json()["pipeline_ready"] is False
        assert len(client.get("/api/environment").json()["checks"]) == 5
        assert client.post("/api/jobs", json={}).status_code == 422
