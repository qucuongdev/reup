from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings
from app.core.paths import JobPaths, require_local_video
from app.core.process import PipelineError


def test_paths_are_repo_relative_not_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, workspace_dir="workspace")
    assert settings.workspace_dir == REPO_ROOT / "workspace"


def test_secret_and_configuration_validation():
    settings = Settings(
        _env_file=None, translation_api_key="secret-value", translation_api_key_field="chatgpt_key"
    )
    assert "secret-value" not in repr(settings)
    assert settings.engine_overrides() == {"chatgpt_key": "secret-value"}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, translation_api_key="secret-value")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, tts_provider=1)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, process_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, pyvideotrans_executor="thread", use_cuda=True)


def test_job_paths_reject_traversal_and_reuse(tmp_path):
    with pytest.raises(ValueError):
        JobPaths.create(tmp_path, "../../outside")
    paths = JobPaths.create(tmp_path)
    assert paths.directory("source").is_dir()
    with pytest.raises(FileExistsError):
        JobPaths.create(tmp_path, paths.id)
    with pytest.raises(PipelineError):
        paths.directory("../outside")


@pytest.mark.parametrize("filename", ["missing.mp4", "empty.mp4", "file.exe"])
def test_invalid_local_video(tmp_path, filename):
    path = tmp_path / filename
    if filename != "missing.mp4":
        path.touch()
    with pytest.raises(PipelineError):
        require_local_video(path)


def test_supported_video(tmp_path):
    path = tmp_path / "demo.MOV"
    path.write_bytes(b"fixture")
    assert require_local_video(path) == Path(path).resolve()
