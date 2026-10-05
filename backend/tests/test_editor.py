import hashlib
import json
import shutil
import subprocess
import time
import wave
from array import array
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from app.core.config import Settings
from app.core.paths import JobPaths
from app.main import create_app
from app.models.editor import EditorStore
from app.models.store import JobConflict, JobStore
from app.schemas.editor import Clip, DraftSave
from app.schemas.jobs import JobCreate, JobStatus
from app.services.editor import clip_duration, stamp, trim_subtitle


def clip(job_id=None, **options):
    return Clip(id=uuid4(), job_id=job_id or uuid4(), start=0, end=2, **options)


@pytest.mark.parametrize("start,end", [(1, 1), (2, 1), (0, 0.05), (-1, 2), (0, float("inf"))])
def test_editor_reject_invalid_intervals(start, end):
    with pytest.raises(ValidationError):
        Clip(id=uuid4(), job_id=uuid4(), start=start, end=end)


def test_editor_revisions_immutable_export_and_recovery(tmp_path):
    store = EditorStore(JobStore(tmp_path / "jobs.sqlite3"))
    job_id = str(uuid4())
    first = clip(job_id)
    plan = DraftSave(revision=0, clips=[first])
    assert store.save(job_id, plan)["revision"] == 1
    with pytest.raises(JobConflict):
        store.save(job_id, plan)
    with pytest.raises(ValidationError):
        DraftSave(revision=0, clips=[first, first])
    exported = store.enqueue(job_id, 1)
    store.save(job_id, DraftSave(revision=1, clips=[clip(job_id)]))
    assert store.export(exported["id"])["plan"]["clips"][0]["id"] == str(first.id)
    with pytest.raises(JobConflict):
        store.assert_source_idle(job_id)
    store.recover()
    assert store.export(exported["id"])["status"] == "failed"
    store.assert_source_idle(job_id)
    other_id = str(uuid4())
    store.save(other_id, DraftSave(revision=0, clips=[first]))
    with pytest.raises(JobConflict, match="saved timelines"):
        store.assert_source_idle(job_id)
    store.delete_project(other_id)
    store.assert_source_idle(job_id)


def test_subtitle_boundary_clipping_and_retiming():
    content = (
        "1\n00:00:00,000 --> 00:00:01,000\nXin chào\n\n2\n00:00:01,000 --> 00:00:02,000\nViệt Nam\n"
    )
    assert trim_subtitle(content, 0.5, 1.5, 3) == [(3, 3.5, "Xin chào"), (3.5, 4, "Việt Nam")]
    assert trim_subtitle(content, 2, 3, 0) == []
    assert stamp(60) == "00:01:00,000"
    assert stamp(1.9996) == "00:00:02,000"
    assert clip_duration(Clip(id=uuid4(), job_id=uuid4(), start=0.1, end=0.22)) == 0.1


def test_real_ffmpeg_editor_api_export(tmp_path):
    # Generated colours + tones test editing only. They are not translation/model proof.
    settings = Settings(workspace_dir=tmp_path)
    if not all(shutil.which(value) for value in (settings.ffmpeg_path, settings.ffprobe_path)):
        pytest.skip("Real FFmpeg/ffprobe required")
    with TestClient(create_app(settings)) as client:

        def source(color, size, frequency):
            paths = JobPaths.create(tmp_path)
            client.app.state.store.create(
                paths.id, JobCreate(source_type="local", source_file=uuid4()), f"{color}.mp4"
            )
            video = paths.root / "final/final.mp4"
            subprocess.run(
                [
                    settings.ffmpeg_path,
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c={color}:s={size}:r=30:d=2",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={frequency}:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(video),
                ],
                check=True,
                capture_output=True,
            )
            width, height = map(int, size.split("x"))
            (video.parent / "metadata.json").write_text(
                json.dumps({"output": {"duration": 2, "width": width, "height": height}})
            )
            (video.parent / "subtitle.srt").write_text(
                f"1\n00:00:00,000 --> 00:00:02,000\n{color} tiếng Việt\n", encoding="utf-8"
            )
            client.app.state.store.stage(paths.id, JobStatus.completed, 100, "done")
            return paths, hashlib.sha256(video.read_bytes()).hexdigest()

        red, original_hash = source("red", "160x90", 440)
        blue, _ = source("blue", "90x160", 880)
        base = f"/api/jobs/{red.id}/editor"
        draft = client.get(base).json()
        assert draft["revision"] == 0
        assert len(draft["sources"]) == 2
        clips = [
            dict(id=str(uuid4()), job_id=blue.id, start=0.2, end=0.8),
            dict(id=str(uuid4()), job_id=red.id, start=0.5, end=1.1),
        ]
        invalid = [clips[0] | {"end": 10}]
        assert client.post(base, json={"revision": 0, "clips": invalid}).status_code == 422
        assert client.post(base, json={"revision": 0, "clips": clips}).json()["revision"] == 1
        assert client.post(base, json={"revision": 0, "clips": clips}).status_code == 409
        assert client.delete(f"/api/jobs/{blue.id}").status_code == 409
        assert client.post(base + "/exports", json={"revision": 2}).status_code == 409
        exported = client.post(base + "/exports", json={"revision": 1})
        assert exported.status_code == 202
        identifier = exported.json()["id"]
        endpoint = base + "/exports/" + identifier
        for _ in range(400):
            state = client.get(endpoint).json()
            if state["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert state["status"] == "completed", state
        assert state["progress"] == 100
        outputs = client.get(endpoint + "/files").json()
        assert {item["name"] for item in outputs} == {
            "final.mp4",
            "subtitle.srt",
            "thumbnail.jpg",
            "metadata.json",
        }
        assert all(client.get(item["url"]).status_code == 200 for item in outputs)
        metadata = client.get(endpoint + "/files/metadata.json").json()
        assert metadata["output"]["has_audio"]
        assert metadata["output"]["fps"] == 30
        assert (metadata["output"]["width"], metadata["output"]["height"]) == (160, 90)
        assert abs(metadata["output"]["duration"] - 1.2) < 0.05
        srt = client.get(endpoint + "/files/subtitle.srt").text.replace("\r\n", "\n")
        assert "00:00:00,000 --> 00:00:00,600\nblue tiếng Việt" in srt
        assert "00:00:00,600 --> 00:00:01,200\nred tiếng Việt" in srt
        assert "WEBVTT" in client.get(endpoint + "/subtitle.vtt").text
        assert client.get(endpoint + "/logs").json()
        video = client.app.state.editor.export_root(state) / "final/final.mp4"
        # Confirm audio order as well as video order, after final AAC encoding.
        for timestamp, expected_frequency in [(0.15, 880), (0.8, 440)]:
            audio = tmp_path / f"audio-{timestamp}.wav"
            subprocess.run(
                [
                    settings.ffmpeg_path,
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(video),
                    "-t",
                    "0.2",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(audio),
                ],
                check=True,
                capture_output=True,
            )
            with wave.open(str(audio)) as handle:
                samples = array("h", handle.readframes(handle.getnframes()))
                measured = sum(
                    left <= 0 < right for left, right in zip(samples, samples[1:], strict=False)
                ) / (len(samples) / handle.getframerate())
            assert abs(measured - expected_frequency) < 10
        for timestamp, channel in [(0.2, 2), (0.9, 0)]:
            frame = tmp_path / f"frame-{timestamp}.png"
            subprocess.run(
                [
                    settings.ffmpeg_path,
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    str(frame),
                ],
                check=True,
                capture_output=True,
            )
            with Image.open(frame) as image:
                pixel = image.getpixel((80, 45))
                assert pixel[channel] > 200 and sum(pixel) - pixel[channel] < 40
                if timestamp == 0.2:
                    assert max(image.getpixel((5, 45))) < 15  # Portrait pad, no stretch.
        assert (
            hashlib.sha256((red.root / "final/final.mp4").read_bytes()).hexdigest() == original_hash
        )
        assert client.get(f"/api/jobs/{red.id}").json()["status"] == "completed"
        assert client.get(f"/api/jobs/{blue.id}/editor/exports/{identifier}").status_code == 404
        # An external failure must remain visible, without exposing partial files.
        client.app.state.editor.settings = settings.model_copy(
            update={"ffmpeg_path": "missing-ffmpeg-editor"}
        )
        failed = client.post(base + "/exports", json={"revision": 1}).json()
        failed_endpoint = base + "/exports/" + failed["id"]
        for _ in range(100):
            failure = client.get(failed_endpoint).json()
            if failure["status"] == "failed":
                break
            time.sleep(0.05)
        assert failure["status"] == "failed"
        assert failure["error"]
        assert client.get(failed_endpoint + "/files").json() == []
