# Verification — 2026-10-05

## Kiểm chứng bàn dựng video

Editor đã xuất bản dựng 4 giây từ video thực sự đã dub tiếng Việt, 30 fps,
có audio và đủ bốn output. Bằng chứng mới nhất nằm ở `workspace/editor-verification.json`;
video ban đầu được so sánh byte và giữ nguyên.

`scripts/verify-editor.mjs` đã đạt: helper trim/split/reorder/bounds/frame grid,
pointer trim và undo, playhead, split/delete/undo, trim bằng input, reorder,
lưu SQLite, preview phát nối tiếp và dừng cuối timeline, xuất FFmpeg và tải output.
React DOM/media events mô phỏng; fetch, SQLite, queue, FFmpeg và file output thật.
Không claim native browser layout/playback. Test dùng timeline chưa lưu để không ghi đè project có sẵn.

Backend mới: 42 test nhẹ đạt; 8 integration model/network trước đó không chạy lại trong lượt editor.
Trong 8 test editor có kiểm tra FFmpeg thật với video màu/tone tự sinh:
ghép blue portrait trước red landscape, scale + pad, mốc subtitle Unicode 0–0.6–1.2 giây,
audio 880 Hz trước 440 Hz, duration/dimensions/fps, giữ nguyên nguồn, export ownership,
revision conflict, bảo vệ DELETE, recovery và external-process failure không lộ output dở.
Đây là kiểm chứng dựng video, không dùng fixture màu để chứng minh ASR/dịch/TTS.

TypeScript/Vite production build, Ruff và helper timeline đạt. Editor là một track với
audio đi cùng video; chưa nhiều lớp độc lập, waveform, transition hoặc keyframe.

## Kết quả MVP

Đã triển khai backend/API/SQLite worker, downloader, pyVideoTrans adapter, postprocess/render/thumbnail và React UI. **API pipeline thật đã Completed; React interaction thật đã Completed qua DOM mô phỏng. Chrome/playback/layout thực tế chưa được xác nhận vì Windows sandbox chặn named pipe.** Không coi unit fixtures hoặc DOM mô phỏng là proof Chrome.

### Local upload, 9:16, đầy đủ tùy chọn

Latest job: `1e10bf6c-27b9-4a95-b0eb-c1159bf87884`, thư mục:

```text
workspace/jobs/1e10bf6c-27b9-4a95-b0eb-c1159bf87884/final/
  final.mp4
  thumbnail.jpg
  subtitle.srt
  metadata.json
```

Chạy `scripts/verify-mvp.py` bằng API thật: upload MP4 và PNG, tạo/start job, chờ real stage, download bốn file, kiểm tra bytes/metadata. ASR tiếng Trung → translation vi → built-in Vietnamese Edge-TTS → upstream alignment/assembly → FFmpeg crop 1080×1920, burn subtitle, watermark, loudnorm → thumbnail 1280×720 với title Unicode và branding. Final duration **18.4s**, FPS **25**, có audio. MP4/SRT/JSON/JPEG đều có dữ liệu.

Báo cáo: `workspace/mvp-verification.json`. Log thật ghi stdout/stderr/return_code và các stage: transcribing, translating, dubbing, postprocessing, rendering, thumbnail, done. Polling có thể bỏ lỡ stage quá nhanh; JSONL giữ sự kiện.

Đã xem thumbnail thật: subtitle/font tiếng Việt có glyph, title và PNG hiển thị. Cỡ caption được sửa bằng canvas PlayRes khớp resolution để video dọc không có subtitle khổng lồ. Thumbnail title đặt phía trên để tránh caption phía dưới. Source test nền màu nên không đánh giá được chất lượng crop cho các cảnh quay chuyển động.

### URL và 16:9

Integration `test_real_url_job_full_pipeline` phục vụ clip tiếng Trung qua HTTP loopback, **yt-dlp thật** tải nguồn, pyVideoTrans thật dịch/dub, FFmpeg pad 1920×1080, thumbnail ở timestamp 1s. Assert Completed 100%, bốn file download, dimensions/audio, stage logs, Range download 206, duplicate start/delete lúc chạy và retry Completed bị từ chối.

Không test URL YouTube/TikTok bên ngoài. Không bypass DRM/paywall/platform protection.

### React interaction

Latest React job: `8cf36883-6f0e-4d0d-8d56-88dc8c8d7f44`.

`scripts/verify-ui.mjs` transpile **App.tsx thật**, mount React bằng Happy DOM, dùng **HTTP API thật**. Nhập URL clip, chọn 16:9, submit Process, chờ worker/engine thật. Assert UI Completed, progress 100, không error alert, bốn download link trả file non-empty. Report `workspace/react-ui-verification.json`, DOM output `workspace/react-ui-completed.html`. Không mock fetch/job/model.

Happy DOM **20.14.5** ở `../.runtime/ui-check`; đây là dependency tùy chọn cho verification, ngoài app production. Test này không xác nhận browser rendering, responsive layout, audio playback hoặc download native.

`scripts/verify-browser.py` sẵn sàng cho Chrome/Playwright: upload file, Process, 16:9 pad + burn/title, chờ Completed, click download, screenshot và mobile overflow check. Đã cài Playwright **1.63.0**, nhưng chạy tại phiên này bị **WinError 5** khi tạo asyncio/Chrome named pipe. Chrome headless cũng fail ở mojo platform channel. **Không có browser screenshot/report thành công**, không tuyên bố Chrome acceptance đạt.

## Runtime đã cài

- Backend `.venv`: Python **3.11.9**, FastAPI/Pydantic/SQLite, yt-dlp, multipart, Pillow, test/lint tools.
- Engine external `../.runtime/pyvideotrans`: Python **3.10.14**, commit `9945754bbe6d7a7108eb7eee941311a87f89d69e`. Không sửa source engine.
- FFmpeg/ffprobe **9.0.2**, Rubber Band **4.0.0**, trong `../.runtime/ffmpeg/bin`.
- yt-dlp **2026.09.27.232945**, Torch/torchaudio **2.7.1+cpu**, faster-whisper **1.2.1**, Edge-TTS **7.2.7**.
- Model `Systran/faster-whisper-small`, revision `536b0662742c02347bc0e980a01041f333bce120`, model.bin **483,546,902 bytes**, SHA256 `3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671`.
- `.env` local đã trỏ paths, CPU/thread compatibility, không API key. Default requested Google0 trả 429 ở một số lần; **upstream tự fallback Microsoft**. App không thay engine dịch/TTS.
- CPU thread compatibility tránh Windows restricted multiprocessing named pipes. Bridge đổi CPU submission/alignment executor và wrap stage method, không viết lại callback. Normal native default process vẫn được hỗ trợ.
- Python mới 3.11.17/3.10.19 có lỗi ACL temp directory trong sandbox; dùng 3.11.9/3.10.14. Không sửa PATH hệ thống/registry.
- Full upstream uv sync vướng optional voiceclone dependency `resemble-perth`; CPU headless profile ở `backend/requirements-engine-cpu.txt` đã được cài. GUI/provider tùy chọn/GPU nằm ngoài profile này.

## Test input và milestone engine

`workspace/input/smoke-chinese/chinese.mp4`: **18.36s**, 640×360, 25fps; giọng built-in `zh-CN-XiaoxiaoNeural`, script original và provenance.json. Đây là input fixture, không clone giọng hoặc dựng output Việt giả.

Engine-only jobs trước MVP: `6c119088-89a1-43d8-8dd1-a8bb8653d72f`, `28e2a557-ac5a-44e8-8c3a-69e87f3fe02e`. Đã nhận diện lại audio output bằng upstream STT vi; token similarity khoảng **0.9123** so với subtitle dịch. Đây là kiểm tra tự động, không thay đánh giá chủ quan bằng nghe/xem.

## Tests

- **32 unit tests**: lifecycle/retry/recovery/conflict, config/path/input validation, metadata, FFmpeg command/aspect, API upload caps/PNG/options validation, adapter target-SRT mapping, subprocess real stderr/stdout/failure/timeout/secret redaction/Unicode.
- **8 integration tests**: real engine milestone, real HTTP yt-dlp, URL job full pipeline, bốn render ratio/mode thật, worker fail/retry giữ nguồn và log return code.
- Lần tổng: 39 pass, một test smoke fail do subprocess cwd từ repo root. Đã sửa test dùng backend cwd và UTF-8, chạy lại riêng đạt 1 pass. Tổng 40 test hiện đạt; không skipped trong lượt kiểm chứng có video.
- Ruff backend/scripts pass, frontend TypeScript + Vite production build pass, git diff --check pass.
- Starlette/httpx TestClient deprecation warning không ảnh hưởng assertions. DOM harness có React act warning khi polling HTTP ngoài act; UI assertions đạt, không tính là browser verification.

## Tái lập

### Player seeking update

Player dùng controls riêng phủ cạnh dưới bên trong khung video, không hiển thị controls native trùng lặp.
Có play/pause, thanh tua, thời gian hiện tại/tổng, tiến/lùi 10s, mute/volume,
toàn màn hình khi browser hỗ trợ và popup nhập vị trí theo giây. Seeking disabled trước metadata hoặc khi media lỗi;
đổi job remount player để tránh giữ duration/vị trí của video trước.
`scripts/verify-ui.mjs --player-only` đạt: metadata readiness, slider seek 42.5s,
jump 80s, bounds 0..95s, time label và error state; controls cùng container với video,
native controls tắt, trạng thái play/pause/mute phản ánh media events (mô phỏng, không claim playback).
API thật trả Range 206 đúng bytes 65536..65567 trên final.mp4 đã render.
TypeScript/Vite build đạt. Native Chrome playback vẫn nằm ngoài bằng chứng sandbox này.

### Player kiểu YouTube: tốc độ và CC

Đã thêm settings tốc độ 0.25×–2×, CC cho native TextTrack, auto-hide 2.5s,
buffer/time hover, phím tắt, theater và PiP khi browser hỗ trợ. Icon SVG nhất quán.
Độ phân giải lấy từ metadata video thật; không đưa vào menu các rendition chưa tạo.
Burned captions không thể tắt, CC bị khóa và tooltip giải thích.
API `/api/jobs/{id}/subtitle.vtt` dùng FFmpeg convert SRT, cache tại postprocess/player,
không thay bộ bốn final output. Đã thử trên SRT output engine thật (HTTP 200, text/vtt, WEBVTT).
Test player DOM đạt cho caption mode/cue positioning, keyboard seek, playbackRate 1.5,
auto-hide/reveal và burned-caption case; media events/tracks mô phỏng, không claim native playback.
Backend test nhẹ mới nhất 34 pass, thêm VTT Unicode/timestamp/cache/MIME và chưa Completed → 404.
Ruff, production build và diff check đạt. Native Chrome playback/layout vẫn chưa được xác nhận.

Lệnh setup/run/test trong README. Dependency production cần thiết đã cài trong workspace này. Chỉ cần backend + frontend. Model ASR local; Google/Edge/fallback vẫn cần mạng. Chất lượng dịch/phát âm/alignment và Chrome playback cần kiểm tra trên nội dung thật của người dùng.
