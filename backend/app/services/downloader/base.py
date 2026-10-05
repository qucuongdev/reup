from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class DownloadResult:
    video: Path
    metadata_file: Path
    metadata: dict


class VideoDownloader(Protocol):
    def download(self, url: str, output: Path) -> DownloadResult: ...
