import json
import os
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class PipelineError(RuntimeError):
    """Actionable integration error, suitable for displaying without a traceback."""


class JobLog:
    def __init__(self, directory: Path, secrets: tuple[str, ...] = ()) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "job.log"
        self.secrets = tuple(secret for secret in secrets if secret)
        self.lock = threading.Lock()

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return text

    def write(self, step: str, message: str, level: str = "INFO") -> None:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "step": step,
            "message": self.redact(message),
        }
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ProcessResult:
    return_code: int
    stdout: str
    stderr: str


class ProcessRunner:
    """No shell. Stream both pipes to job.log; keep bounded tails in memory."""

    def __init__(self, log: JobLog, timeout: int = 7200, on_line: Callable | None = None) -> None:
        self.log = log
        self.timeout = timeout
        self.on_line = on_line

    def run(
        self,
        command: list[str],
        step: str,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ProcessResult:
        self.log.write(step, f"Starting {Path(command[0]).name}")
        process_env = (env if env is not None else os.environ).copy()
        process_env["PYTHONUTF8"] = "1"
        process_env["PYTHONIOENCODING"] = "utf-8"
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
        except OSError as exc:
            raise PipelineError(f"Cannot start {command[0]}: {exc}") from exc

        tails: dict[str, deque[str]] = {"stdout": deque(maxlen=100), "stderr": deque(maxlen=100)}
        callback_errors: list[Exception] = []

        def drain(stream, name: str) -> None:
            assert stream is not None
            with stream:
                for line in stream:
                    line = self.log.redact(line.rstrip())
                    tails[name].append(line)
                    self.log.write(step, f"{name}: {line}")
                    if self.on_line and not callback_errors:
                        try:
                            self.on_line(name, line)
                        except Exception as exc:
                            callback_errors.append(exc)

        threads = [
            threading.Thread(target=drain, args=(process.stdout, "stdout"), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            process.kill()
            process.wait()
        for thread in threads:
            thread.join(timeout=10)
        result = ProcessResult(
            process.returncode, "\n".join(tails["stdout"]), "\n".join(tails["stderr"])
        )
        self.log.write(step, f"return_code={result.return_code}")
        if callback_errors:
            raise PipelineError(
                f"Stage reporting failed: {callback_errors[0]}"
            ) from callback_errors[0]
        if timed_out:
            raise PipelineError(
                f"{step} timed out after {timeout or self.timeout}s; see {self.log.path}"
            )
        if result.return_code:
            detail = (result.stderr or result.stdout)[-2000:]
            raise PipelineError(
                f"{step} exited {result.return_code}: {detail}; see {self.log.path}"
            )
        return result
