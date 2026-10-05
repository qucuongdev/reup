import json
import math
import re
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.paths import write_json
from app.core.process import JobLog, PipelineError, ProcessRunner
from app.models.editor import EditorStore
from app.models.store import JobStore
from app.schemas.editor import Clip
from app.services.probe import probe
from app.services.thumbnail.generator import ThumbnailGenerator

FPS = 30


def clip_duration(clip: Clip) -> float:
    return math.floor((clip.end - clip.start) * FPS + 1e-6) / FPS


def stamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def trim_subtitle(
    content: str, start: float, end: float, offset: float
) -> list[tuple[float, float, str]]:
    result = []
    for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        match = re.fullmatch(
            r"\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})(?:\s+.*)?",
            lines[timing],
        )
        if not match:
            raise PipelineError("Invalid subtitle timing in editor source")
        values = [int(value) for value in match.groups()]
        left = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        right = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        text = "\n".join(lines[timing + 1 :]).strip()
        left, right = max(left, start), min(right, end)
        if right > left and text:
            result.append((offset + left - start, offset + right - start, text))
    return result


class EditorService:
    def __init__(self, settings: Settings, jobs: JobStore, store: EditorStore):
        self.settings, self.jobs, self.store = settings, jobs, store

    def root(self, job_id: str) -> Path:
        root = self.settings.workspace_dir.resolve() / "jobs"
        target = (root / str(UUID(job_id))).resolve()
        if not target.is_relative_to(root):
            raise PipelineError("Invalid editor source path")
        return target

    def media(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        root = self.root(job_id)
        if job.status != "completed" or not (root / "final/final.mp4").is_file():
            raise PipelineError("Editor sources must be completed videos")
        try:
            output = json.loads((root / "final/metadata.json").read_text(encoding="utf-8"))[
                "output"
            ]
            duration = float(output["duration"])
            width, height = int(output["width"]), int(output["height"])
            if not math.isfinite(duration) or duration <= 0 or min(width, height) < 2:
                raise ValueError("Invalid duration/dimensions")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PipelineError("Video metadata unavailable or invalid") from exc
        return {
            "id": job_id,
            "name": job.source_name,
            "duration": duration,
            "width": width,
            "height": height,
            "target_language": job.target_language,
            "burn_subtitle": job.burn_subtitle,
            "subtitle": (root / "final/subtitle.srt").is_file(),
            "thumbnail": f"/api/jobs/{job_id}/files/thumbnail.jpg"
            if (root / "final/thumbnail.jpg").is_file()
            else None,
        }

    def validate(self, clips: list[Clip]):
        total = 0.0
        for clip in clips:
            media = self.media(str(clip.job_id))
            if clip.end > media["duration"] + 0.001:
                raise PipelineError("Clip extends beyond source duration")
            total += clip_duration(clip)
        if total > self.settings.max_video_seconds:
            raise PipelineError("Timeline exceeds MAX_VIDEO_SECONDS")

    def draft(self, job_id: str) -> dict:
        media = self.media(job_id)
        return self.store.draft(job_id) or {
            "revision": 0,
            "clips": [{"id": str(uuid4()), "job_id": job_id, "start": 0, "end": media["duration"]}],
        }

    def export_root(self, export: dict) -> Path:
        root = self.root(export["job_id"])
        target = (root / "editor/exports" / str(UUID(export["id"]))).resolve()
        if not target.is_relative_to(root):
            raise PipelineError("Invalid export path")
        return target

    def process(self, identifier: str):
        export = self.store.export(identifier)
        log = None
        try:
            root = self.export_root(export)
            log = JobLog(root / "logs", (self.settings.translation_api_key.get_secret_value(),))
            runner = ProcessRunner(log, self.settings.process_timeout_seconds)
            clips = [Clip.model_validate(clip) for clip in export["plan"]["clips"]]
            self.validate(clips)
            media = self.media(export["job_id"])
            width, height = media["width"], media["height"]
            work, final = root / "postprocess", root / "final"
            work.mkdir(parents=True, exist_ok=False)
            final.mkdir()
            subtitles, offset, inputs = [], 0.0, []
            count = len(clips)
            for index, clip in enumerate(clips):
                step = f"clip-{index + 1}-of-{count}"
                self.store.update(identifier, "rendering", round(index / (count + 2) * 100), step)
                source = self.root(str(clip.job_id)) / "final"
                length = clip_duration(clip)
                frames = round(length * FPS)
                output = work / f"clip-{index:03}.mkv"
                # Uniform H.264 + PCM intermediates avoid repeated AAC encoder delay.
                # Only final mux encodes AAC. Duration is quantized to the 30fps frame grid.
                filters = (
                    f"fps={FPS},tpad=stop_mode=clone:stop_duration=0.1,"
                    f"trim=end_frame={frames},setpts=N/({FPS}*TB),"
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
                )
                runner.run(
                    [
                        self.settings.ffmpeg_path,
                        "-nostdin",
                        "-hide_banner",
                        "-y",
                        "-ss",
                        str(clip.start),
                        "-i",
                        str(source / "final.mp4"),
                        "-t",
                        str(length),
                        "-map",
                        "0:v:0",
                        "-map",
                        "0:a:0",
                        "-vf",
                        filters,
                        "-af",
                        f"aresample=48000,apad,atrim=end_sample={frames * 1600},asetpts=N/SR/TB",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "20",
                        "-bf",
                        "0",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "pcm_s16le",
                        "-ar",
                        "48000",
                        "-ac",
                        "2",
                        str(output),
                    ],
                    step,
                )
                inputs += [f"file '{output.name}'", f"duration {length:.9f}"]
                if (source / "subtitle.srt").is_file():
                    subtitles += trim_subtitle(
                        (source / "subtitle.srt").read_text(encoding="utf-8-sig"),
                        clip.start,
                        clip.start + length,
                        offset,
                    )
                offset += length
            self.store.update(identifier, "rendering", round(count / (count + 2) * 100), "joining")
            (work / "concat.txt").write_text("\n".join(inputs) + "\n", encoding="utf-8")
            runner.run(
                [
                    self.settings.ffmpeg_path,
                    "-nostdin",
                    "-hide_banner",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "1",
                    "-i",
                    "concat.txt",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                    str(final / "final.mp4"),
                ],
                "joining",
                cwd=work,
            )
            info = probe(final / "final.mp4", self.settings.ffprobe_path, runner)
            if (
                not info["has_audio"]
                or abs(info["duration"] - offset) > max(0.15, count * 0.02)
                or (info["width"], info["height"]) != (width, height)
                or info["fps"] != FPS
            ):
                raise PipelineError("Edited output failed duration/audio validation")
            (final / "subtitle.srt").write_text(
                "".join(
                    f"{i + 1}\n{stamp(left)} --> {stamp(right)}\n{text}\n\n"
                    for i, (left, right, text) in enumerate(subtitles)
                ),
                encoding="utf-8",
            )
            self.store.update(
                identifier, "rendering", round((count + 1) / (count + 2) * 100), "thumbnail"
            )
            config = self.jobs.get(export["job_id"]).model_copy(
                update={
                    "thumbnail_mode": "auto",
                    "thumbnail_title": "",
                    "thumbnail_branding": False,
                }
            )
            ThumbnailGenerator(self.settings, runner).generate(
                final / "final.mp4", final / "thumbnail.jpg", info["duration"], config, work
            )
            write_json(
                final / "metadata.json",
                {
                    "export_id": identifier,
                    "job_id": export["job_id"],
                    "plan": export["plan"],
                    "output": info,
                    "planned_duration": offset,
                    "fps": FPS,
                    "subtitle_cues": len(subtitles),
                    "contains_burned_subtitles": any(
                        self.jobs.get(str(c.job_id)).burn_subtitle for c in clips
                    ),
                    "files": ["final.mp4", "subtitle.srt", "thumbnail.jpg", "metadata.json"],
                },
            )
            self.store.update(identifier, "completed", 100, "done")
            log.write("done", "Timeline export completed; originals preserved")
        except Exception as exc:
            message = str(exc)
            secret = self.settings.translation_api_key.get_secret_value()
            if secret:
                message = message.replace(secret, "[REDACTED]")
            if log:
                log.write("failed", message, "ERROR")
            self.store.update(identifier, "failed", 0, "failed", message)
