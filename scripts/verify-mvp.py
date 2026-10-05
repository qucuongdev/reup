"""Real API integration: no fake engine. Run with backend PYTHONPATH and running API."""

import json
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

repo = Path(__file__).resolve().parents[1]
image = Image.new("RGBA", (240, 80), (15, 100, 90, 210))
ImageDraw.Draw(image).text((20, 25), "LOCALIZER", fill="white")
buffer = BytesIO()
image.save(buffer, format="PNG")
with httpx.Client(
    base_url="http://127.0.0.1:8000", timeout=60, trust_env=False
) as client:
    video = repo / "workspace/input/smoke-chinese/chinese.mp4"
    with video.open("rb") as handle:
        response = client.post(
            "/api/uploads", files={"file": ("chinese.mp4", handle, "video/mp4")}
        )
    response.raise_for_status()
    token = response.json()["id"]
    watermark = client.post(
        "/api/uploads?kind=watermark",
        files={"file": ("brand.png", buffer.getvalue(), "image/png")},
    )
    watermark.raise_for_status()
    response = client.post(
        "/api/jobs",
        json={
            "source_type": "local",
            "source_file": token,
            "output_ratio": "9:16",
            "burn_subtitle": True,
            "watermark_enabled": True,
            "watermark_file": watermark.json()["id"],
            "thumbnail_title": "Video thử nghiệm tiếng Việt",
            "thumbnail_branding": True,
        },
    )
    response.raise_for_status()
    job_id = response.json()["id"]
    print("JOB_ID=" + job_id, flush=True)
    client.post(f"/api/jobs/{job_id}/start").raise_for_status()
    deadline = time.monotonic() + 1800
    stages = []
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if not stages or stages[-1] != job["current_step"]:
            stages.append(job["current_step"])
            print(job["status"], job["progress"], job["current_step"], flush=True)
        if job["status"] == "failed":
            raise RuntimeError(job["error"])
        if job["status"] == "completed":
            break
        time.sleep(1)
    else:
        raise TimeoutError("MVP job exceeded 30 minutes")
    outputs = client.get(f"/api/jobs/{job_id}/files").json()
    assert {item["name"] for item in outputs} == {
        "final.mp4",
        "thumbnail.jpg",
        "subtitle.srt",
        "metadata.json",
    }
    for item in outputs:
        download = client.get(item["url"])
        download.raise_for_status()
        assert len(download.content) == item["size"] > 0
    metadata = client.get(f"/api/jobs/{job_id}/files/metadata.json").json()
    assert metadata["output"]["width"] == 1080 and metadata["output"]["height"] == 1920
    assert metadata["output"]["has_audio"]
    report = {
        "job_id": job_id,
        "observed_steps": stages,
        "files": outputs,
        "metadata": metadata,
    }
    (repo / "workspace/mvp-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("REAL MVP API PASS", flush=True)
