import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from app.core.process import PipelineError


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class JobPaths:
    id: str
    root: Path

    @classmethod
    def create(cls, workspace: Path, job_id: str | None = None) -> "JobPaths":
        identifier = str(UUID(job_id)) if job_id else str(uuid4())
        root = workspace.resolve() / "jobs" / identifier
        root.mkdir(parents=True, exist_ok=False)
        for name in ("source", "translation", "postprocess", "final", "logs"):
            (root / name).mkdir()
        return cls(identifier, root)

    def directory(self, name: str) -> Path:
        if name not in {"source", "translation", "postprocess", "final", "logs"}:
            raise PipelineError("Unknown job directory")
        return self.root / name


def require_local_video(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise PipelineError("Input must be an existing MP4, MOV, MKV or WebM file")
    if path.stat().st_size == 0:
        raise PipelineError("Input video is empty")
    return path
