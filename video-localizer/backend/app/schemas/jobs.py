from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.downloader.ytdlp import validate_url
from app.services.translator.base import TranslationConfig


class JobStatus(StrEnum):
    queued = "queued"
    downloading = "downloading"
    transcribing = "transcribing"
    translating = "translating"
    dubbing = "dubbing"
    postprocessing = "postprocessing"
    rendering = "rendering"
    completed = "completed"
    failed = "failed"


ACTIVE_STATUSES = {
    JobStatus.downloading,
    JobStatus.transcribing,
    JobStatus.translating,
    JobStatus.dubbing,
    JobStatus.postprocessing,
    JobStatus.rendering,
}


class WatermarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "bottom-right"
    opacity: float = Field(default=0.7, ge=0, le=1)
    margin: int = Field(default=24, ge=0, le=300)
    scale: float = Field(default=0.15, ge=0.01, le=0.5, description="Fraction of video width")


class JobCreate(TranslationConfig):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["url", "local"]
    source_url: str | None = None
    source_file: UUID | None = None  # Upload token, never an arbitrary server path.
    output_ratio: Literal["original", "16:9", "9:16", "1:1"] = "original"
    fit_mode: Literal["pad", "crop"] = "crop"
    subtitle_enabled: bool = True
    burn_subtitle: bool = False
    watermark_enabled: bool = False
    watermark_file: UUID | None = None
    watermark: WatermarkConfig = Field(default_factory=WatermarkConfig)
    normalize_audio: bool = True
    thumbnail_enabled: bool = True
    thumbnail_mode: Literal["auto", "timestamp"] = "auto"
    thumbnail_timestamp: float = Field(default=0, ge=0)
    thumbnail_title: str = Field(default="", max_length=120)
    thumbnail_branding: bool = False

    @model_validator(mode="after")
    def validate_options(self) -> "JobCreate":
        if self.source_type == "url":
            if not self.source_url or self.source_file:
                raise ValueError("URL source requires source_url only")
            try:
                validate_url(self.source_url)
            except RuntimeError as exc:
                raise ValueError(str(exc)) from exc
        elif not self.source_file or self.source_url:
            raise ValueError("Local source requires an upload token only")
        if self.burn_subtitle and not self.subtitle_enabled:
            raise ValueError("Burn subtitle requires subtitle_enabled")
        if (self.watermark_enabled or self.thumbnail_branding) and not self.watermark_file:
            raise ValueError("Watermark/thumbnail branding requires a PNG upload")
        prefixes = {
            "vi": "vi-",
            "en": "en-",
            "zh-cn": "zh-CN-",
            "zh-tw": "zh-TW-",
            "ja": "ja-",
            "ko": "ko-",
            "fr": "fr-",
            "de": "de-",
            "es": "es-",
        }
        if not self.voice.endswith("Neural") or self.voice == "No":
            raise ValueError("Only built-in Edge-TTS Neural voices are supported")
        prefix = prefixes.get(self.target_language)
        if prefix and not self.voice.lower().startswith(prefix.lower()):
            raise ValueError("Voice language must match target_language")
        return self


class JobView(JobCreate):
    id: UUID
    source_name: str
    status: JobStatus
    progress: int
    current_step: str
    error: str | None
    created_at: datetime
    updated_at: datetime
    attempt: int
