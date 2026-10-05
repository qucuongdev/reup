from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.core.process import JobLog, ProcessRunner


def preview_subtitle(root: Path, settings: Settings) -> Path:
    """Convert existing SRT using FFmpeg; keep browser-only cache outside final outputs."""
    directory = root / "postprocess" / "player"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "subtitle.vtt"
    if target.is_file():
        return target
    pending = directory / f"{uuid4()}.vtt"
    runner = ProcessRunner(
        JobLog(root / "logs", (settings.translation_api_key.get_secret_value(),)), 30
    )
    try:
        runner.run(
            [
                settings.ffmpeg_path,
                "-nostdin",
                "-hide_banner",
                "-y",
                "-i",
                str(root / "final" / "subtitle.srt"),
                "-f",
                "webvtt",
                str(pending),
            ],
            "subtitle-preview",
        )
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return target
