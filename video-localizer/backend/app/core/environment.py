import os
import shutil
import sys

from app.core.config import Settings
from app.core.process import JobLog, PipelineError, ProcessRunner


def check_environment(settings: Settings, *, deep: bool = False) -> dict:
    """Startup probes are lightweight; deep CLI import/capability probe is explicit."""
    checks = [
        {
            "name": "python",
            "available": sys.version_info >= (3, 11),
            "detail": sys.version.split()[0],
            "hint": "Install Python 3.11+ for backend",
        }
    ]
    for name, command in (
        ("ffmpeg", settings.ffmpeg_path),
        ("ffprobe", settings.ffprobe_path),
        ("yt-dlp", settings.ytdlp_path),
    ):
        located = shutil.which(command)
        detail = located or command
        available = bool(located)
        if available:
            runner = ProcessRunner(JobLog(settings.workspace_dir / "diagnostics"), timeout=15)
            try:
                result = runner.run(
                    [command, "--version" if name == "yt-dlp" else "-version"], name
                )
                detail = result.stdout.splitlines()[0] if result.stdout else result.stderr[:200]
            except PipelineError as exc:
                available, detail = False, str(exc)
        checks.append(
            {
                "name": name,
                "available": available,
                "detail": detail,
                "hint": f"Install {name} or set its *_PATH in .env",
            }
        )
    root = settings.pyvideotrans_path
    python = settings.pyvideotrans_python
    present = bool(root and (root / "cli.py").is_file() and python and python.is_file())
    detail = str(root) if present else "External cli.py or engine Python not configured/found"
    if present and deep:
        assert root is not None and python is not None
        runner = ProcessRunner(JobLog(settings.workspace_dir / "diagnostics"), timeout=120)
        try:
            result = runner.run(
                [str(python), str(root / "cli.py"), "--help"], "pyVideoTrans", cwd=root
            )
            required = ("--output-dir", "--task", "--source_language_code", "--no-clear-cache")
            if not all(flag in result.stdout for flag in required):
                raise PipelineError(
                    "Unsupported CLI: update pyVideoTrans checkout; required flags missing"
                )
            if os.name == "nt" and settings.pyvideotrans_executor == "process":
                try:
                    runner.run(
                        [
                            str(python),
                            "-c",
                            "import multiprocessing; a,b=multiprocessing.Pipe(duplex=False); "
                            "a.close(); b.close()",
                        ],
                        "pyVideoTrans multiprocessing",
                        cwd=root,
                    )
                except PipelineError as exc:
                    raise PipelineError(
                        "Windows multiprocessing unavailable. For CPU compatibility set "
                        "PYVIDEOTRANS_EXECUTOR=thread; see diagnostic log."
                    ) from exc
            detail = "CLI imports successfully and required vtv flags exist"
        except PipelineError as exc:
            present, detail = False, str(exc)
    checks.append(
        {
            "name": "pyVideoTrans",
            "available": present,
            "detail": detail,
            "hint": "Set PYVIDEOTRANS_PATH and PYVIDEOTRANS_PYTHON; uv sync in external checkout",
        }
    )
    return {
        "ready": all(item["available"] for item in checks),
        "deep": deep,
        "engine_executor": settings.pyvideotrans_executor,
        "checks": checks,
    }
