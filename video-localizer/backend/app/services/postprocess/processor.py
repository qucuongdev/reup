import shutil
from pathlib import Path

from app.core.config import Settings
from app.core.process import PipelineError
from app.schemas.jobs import JobCreate

RESOLUTIONS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


class VideoProcessor:
    def resize(self, ratio: str, mode: str) -> str:
        base = "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1"
        if ratio == "original":
            return base
        width, height = RESOLUTIONS[ratio]
        if mode == "crop":
            return (
                base
                + f",scale={width}:{height}:force_original_aspect_ratio=increase,"
                + f"crop={width}:{height}"
            )
        return (
            base
            + f",scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            + f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

    def crop(self, ratio: str) -> str:
        return self.resize(ratio, "crop")

    def burn_subtitle(self, width: int, height: int) -> str:
        # Explicit canvas prevents libass's default style becoming huge in portrait.
        font_size = max(18, min(48, round(width * 0.035)))
        return (
            "subtitles=filename=subtitle.srt:fontsdir=.:force_style='"
            f"PlayResX={width},PlayResY={height},FontSize={font_size},"
            "MarginL=32,MarginR=32,MarginV=40,Outline=2'"
        )

    def normalize_audio(self) -> str:
        return "loudnorm=I=-16:TP=-1.5:LRA=11"

    def add_watermark(self, config: JobCreate, width: int) -> str:
        wm = config.watermark
        x = str(wm.margin) if wm.position.endswith("left") else f"W-w-{wm.margin}"
        y = str(wm.margin) if wm.position.startswith("top") else f"H-h-{wm.margin}"
        return (
            f"[1:v]scale={max(2, int(width * wm.scale))}:-1,format=rgba,"
            f"colorchannelmixer=aa={wm.opacity}[wm];"
            f"[base][wm]overlay={x}:{y}:shortest=1[out]"
        )


def prepare_font(settings: Settings, directory: Path) -> None:
    candidates = [
        settings.font_path,
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font = next((p for p in candidates if p and p.is_file()), None)
    if not font:
        raise PipelineError("Install a Unicode font or set FONT_PATH to a TTF file")
    shutil.copy2(font, directory / "font.ttf")
