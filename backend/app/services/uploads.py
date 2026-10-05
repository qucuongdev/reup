import json
from pathlib import Path
from uuid import UUID

from app.core.paths import write_json
from app.core.process import PipelineError


class UploadStore:
    def __init__(self, workspace: Path) -> None:
        self.root = workspace / "input" / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, token: UUID, kind: str) -> tuple[Path, str]:
        directory = self.root / str(token)
        try:
            info = json.loads((directory / "upload.json").read_text(encoding="utf-8"))
            path = directory / info["stored_name"]
            if (
                info["kind"] != kind
                or not path.is_file()
                or not path.resolve().is_relative_to(self.root.resolve())
            ):
                raise PipelineError("Invalid upload reference")
            return path, info["original_name"]
        except (OSError, ValueError, KeyError) as exc:
            raise PipelineError("Upload not found or invalid; upload the file again") from exc

    def register(
        self, directory: Path, filename: str, original_name: str, kind: str, size: int
    ) -> None:
        write_json(
            directory / "upload.json",
            {
                "stored_name": filename,
                "original_name": original_name,
                "kind": kind,
                "size": size,
            },
        )
