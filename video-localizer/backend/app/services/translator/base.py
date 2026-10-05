from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field


class TranslationConfig(BaseModel):
    source_language: str = Field(default="zh-cn", pattern=r"^[a-z]{2,3}(-[a-z]{2,4})?$")
    target_language: str = Field(default="vi", pattern=r"^[a-z]{2,3}(-[a-z]{2,4})?$")
    voice: str = Field(default="vi-VN-HoaiMyNeural", min_length=1)


@dataclass(frozen=True)
class TranslationResult:
    video: Path
    subtitle: Path
    text: Path
    engine_output: Path


class TranslationEngine(Protocol):
    def process(
        self, input_video: Path, config: TranslationConfig, output: Path
    ) -> TranslationResult: ...
