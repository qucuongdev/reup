from pathlib import Path

from app.core.config import Settings
from app.core.process import ProcessRunner
from app.schemas.jobs import JobCreate
from app.services.postprocess.processor import RESOLUTIONS, VideoProcessor


class FFmpegRenderer:
    def __init__(self, settings: Settings, runner: ProcessRunner):
        self.settings, self.runner = settings, runner

    def build_command(
        self,
        video: Path,
        output: Path,
        config: JobCreate,
        source_width: int,
        source_height: int = 360,
    ) -> list[str]:
        processor = VideoProcessor()
        command = [self.settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y", "-i", str(video)]
        filters = processor.resize(config.output_ratio, config.fit_mode)
        if config.burn_subtitle:
            width, height = RESOLUTIONS.get(config.output_ratio, (source_width, source_height))
            filters += "," + processor.burn_subtitle(width, height)
        if config.watermark_enabled:
            command += ["-loop", "1", "-i", "watermark.png"]
            width = RESOLUTIONS.get(config.output_ratio, (source_width, 0))[0]
            command += [
                "-filter_complex",
                f"[0:v]{filters}[base];" + processor.add_watermark(config, width),
                "-map",
                "[out]",
            ]
        else:
            command += ["-vf", filters, "-map", "0:v:0"]
        command += ["-map", "0:a:0"]
        if config.normalize_audio:
            command += ["-af", processor.normalize_audio()]
        return command + [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]

    def render(
        self,
        video: Path,
        output: Path,
        config: JobCreate,
        source_width: int,
        directory: Path,
        source_height: int = 360,
    ) -> None:
        self.runner.run(
            self.build_command(video, output, config, source_width, source_height),
            "rendering",
            cwd=directory,
        )
