import textwrap
from pathlib import Path

from app.core.config import Settings
from app.core.process import PipelineError, ProcessRunner
from app.schemas.jobs import JobCreate


class ThumbnailGenerator:
    def __init__(self, settings: Settings, runner: ProcessRunner):
        self.settings, self.runner = settings, runner

    def generate(
        self, video: Path, output: Path, duration: float, config: JobCreate, directory: Path
    ) -> None:
        timestamp = (
            duration * 0.3 if config.thumbnail_mode == "auto" else config.thumbnail_timestamp
        )
        if timestamp >= duration:
            raise PipelineError("Thumbnail timestamp must be smaller than video duration")
        filters = (
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
        command = [
            self.settings.ffmpeg_path,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(video),
        ]
        if config.thumbnail_title:
            (directory / "title.txt").write_text(
                "\n".join(textwrap.wrap(config.thumbnail_title, 42)), encoding="utf-8"
            )
            filters += ":".join(
                [
                    ",drawtext=fontfile=font.ttf",
                    "textfile=title.txt",
                    "expansion=none",
                    "fontsize=38",
                    "fontcolor=white",
                    "box=1",
                    "boxcolor=black@0.65",
                    "boxborderw=16",
                    "x=40",
                    "y=40",
                ]
            )
        if config.thumbnail_branding:
            command += [
                "-i",
                "watermark.png",
                "-filter_complex",
                f"[0:v]{filters}[base];[1:v]scale=180:-1[wm];[base][wm]overlay=W-w-24:24[out]",
                "-map",
                "[out]",
            ]
        else:
            command += ["-vf", filters]
        command += ["-frames:v", "1", "-q:v", "2", str(output)]
        self.runner.run(command, "thumbnail", cwd=directory)
