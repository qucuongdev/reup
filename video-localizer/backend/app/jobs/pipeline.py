import json
import shutil
from datetime import UTC, datetime

from PIL import Image

from app.core.config import Settings
from app.core.paths import JobPaths, write_json
from app.core.process import JobLog, PipelineError, ProcessRunner
from app.models.store import JobStore
from app.schemas.jobs import JobCreate, JobStatus
from app.services.downloader.ytdlp import YtDlpDownloader
from app.services.postprocess.processor import RESOLUTIONS, prepare_font
from app.services.probe import probe
from app.services.renderer.ffmpeg import FFmpegRenderer
from app.services.thumbnail.generator import ThumbnailGenerator
from app.services.translator.pyvideotrans import PyVideoTransEngine
from app.services.uploads import UploadStore

OUTPUT_NAMES = ("final.mp4", "thumbnail.jpg", "subtitle.srt", "metadata.json")


class Pipeline:
    def __init__(self, settings: Settings, store: JobStore):
        self.settings, self.store = settings, store

    def process(self, job_id: str) -> None:
        job = self.store.get(job_id)
        settings = self.settings
        paths = JobPaths(job_id, settings.workspace_dir / "jobs" / job_id)
        log = JobLog(paths.directory("logs"), (settings.translation_api_key.get_secret_value(),))

        def stage(status: str, progress: int, step: str | None = None):
            self.store.stage(job_id, JobStatus(status), progress, step or status)
            log.write(step or status, f"Stage entered; completed work={progress}%")

        def event(stream: str, line: str):
            if stream == "stdout" and line.startswith("LOCALIZER_STAGE "):
                name = json.loads(line[len("LOCALIZER_STAGE ") :])["stage"]
                stage(name, {"transcribing": 14, "translating": 28, "dubbing": 42}[name])

        runner = ProcessRunner(log, settings.process_timeout_seconds, event)
        uploads = UploadStore(settings.workspace_dir)
        try:
            source_dir = paths.directory("source")
            existing = list(source_dir.glob("source.*"))
            existing = [p for p in existing if p.suffix in {".mp4", ".mov", ".mkv", ".webm"}]
            if existing:
                source = existing[0]
            elif job.source_type == "url":
                stage("downloading", 0)
                source = (
                    YtDlpDownloader(settings, runner).download(job.source_url, source_dir).video
                )
            else:
                uploaded, _ = uploads.resolve(job.source_file, "video")
                source = source_dir / ("source" + uploaded.suffix)
                pending = source_dir / "upload.pending"
                shutil.copy2(uploaded, pending)
                pending.replace(source)
            source_info = probe(source, settings.ffprobe_path, runner)
            if (
                not source_info["has_audio"]
                or not 0 < source_info["duration"] <= settings.max_video_seconds
            ):
                raise PipelineError(
                    "Source must contain audio and have duration within MAX_VIDEO_SECONDS"
                )
            if source.stat().st_size > settings.max_download_bytes:
                raise PipelineError("Source exceeds MAX_DOWNLOAD_BYTES")
            metadata_source = source_dir / "source_metadata.json"
            if not metadata_source.exists():
                write_json(
                    metadata_source,
                    source_info | {"title": job.source_name, "source_url": job.source_url},
                )
            translation_dir = paths.directory("translation") / f"attempt-{job.attempt}"
            result = PyVideoTransEngine(settings, runner).process(source, job, translation_dir)
            translated = probe(result.video, settings.ffprobe_path, runner)
            if not translated["has_audio"]:
                raise PipelineError("Translation engine output has no audio")
            stage("postprocessing", 57)
            directory = paths.directory("postprocess") / f"attempt-{job.attempt}"
            directory.mkdir()
            staging = directory / "final"
            staging.mkdir()
            if job.burn_subtitle:
                shutil.copy2(result.subtitle, directory / "subtitle.srt")
            if job.burn_subtitle or job.thumbnail_title:
                prepare_font(settings, directory)
            if job.watermark_enabled or job.thumbnail_branding:
                watermark, _ = uploads.resolve(job.watermark_file, "watermark")
                saved = source_dir / "watermark.png"
                if not saved.exists():
                    shutil.copy2(watermark, saved)
                shutil.copy2(saved, directory / "watermark.png")
            stage("rendering", 71)
            final = staging / "final.mp4"
            FFmpegRenderer(settings, runner).render(
                result.video,
                final,
                job,
                translated["width"],
                directory,
                source_height=translated["height"],
            )
            output_info = probe(final, settings.ffprobe_path, runner)
            expected = RESOLUTIONS.get(job.output_ratio)
            if (
                not output_info["has_audio"]
                or output_info["duration"] <= 0
                or (expected and expected != (output_info["width"], output_info["height"]))
            ):
                raise PipelineError("Rendered output failed stream/dimension validation")
            if job.subtitle_enabled:
                shutil.copy2(result.subtitle, staging / "subtitle.srt")
            if job.thumbnail_enabled:
                stage("rendering", 85, "thumbnail")
                ThumbnailGenerator(settings, runner).generate(
                    final, staging / "thumbnail.jpg", output_info["duration"], job, directory
                )
                with Image.open(staging / "thumbnail.jpg") as image:
                    if image.size != (1280, 720) or image.format != "JPEG":
                        raise PipelineError("Invalid thumbnail dimensions/format")
            metadata = {
                "job_id": job_id,
                "attempt": job.attempt,
                "completed_at": datetime.now(UTC).isoformat(),
                "config": job.model_dump(mode="json", include=set(JobCreate.model_fields)),
                "source": json.loads(metadata_source.read_text(encoding="utf-8")),
                "output": output_info,
                "engine": {
                    "name": "pyVideoTrans",
                    "asr_model": settings.asr_model,
                    "translation_provider": settings.translation_provider,
                    "tts_provider": settings.tts_provider,
                },
                "files": [p.name for p in staging.iterdir()] + ["metadata.json"],
            }
            write_json(staging / "metadata.json", metadata)
            for file in staging.iterdir():
                file.replace(paths.directory("final") / file.name)
            stage("completed", 100, "done")
        except Exception as exc:
            message = log.redact(str(exc))
            log.write("failed", message, "ERROR")
            self.store.fail(job_id, message)
