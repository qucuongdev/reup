# Video Localizer

## Bàn dựng video: cắt và ghép

Trong **Jobs**, chọn job Completed → **✂ Cắt / ghép video**. Preview ở trên, timeline ở dưới.
Kéo hai tay nắm xanh để trim; đặt playhead rồi **Chia đoạn**; kéo thân clip để đổi thứ tự.
Có Xóa đoạn, Hoàn tác/Làm lại, zoom, nhập mốc cắt chính xác và nút chuyển đoạn trước/sau.
Chọn một video đã Completed trong danh sách để thêm vào cuối timeline. Tối đa 32 đoạn.
**Lưu timeline** ghi project vào SQLite; **Xuất bản dựng** lưu snapshot và đưa vào cùng worker local,
không block request hoặc ghi đè video đã dịch. Lưu từ hai tab đồng thời trả 409 để tránh mất thay đổi.

FFmpeg xuất H.264/AAC, 30 fps, giữ canvas của job đang mở. Video khác tỷ lệ được scale + pad.
Thời lượng mỗi đoạn làm tròn xuống theo frame 1/30 giây; preview/timeline dùng cùng phép tính.
Audio cắt cùng video, subtitle rời được chặn ở biên đoạn, đổi mốc và đánh số lại theo thứ tự ghép.
Cắt giữa một câu vẫn giữ toàn bộ chữ của cue trong thời gian còn lại; chưa nhận diện lại từng từ.
Nếu vùng chọn không có cue, `subtitle.srt` hợp lệ nhưng rỗng. Chữ đã burn vào hình không thể gỡ.

Mỗi bản xuất có `final.mp4`, `thumbnail.jpg`, `subtitle.srt`, `metadata.json` và log riêng:
`workspace/jobs/{job_id}/editor/exports/{export_id}/{final,logs,postprocess}/`.
Intermediate PCM giữ độ chính xác audio và tốn dung lượng; chưa tự cleanup. Nguồn đang dùng trong
export hoặc timeline của job khác được bảo vệ khỏi DELETE; bỏ clip khỏi timeline và lưu trước khi xóa.
Các API nằm dưới `/api/jobs/{job_id}/editor`: GET/POST draft, POST/GET exports,
GET exports/{id}, files, files/{name}, subtitle.vtt, logs.

Đây là editor một track với audio đi cùng video; chưa có nhiều lớp video/audio độc lập, waveform,
transition, keyframe, hiệu ứng hoặc sửa chữ subtitle. Dubbing hiện vẫn thay audio gốc;
chưa có tách/giữ nhạc nền gốc hoặc trộn voiceover. Ghép giữ audio của video đã xử lý.

Kiểm tra editor không cần model: `cd backend` rồi
`../.venv/Scripts/python.exe -m pytest tests/test_editor.py -q`.
Kiểm tra helper timeline: từ repo root `node scripts/verify-editor.mjs --helpers-only`.
Interaction test tùy chọn: đặt `LOCALIZER_DOM_MODULE` trỏ Happy DOM và `LOCALIZER_EDITOR_JOB`
thành job Completed chưa có timeline đã lưu, rồi `node scripts/verify-editor.mjs`.
Test này thực sự lưu timeline/xuất FFmpeg/tải file; DOM và media events mô phỏng, không chứng minh Chrome playback/layout.

Local MVP: URL hoặc MP4/MOV/MKV/WebM → pyVideoTrans → dịch/lồng tiếng → FFmpeg → video, subtitle, thumbnail và metadata.

**Đã chạy một job API thực tế**: ASR tiếng Trung, dịch và TTS tiếng Việt, crop 9:16 1080×1920, subtitle burn, PNG watermark, normalize audio, thumbnail 1280×720 có tiêu đề/branding, tải đủ bốn file. Không mock engine. UI có Create Job và Jobs; kết quả kiểm chứng trình duyệt được ghi riêng trong `docs/verification.md`.

## Chạy trên workspace đã cài dependency

Từ repo root, terminal thứ nhất:

```powershell
./scripts/start-backend.ps1
```

Terminal thứ hai:

```powershell
cd frontend
pnpm dev
```

Mở **http://127.0.0.1:5173** → chọn URL / Upload → cấu hình → Process → Jobs → preview / tải output. API docs: **http://127.0.0.1:8000/docs**.

`.env` local đã trỏ dependency ngoài repo ở `../.runtime`; không ghi đè bằng example trên máy này. Chạy một backend process / một uvicorn worker. Không `--reload` khi đang render. Shutdown bình thường đợi job đã xếp hàng; nếu app bị kill, startup sau đánh dấu job gián đoạn Failed, cho Retry.

## Architecture

```text
React + TypeScript + Vite
  → FastAPI: uploads / jobs / logs / output files
  → SQLite JobStore + LocalWorker (queue nội bộ, một worker)
  → Pipeline
      → yt-dlp: URL download / copy local upload
      → ffprobe: kiểm tra nguồn
      → TranslationEngine → PyVideoTransEngine
          → process Python riêng + bridge → upstream CLI vtv
          → upstream ASR / translate / TTS / alignment / assemble
      → chuẩn hóa translated_video.mp4 + subtitle.srt + translated_text.txt
      → VideoProcessor: chuẩn bị filter/subtitle/PNG/font
      → FFmpegRenderer: crop/pad, subtitle, watermark, audio → final.mp4
      → ThumbnailGenerator: frame 30% / timestamp → thumbnail.jpg
      → kiểm tra media + metadata.json → Completed
```

Không fork/copy pipeline pyVideoTrans. Bridge inject runtime settings, gọi CLI và quan sát method thật `TransCreate.recogn/trans/dubbing` để emit stage events; không viết ASR/TTS/translation. CPU thread compatibility chỉ đổi executor khi Windows named pipe không hoạt động, vẫn dùng callback upstream. Không ghi key vào command line hoặc source, không gọi params.save(). Khi update engine, chạy deep check và integration.

Progress là tỷ lệ stage đã hoàn tất, **không phải phần trăm thời gian/model nội bộ**: 0 input/download, 14 transcribing, 28 translating, 42 dubbing, 57 postprocessing, 71 rendering, 85 thumbnail, 100 completed. Stage nhanh có thể nằm giữa hai lần UI polling nhưng được log. Lỗi luôn Failed với message; stdout/stderr/return code trong JSONL log.

## Structure và output

```text
video-localizer/
├── backend/
│   ├── app/{api,core,models,schemas,jobs}/
│   ├── app/services/{downloader,translator,postprocess,renderer,thumbnail}/
│   ├── app/main.py, app/smoke.py
│   ├── tests/
│   └── requirements{,-dev,-engine-cpu,-browser}.txt
├── frontend/src/                     # Create Job / Jobs
├── scripts/                          # Start/checks/real verification
├── docs/verification.md
├── docker/README.md                  # Native first; Docker deferred
├── .env.example
└── workspace/
    ├── input/uploads/<token>/        # Controlled upload tokens
    └── jobs/<uuid>/
        ├── source/                  # Original + metadata + optional PNG
        ├── translation/attempt-N/   # Fresh engine output + normalized files
        ├── postprocess/attempt-N/   # Render assets/staging
        ├── final/
        │   ├── final.mp4
        │   ├── thumbnail.jpg
        │   ├── subtitle.srt
        │   └── metadata.json
        └── logs/job.log
```

Thumbnail chỉ export khi Generate thumbnail bật; SRT export khi Subtitle bật. Engine vẫn tạo subtitle nội bộ để dịch/align. Retry giữ nguồn/log, dùng attempt mới. API mở final sau Completed. Metadata chứa config không secret, source metadata, dimensions/FPS/duration/audio, engine settings và danh sách output.

Upload video giới hạn MAX_DOWNLOAD_BYTES; PNG giới hạn MAX_WATERMARK_BYTES và 4096px mỗi cạnh. Source được ffprobe kiểm tra trong worker. App giữ nguồn/upload sau thành công. DELETE xóa thư mục job đã dừng, không xóa upload dùng chung. Chưa cleanup tự động; quản lý dung lượng workspace khi không còn cần file.

## Native setup — Windows PowerShell

Chạy tại repo root. Cài Python 3.11+ trước, Node >=22.12, pnpm và Git.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Copy-Item .env.example .env
```

Cài FFmpeg gồm `ffmpeg` và `ffprobe` vào PATH (ví dụ `winget install --id Gyan.FFmpeg -e`),
mở terminal mới rồi kiểm tra:

```powershell
ffmpeg -version
ffprobe -version
.\.venv\Scripts\yt-dlp.exe --version
```

Checkout engine **ngoài repo app**, theo [upstream setup](https://github.com/jianchang512/pyvideotrans).
Cài `uv` nếu chưa có (`python -m pip install uv` hoặc installer chính thức).

```powershell
git clone https://github.com/jianchang512/pyvideotrans.git D:/Tools/pyvideotrans
Set-Location D:/Tools/pyvideotrans
uv sync
uv run cli.py --list providers
uv run cli.py --list languages
uv run cli.py --help
git rev-parse HEAD
```

Ghi lại commit engine khi smoke test thành công để tái lập; app không tự update engine.
Upstream chọn Python phù hợp qua `uv sync`, không ép engine dùng Python backend.
CPU mặc định; CUDA chỉ bật khi đã cài stack GPU đúng theo tài liệu engine.

### CPU headless profile trong workspace này

Full upstream dependency set gồm nhiều provider ngoài scope MVP và mặc định kéo Torch CUDA.
Repo cung cấp `backend/requirements-engine-cpu.txt` cho CLI faster-whisper/Edge-TTS,
đối chiếu với commit `9945754bbe6d7a7108eb7eee941311a87f89d69e`. Source engine giữ nguyên.
Profile này không phục vụ mọi provider tùy chọn/GUI của upstream. Sau này bật provider khác
thì cài dependency tương ứng trong engine venv.

Backend venv hiện ở `.venv`; engine ở `../.runtime/pyvideotrans/.venv`;
FFmpeg/ffprobe ở `../.runtime/ffmpeg/bin`; `.env` local đã trỏ tới các đường dẫn này.
Python 3.11.9 và 3.10.14 được dùng để tránh lỗi ACL thư mục tạm của Python mới trong
Windows sandbox hiện tại; không đăng ký Python vào registry hoặc sửa PATH toàn hệ thống.

Các lệnh cài engine CPU tương đương (từ repo root, với `uv` đã cài):

```powershell
uv venv ../.runtime/pyvideotrans/.venv --python 3.10.14
uv pip install --python ../.runtime/pyvideotrans/.venv/Scripts/python.exe torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cpu
uv pip install --python ../.runtime/pyvideotrans/.venv/Scripts/python.exe -r backend/requirements-engine-cpu.txt --index-url https://pypi.org/simple
```

Trong sandbox, đặt `UV_CACHE_DIR` và `UV_PYTHON_INSTALL_DIR` vào `../.runtime/` nếu dùng uv,
để các file cài đặt nằm trong workspace được phép ghi. Không chạy `uv sync` mặc định sau
CPU setup vì upstream sẽ đồng bộ lại toàn bộ dependency/CUDA profile của nó.

Sửa `.env`:

```dotenv
PYVIDEOTRANS_PATH=D:/Tools/pyvideotrans
PYVIDEOTRANS_PYTHON=D:/Tools/pyvideotrans/.venv/Scripts/python.exe
YTDLP_PATH=D:/Work/Tool/reup/video-localizer/.venv/Scripts/yt-dlp.exe
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
TRANSLATION_PROVIDER=0
TTS_PROVIDER=0
```

Provider mặc định 0 theo CLI hiện được đối chiếu (Google translate và Edge-TTS); không đảm bảo
dịch vụ online luôn sẵn sàng. Edge-TTS cần mạng; “local” là app/media storage local,
không có nghĩa toàn bộ provider offline. Faster-whisper tải model lần đầu.
Nếu dùng provider cần key, chọn đúng ID từ installation của bạn rồi set `.env`, ví dụ
OpenAI ChatGPT: `TRANSLATION_API_KEY_FIELD=chatgpt_key`, `TRANSLATION_MODEL_FIELD=chatgpt_model`,
`TRANSLATION_API_URL_FIELD=chatgpt_api` cùng các giá trị tương ứng. Không đưa secret vào Git.
Cấu hình TTS khác Edge-TTS bị từ chối ở milestone này để không bật voice cloning ngoài ý muốn.

## API

| Method | Endpoint | Mục đích |
|---|---|---|
| POST | `/api/uploads?kind=video` / `kind=watermark` | Multipart `file`, trả UUID |
| POST | `/api/jobs` | Tạo queued job từ URL/upload token |
| GET | `/api/jobs?limit=100&offset=0` | Danh sách |
| GET | `/api/jobs/{id}` | Status/progress/step/error |
| POST | `/api/jobs/{id}/start` | Xếp hàng mới, HTTP 202 |
| POST | `/api/jobs/{id}/retry` | Failed job, attempt mới |
| DELETE | `/api/jobs/{id}` | Xóa job đã dừng; từ chối job đang chạy |
| GET | `/api/jobs/{id}/files` | File allowlist + URL |
| GET | `/api/jobs/{id}/files/{name}` | Download/stream, hỗ trợ Range |
| GET | `/api/jobs/{id}/subtitle.vtt` | Track phụ đề cho player, FFmpeg convert/cache từ SRT |
| GET | `/api/jobs/{id}/logs?limit=100` | Log gần nhất, bounded read |
| GET | `/api/health`, `/api/environment`, `/api/options` | Dependency/defaults |

`source_file` là UUID upload token, không nhận đường dẫn tùy ý trên server. Xem schema ở `/docs`. Chỉ bốn output cố định được expose. Không authentication; bind loopback, không thiết kế cho public hosting.

## Media configuration

Player dùng giao diện kiểu YouTube: controls phủ trong video, thanh tua đỏ/buffered progress,
tự ẩn sau 2.5s khi phát, icon play/pause, volume, CC, settings, theater, fullscreen và PiP
khi browser hỗ trợ. Menu tốc độ 0.25×–2×, popup nhập vị trí và thông tin độ phân giải nguồn.
Phím tắt khi focus player: Space/K phát, ←/→ tua 5s, J/L tua 10s, M mute, C caption,
F fullscreen, T theater, số 0–9 đến 0–90% video, </> đổi tốc độ. Input/menu không bị phím tua can thiệp.
CC dùng track WebVTT được FFmpeg convert từ subtitle.srt; chỉ bật/tắt phụ đề rời.
Nếu Burn subtitle bật lúc render, phụ đề đã nằm trong hình và CC bị khóa với giải thích.
Player phát file MP4 nguồn; chưa có nhiều rendition để đổi chất lượng hoặc adaptive streaming.

- Original giữ kích thước với pixel/SAR/số chẵn tương thích H.264. 16:9 = 1920×1080; 9:16 = 1080×1920; 1:1 = 1080×1080. Crop lấp đầy hoặc pad giữ khung; không stretch.
- Subtitle SRT bật/tắt, burn tùy chọn, libass style cơ bản. FFmpeg cần libass.
- PNG watermark: bốn góc, opacity 0..1, margin 0..300px, scale 1..50% chiều rộng. Branding thumbnail dùng cùng PNG, độc lập overlay video.
- Audio loudnorm single-pass: I=-16 / TP=-1.5 / LRA=11, chưa mastering hai pass.
- Thumbnail JPEG riêng, 1280×720 pad giữ aspect, auto 30% hoặc timestamp nhỏ hơn duration. Unicode title tối đa 120 ký tự, branding tùy chọn. FONT_PATH trỏ TTF có glyph; defaults Arial Windows / DejaVu Sans Linux.
- Language và built-in Edge Neural voice phải khớp. Không voice cloning. Provider/keys/model qua `.env`.

## Tests và kiểm chứng

Từ repo root:

```powershell
$env:PYTHONPATH='backend'
.venv/Scripts/python.exe -m app.smoke --check
.venv/Scripts/python.exe -m ruff check backend scripts
.venv/Scripts/python.exe -m pytest backend/tests -m 'not integration' -q
```

Test nhẹ gồm lifecycle/retry/recovery/duplicate start, API/config/path/upload validation, FFmpeg filter/aspect, metadata, adapter mapping, real subprocess error/timeout/redaction/Unicode. Fixture unit test không được tính là bằng chứng model.

Integration với clip có quyền sử dụng:

```powershell
$env:LOCALIZER_TEST_VIDEO='D:/Videos/rights-cleared-chinese.mp4'
.venv/Scripts/python.exe -m pytest backend/tests -m integration -s
```

Có thể tạo INPUT tiếng Trung bằng Edge voice có sẵn, nền màu và script original, không clone voice hoặc tạo output dịch giả:

```powershell
.venv/Scripts/python.exe scripts/make-smoke-fixture.py
```

Với backend/frontend đang chạy, kiểm chứng acceptance:

```powershell
.venv/Scripts/python.exe -X utf8 scripts/verify-mvp.py
.venv/Scripts/python.exe -m pip install -r backend/requirements-browser.txt
.venv/Scripts/python.exe -X utf8 scripts/verify-browser.py
```

API script chạy engine thật, 9:16 burn/watermark/title/branding, tải bốn file và lưu `workspace/mvp-verification.json`. Browser script dùng Chrome đã cài: upload → Process → Completed → click tải bốn file, kiểm tra 16:9/mobile, lưu screenshot/report. Browser cần quyền tạo named pipe/process của Playwright/Chrome. Frontend build: trong `frontend/`, `pnpm build`.

## Giới hạn / TODO

- Chất lượng dịch/phát âm/alignment cần nghe/xem trên nội dung thật; kiểm tra file và ASR lại không đánh giá chất lượng chủ quan.
- Generic HTTP download đã test. YouTube/TikTok cụ thể phụ thuộc platform/network, chưa xác nhận trong phiên này. Không bypass DRM/paywall/protection; unsupported source báo lỗi.
- Google/Edge và fallback upstream cần mạng, có thể rate limit. Retry chạy lại toàn engine. Local là app/storage, không phải mọi provider offline.
- CPU headless profile chỉ cho faster-whisper/Edge và provider đã cài dependency. GPU/GUI/provider khác cần setup upstream riêng. Thread compatibility CPU xử lý một job.
- Docker chưa implement vì engine/GPU/native runtime; không cung cấp compose giả. Xem `docker/README.md`. Không Redis/auth/analytics/tự đăng video.
- Chưa cancellation/resume giữa stage, auto cleanup upload hoặc sửa nội dung từng cue subtitle. Job gián đoạn Retry fresh attempt.

Người dùng phải có quyền sử dụng nội dung nguồn. Không bypass DRM, paywall, Content ID/copyright detection hoặc tự đăng video lên nền tảng.

## React DOM verification tùy chọn

Khi Chrome bị sandbox chặn, có thể chạy interaction test trong DOM mô phỏng với API và engine thật. Đây không phải kiểm chứng layout/playback của browser.

Trong workspace hiện tại Happy DOM đã cài ngoài repo. Với backend đang chạy, mở terminal phục vụ fixture:

```powershell
.venv/Scripts/python.exe -m http.server 8765 --bind 127.0.0.1 --directory workspace/input/smoke-chinese
```

Terminal khác từ repo root:

```powershell
# Chỉ cần cài nếu chưa có thư mục dependency tùy chọn này:
# npm install --prefix ../.runtime/ui-check happy-dom@20.14.5
$env:LOCALIZER_DOM_MODULE=(Join-Path (Resolve-Path ../.runtime/ui-check) 'node_modules/happy-dom/lib/index.js')
$env:LOCALIZER_TEST_URL='http://127.0.0.1:8765/chinese.mp4'
node scripts/verify-ui.mjs
```

Test mount App.tsx thật, submit Process, chờ job Completed 100%, kiểm tra bốn link tải qua API thật. Không mock fetch hoặc model. Report nằm ở `workspace/react-ui-verification.json`.
