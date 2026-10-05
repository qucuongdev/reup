import json
import os
import re
import shutil
from pathlib import Path

from app.core.config import Settings
from app.core.paths import require_local_video
from app.core.process import PipelineError, ProcessRunner
from app.services.translator.base import TranslationConfig, TranslationResult


def subtitle_text(content: str) -> str:
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    lines: list[str] = []
    for block in blocks:
        parts = block.splitlines()
        timing = next((index for index, line in enumerate(parts) if "-->" in line), None)
        if timing is not None:
            lines.extend(parts[timing + 1 :])
    if not lines:
        raise PipelineError("Engine produced no translated subtitle cues")
    return "\n".join(lines) + "\n"


def normalize_output(raw: Path, output: Path, config: TranslationConfig) -> TranslationResult:
    # Select target-language subtitle explicitly, never fall back to source-language SRT.
    subtitles = list(raw.rglob(f"{config.target_language}.srt"))
    videos = [path for path in raw.rglob("*.mp4") if path.stat().st_size > 0]
    if len(subtitles) != 1 or len(videos) != 1:
        raise PipelineError(
            f"Ambiguous/missing engine artifacts: {len(videos)} videos, "
            f"{len(subtitles)} target SRTs "
            f"in {raw}. Expected one MP4 and {config.target_language}.srt; update adapter mapping."
        )
    text = subtitle_text(subtitles[0].read_text(encoding="utf-8-sig"))
    video, subtitle, transcript = (
        output / "translated_video.mp4",
        output / "subtitle.srt",
        output / "translated_text.txt",
    )
    shutil.copy2(videos[0], video)
    shutil.copy2(subtitles[0], subtitle)
    transcript.write_text(text, encoding="utf-8")
    return TranslationResult(video, subtitle, transcript, raw)


class PyVideoTransEngine:
    def __init__(self, settings: Settings, runner: ProcessRunner) -> None:
        self.settings, self.runner = settings, runner

    def build_command(self, input_video: Path, config: TranslationConfig, raw: Path) -> list[str]:
        root, python = self.settings.pyvideotrans_path, self.settings.pyvideotrans_python
        if not root or not (root / "cli.py").is_file() or not python or not python.is_file():
            raise PipelineError(
                "Set PYVIDEOTRANS_PATH and PYVIDEOTRANS_PYTHON to a working CLI installation"
            )
        if not config.voice.endswith("Neural") or config.voice == "No":
            raise PipelineError("MVP supports built-in Edge-TTS Neural voices only")
        command = [
            str(python),
            str(Path(__file__).with_name("bridge.py")),
            "--task",
            "vtv",
            "--name",
            str(input_video.resolve()),
            "--output-dir",
            str(raw.resolve()),
            "--source_language_code",
            config.source_language,
            "--target_language_code",
            config.target_language,
            "--recogn_type",
            str(self.settings.asr_provider),
            "--model_name",
            self.settings.asr_model,
            "--translate_type",
            str(self.settings.translation_provider),
            "--tts_type",
            str(self.settings.tts_provider),
            "--voice_role",
            config.voice,
            "--subtitle_type",
            "0",
            "--voice_autorate",
            "--video_autorate",
            "--no-clear-cache",
            "--log-level",
            "INFO",
        ]
        if self.settings.use_cuda:
            command.append("--cuda")
        return command

    def process(
        self, input_video: Path, config: TranslationConfig, output: Path
    ) -> TranslationResult:
        input_video = require_local_video(input_video)
        output.mkdir(parents=True, exist_ok=True)
        raw = output / "engine"
        raw.mkdir(exist_ok=False)  # Fresh attempt; stale artifacts cannot imply success.
        command = self.build_command(input_video, config, raw)
        env = os.environ.copy()
        env["LOCALIZER_ENGINE_ROOT"] = str(self.settings.pyvideotrans_path)
        env["LOCALIZER_ENGINE_OVERRIDES"] = json.dumps(self.settings.engine_overrides())
        env["LOCALIZER_ENGINE_EXECUTOR"] = self.settings.pyvideotrans_executor
        env["PYTHONUNBUFFERED"] = "1"
        # Let upstream subprocesses find configured FFmpeg/ffprobe too.
        media_dirs = [
            str(Path(p).resolve().parent)
            for p in (self.settings.ffmpeg_path, self.settings.ffprobe_path)
            if Path(p).is_file()
        ]
        env["PATH"] = os.pathsep.join(media_dirs + [env.get("PATH", "")])
        self.runner.run(command, "pyvideotrans-vtv", cwd=self.settings.pyvideotrans_path, env=env)
        return normalize_output(raw, output, config)
