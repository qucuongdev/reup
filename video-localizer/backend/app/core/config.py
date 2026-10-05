from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    workspace_dir: Path = REPO_ROOT / "workspace"
    pyvideotrans_path: Path | None = None
    pyvideotrans_python: Path | None = None
    pyvideotrans_executor: Literal["process", "thread"] = "process"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ytdlp_path: str = "yt-dlp"
    default_source_language: str = "zh-cn"
    default_target_language: str = "vi"
    default_voice: str = "vi-VN-HoaiMyNeural"
    asr_model: str = "small"
    asr_provider: int = Field(default=0, ge=0)
    translation_provider: int = Field(default=0, ge=0)
    translation_api_key: SecretStr = SecretStr("")
    translation_api_key_field: str = ""
    translation_api_url: str = ""
    translation_api_url_field: str = ""
    translation_model: str = ""
    translation_model_field: str = ""
    # MVP deliberately enables built-in Edge-TTS only; no voice cloning.
    tts_provider: int = Field(default=0, ge=0, le=0)
    use_cuda: bool = False
    process_timeout_seconds: int = Field(default=7200, ge=1)
    max_download_bytes: int = Field(default=2 * 1024**3, ge=1)
    max_video_seconds: int = Field(default=14400, ge=1)
    max_watermark_bytes: int = Field(default=10 * 1024**2, ge=1)
    font_path: Path | None = None

    @field_validator(
        "workspace_dir", "pyvideotrans_path", "pyvideotrans_python", "font_path", mode="before"
    )
    @classmethod
    def absolute_path(cls, value: object, info: ValidationInfo) -> Path | None:
        if value is None or value == "":
            return REPO_ROOT / "workspace" if info.field_name == "workspace_dir" else None
        path = Path(str(value)).expanduser()
        return (path if path.is_absolute() else REPO_ROOT / path).resolve()

    @model_validator(mode="after")
    def validate_engine_parameters(self) -> "Settings":
        if self.pyvideotrans_executor == "thread" and self.use_cuda:
            raise ValueError("Thread compatibility mode is CPU-only; set USE_CUDA=false")
        for value, field in (
            (self.translation_api_key.get_secret_value(), self.translation_api_key_field),
            (self.translation_api_url, self.translation_api_url_field),
            (self.translation_model, self.translation_model_field),
        ):
            if value and not field:
                raise ValueError("Engine credential/URL/model requires its corresponding *_FIELD")
            if field and (not field.isidentifier() or field.startswith("_")):
                raise ValueError("Engine parameter field must be a public identifier")
        return self

    def engine_overrides(self) -> dict[str, str]:
        pairs = (
            (self.translation_api_key_field, self.translation_api_key.get_secret_value()),
            (self.translation_api_url_field, self.translation_api_url),
            (self.translation_model_field, self.translation_model),
        )
        return {key: value for key, value in pairs if key and value}
