import json
from fractions import Fraction
from pathlib import Path

from app.core.process import PipelineError, ProcessRunner


def media_metadata(data: dict) -> dict:
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not video:
        raise PipelineError("Input/output has no video stream")
    try:
        fps = float(Fraction(video.get("avg_frame_rate", "0/1")))
    except (ValueError, ZeroDivisionError):
        fps = None
    return {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": fps,
        "has_audio": audio is not None,
    }


def probe(video: Path, ffprobe: str, runner: ProcessRunner) -> dict:
    result = runner.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,avg_frame_rate:format=duration",
            "-of",
            "json",
            str(video),
        ],
        "probe",
    )
    try:
        return media_metadata(json.loads(result.stdout))
    except (ValueError, TypeError) as exc:
        raise PipelineError(f"Invalid ffprobe metadata for {video}: {exc}") from exc
