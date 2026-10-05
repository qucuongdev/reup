import sys

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.process import JobLog, PipelineError, ProcessRunner
from app.services.translator.base import TranslationConfig
from app.services.translator.pyvideotrans import PyVideoTransEngine, normalize_output, subtitle_text


def test_real_cli_command_contract(tmp_path):
    (tmp_path / "cli.py").touch()
    settings = Settings(
        _env_file=None,
        pyvideotrans_path=tmp_path,
        pyvideotrans_python=sys.executable,
        translation_provider=4,
    )
    engine = PyVideoTransEngine(settings, ProcessRunner(JobLog(tmp_path / "logs")))
    command = engine.build_command(tmp_path / "source.mp4", TranslationConfig(), tmp_path / "raw")
    assert command[command.index("--task") + 1] == "vtv"
    assert command[command.index("--target_language_code") + 1] == "vi"
    assert command[command.index("--translate_type") + 1] == "4"
    assert command[command.index("--tts_type") + 1] == "0"
    assert "--no-clear-cache" in command
    assert "--cuda" not in command


def test_normalization_selects_target_not_source(tmp_path):
    raw = tmp_path / "engine"
    raw.mkdir()
    (raw / "source.mp4").write_bytes(b"fixture-not-real-video")
    (raw / "zh-cn.srt").write_text("source", encoding="utf-8")
    (raw / "vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào\n", encoding="utf-8")
    result = normalize_output(raw, tmp_path, TranslationConfig())
    assert result.text.read_text(encoding="utf-8") == "Xin chào\n"
    assert result.video.name == "translated_video.mp4"


def test_source_only_and_ambiguous_outputs_fail(tmp_path):
    (tmp_path / "one.mp4").write_bytes(b"fixture")
    (tmp_path / "zh-cn.srt").write_text("source")
    with pytest.raises(PipelineError, match="target SRTs"):
        normalize_output(tmp_path, tmp_path, TranslationConfig())
    (tmp_path / "vi.srt").write_text("1\n0 --> 1\nXin chào", encoding="utf-8")
    (tmp_path / "two.mp4").write_bytes(b"fixture")
    with pytest.raises(PipelineError, match="Ambiguous"):
        normalize_output(tmp_path, tmp_path, TranslationConfig())


def test_subtitle_text_rejects_empty_cues():
    with pytest.raises(PipelineError):
        subtitle_text("not a subtitle")
    assert subtitle_text("1\r\n0 --> 1\r\nLine 1\r\nLine 2\r\n") == "Line 1\nLine 2\n"


def test_language_validation():
    with pytest.raises(ValidationError):
        TranslationConfig(target_language="--exec evil")
