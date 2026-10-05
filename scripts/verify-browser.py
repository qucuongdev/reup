"""Real UI acceptance using installed Chrome, backend and Vite servers."""

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

repo = Path(__file__).resolve().parents[1]
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:5173")
    page.get_by_text("Engine sẵn sàng", exact=True).wait_for(timeout=30000)
    page.get_by_role("button", name="Upload", exact=True).click()
    page.get_by_label("File local", exact=True).set_input_files(
        repo / "workspace/input/smoke-chinese/chinese.mp4"
    )
    page.get_by_label("Format", exact=True).select_option("16:9")
    page.get_by_label("Resize", exact=True).select_option("pad")
    page.get_by_label("Burn subtitle", exact=True).check()
    page.get_by_label("Title (tùy chọn)", exact=True).fill("Kiểm chứng Video Localizer")
    with page.expect_response(
        lambda response: (
            response.url.endswith("/api/jobs") and response.request.method == "POST"
        )
    ) as created:
        page.get_by_role("button", name="Process", exact=True).click()
    job_id = created.value.json()["id"]
    print("BROWSER_JOB_ID=" + job_id, flush=True)
    row = page.get_by_role("row").filter(has=page.get_by_text(job_id[:8], exact=False))
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        if row.get_by_text("Completed", exact=True).count():
            break
        if row.get_by_text("failed", exact=True).count():
            raise RuntimeError(
                row.inner_text()
                + "\n"
                + page.locator("[role=alert]").all_inner_texts().__repr__()
            )
        page.wait_for_timeout(1000)
    else:
        raise TimeoutError("UI job did not complete")
    page.get_by_role("link", name="metadata.json", exact=False).wait_for(timeout=15000)
    for name in ["final.mp4", "thumbnail.jpg", "subtitle.srt", "metadata.json"]:
        with page.expect_download() as result:
            page.get_by_role("link", name=name, exact=False).click()
        assert result.value.suggested_filename == name
        destination = repo / "workspace/temp/browser-downloads" / job_id / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        result.value.save_as(destination)
        assert destination.stat().st_size > 0
    metadata = json.loads(destination.read_text(encoding="utf-8"))
    assert metadata["output"]["width"] == 1920 and metadata["output"]["height"] == 1080
    assert not errors, errors
    page.screenshot(path=str(repo / "workspace/browser-completed.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Create Job", exact=True).click()
    page.screenshot(
        path=str(repo / "workspace/browser-create-mobile.png"), full_page=True
    )
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    (repo / "workspace/browser-verification.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "browser": browser.version,
                "downloaded_files": [
                    "final.mp4",
                    "thumbnail.jpg",
                    "subtitle.srt",
                    "metadata.json",
                ],
                "page_errors": errors,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    browser.close()
    print("REAL BROWSER MVP PASS", flush=True)
