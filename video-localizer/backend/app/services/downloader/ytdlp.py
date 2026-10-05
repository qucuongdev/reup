import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import Settings
from app.core.paths import write_json
from app.core.process import PipelineError, ProcessRunner
from app.services.downloader.base import DownloadResult


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise PipelineError("Source URL must be HTTP(S) without embedded credentials")
    return url


def source_metadata(info: dict, url: str) -> dict:
    return {
        key: info.get(key) for key in ("title", "description", "duration", "width", "height", "fps")
    } | {"source_url": url}


class YtDlpDownloader:
    def __init__(self, settings: Settings, runner: ProcessRunner) -> None:
        self.settings, self.runner = settings, runner

    def build_command(self, url: str, output: Path) -> list[str]:
        validate_url(url)
        return [
            self.settings.ytdlp_path,
            "--ignore-config",
            "--no-playlist",
            "--no-progress",
            "--write-info-json",
            "--no-simulate",
            "--no-overwrites",
            "--max-filesize",
            str(self.settings.max_download_bytes),
            "--match-filter",
            f"duration <=? {self.settings.max_video_seconds}",
            "--ffmpeg-location",
            shutil.which(self.settings.ffmpeg_path) or self.settings.ffmpeg_path,
            "--format",
            "bv*+ba/b",
            "--merge-output-format",
            "mp4",
            "--recode-video",
            "mp4",
            "--output",
            str(output / "source.%(ext)s"),
            "--",
            url,
        ]

    def download(self, url: str, output: Path) -> DownloadResult:
        output.mkdir(parents=True, exist_ok=True)
        self.runner.run(self.build_command(url, output), "downloading")
        video, raw = output / "source.mp4", output / "source.info.json"
        if not video.is_file() or not video.stat().st_size or not raw.is_file():
            raise PipelineError(
                "yt-dlp did not produce source.mp4/info JSON; source may exceed limits"
            )
        try:
            metadata = source_metadata(json.loads(raw.read_text(encoding="utf-8")), url)
        except (OSError, ValueError) as exc:
            raise PipelineError(f"Invalid yt-dlp metadata: {exc}") from exc
        target = output / "source_metadata.json"
        write_json(target, metadata)
        return DownloadResult(video, target, metadata)
