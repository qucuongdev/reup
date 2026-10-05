"""Real integration command. No simulated successful outputs."""

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.core.environment import check_environment
from app.core.paths import JobPaths, require_local_video, write_json
from app.core.process import JobLog, PipelineError, ProcessRunner
from app.services.downloader.ytdlp import YtDlpDownloader, validate_url
from app.services.probe import probe
from app.services.translator.base import TranslationConfig
from app.services.translator.pyvideotrans import PyVideoTransEngine


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local/URL → pyVideoTrans → Vietnamese")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--input", type=Path)
    source.add_argument("--url")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--source-language")
    parser.add_argument("--target-language")
    parser.add_argument("--voice")
    args = parser.parse_args()
    paths = None
    log = None
    try:
        settings = Settings()
        report = check_environment(settings, deep=True)
        if args.check:
            import json

            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 1
        if not args.input and not args.url:
            parser.error("--input or --url required unless --check")
        missing = [
            f"{c['name']}: {c['detail']} ({c['hint']})"
            for c in report["checks"]
            if not c["available"] and (args.url or c["name"] != "yt-dlp")
        ]
        if missing:
            raise PipelineError("Dependencies unavailable:\n" + "\n".join(missing))
        config = TranslationConfig(
            source_language=args.source_language or settings.default_source_language,
            target_language=args.target_language or settings.default_target_language,
            voice=args.voice or settings.default_voice,
        )
        if args.url:
            validate_url(args.url)
        else:
            require_local_video(args.input)
        paths = JobPaths.create(settings.workspace_dir)
        log = JobLog(paths.directory("logs"), (settings.translation_api_key.get_secret_value(),))
        runner = ProcessRunner(log, settings.process_timeout_seconds)
        if args.url:
            downloaded = YtDlpDownloader(settings, runner).download(
                args.url, paths.directory("source")
            )
            video = downloaded.video
        else:
            original = require_local_video(args.input)
            video = paths.directory("source") / ("source" + original.suffix.lower())
            shutil.copy2(original, video)
        source_info = probe(video, settings.ffprobe_path, runner)
        if source_info["duration"] > settings.max_video_seconds:
            raise PipelineError("Input duration exceeds MAX_VIDEO_SECONDS")
        if video.stat().st_size > settings.max_download_bytes:
            raise PipelineError("Input file exceeds MAX_DOWNLOAD_BYTES")
        if not source_info["has_audio"]:
            raise PipelineError("Input has no audio for speech recognition")
        if not args.url:
            write_json(paths.directory("source") / "source_metadata.json", source_info)
        log.write(
            "pyvideotrans-vtv", "Delegating ASR, translation, TTS and assembly to external CLI"
        )
        result = PyVideoTransEngine(settings, runner).process(
            video, config, paths.directory("translation")
        )
        output_info = probe(result.video, settings.ffprobe_path, runner)
        if not output_info["has_audio"] or output_info["duration"] <= 0:
            raise PipelineError("Engine output has no audio or valid duration")
        write_json(
            paths.root / "integration_result.json",
            {
                "id": paths.id,
                "status": "engine_succeeded",
                "created_at": datetime.now(UTC).isoformat(),
                "config": config.model_dump(),
                "engine": {
                    "name": "pyVideoTrans",
                    "executor": settings.pyvideotrans_executor,
                    "asr_provider": settings.asr_provider,
                    "asr_model": settings.asr_model,
                    "translation_provider": settings.translation_provider,
                    "tts_provider": settings.tts_provider,
                },
                "source_url": args.url,
                "source": source_info,
                "output": output_info,
                "artifacts": {
                    "video": str(result.video),
                    "subtitle": str(result.subtitle),
                    "text": str(result.text),
                },
                "verification": (
                    "Artifact/media checks passed; human Vietnamese listening check required"
                ),
                "acceptance_criteria_met": False,
            },
        )
        log.write("engine_succeeded", "Engine artifacts validated; final rendering stages pending")
        print(f"Engine integration succeeded: {paths.root}")
        return 0
    except (PipelineError, ValidationError, OSError, ValueError) as exc:
        message = (
            str(exc.errors(include_input=False)) if isinstance(exc, ValidationError) else str(exc)
        )
        if log:
            message = log.redact(message)
            log.write("failed", message, "ERROR")
        if paths:
            write_json(
                paths.root / "integration_result.json", {"status": "failed", "error": message}
            )
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
