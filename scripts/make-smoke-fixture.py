"""Create a rights-cleared Chinese speech INPUT using a built-in Edge voice.

This is test input generation, not simulated engine output. Run from backend/:
python ../scripts/make-smoke-fixture.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import Settings
from app.core.paths import write_json
from app.core.process import JobLog, PipelineError, ProcessRunner

TEXT = (
    "大家好，欢迎来到视频翻译测试。今天我们学习如何把中文视频翻译成越南语。"
    "请保留字幕，并使用自然的声音朗读。这个短视频只用于测试本地的视频处理工具。"
)


def main() -> int:
    settings = Settings()
    folder = settings.workspace_dir / "input" / "smoke-chinese"
    folder.mkdir(parents=True, exist_ok=True)
    runner = ProcessRunner(JobLog(folder / "logs"), timeout=180)
    try:
        audio = folder / "chinese.mp3"
        video = folder / "chinese.mp4"
        runner.run(
            [
                sys.executable,
                "-m",
                "edge_tts",
                "--voice",
                "zh-CN-XiaoxiaoNeural",
                "--text",
                TEXT,
                "--write-media",
                str(audio),
            ],
            "fixture-speech",
        )
        runner.run(
            [
                settings.ffmpeg_path,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x203047:s=640x360:r=25",
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(video),
            ],
            "fixture-video",
        )
        write_json(
            folder / "provenance.json",
            {
                "text": TEXT,
                "voice": "zh-CN-XiaoxiaoNeural",
                "description": "Synthetic Chinese source speech; original text; no voice cloning",
                "purpose": "Real ASR/translation/TTS integration input, not final output",
            },
        )
        print(json.dumps({"input_video": str(video)}, ensure_ascii=False))
        return 0
    except (PipelineError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
