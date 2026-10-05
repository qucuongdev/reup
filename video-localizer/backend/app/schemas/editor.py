from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Clip(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: UUID
    job_id: UUID
    start: float = Field(ge=0)
    end: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end - self.start < 0.1 - 1e-8:
            raise ValueError("Clip must be at least 0.1 seconds")
        return self


class DraftSave(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    clips: list[Clip] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def distinct_clips(self):
        if len({clip.id for clip in self.clips}) != len(self.clips):
            raise ValueError("Clip IDs must be unique")
        return self


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
