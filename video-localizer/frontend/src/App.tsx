import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import VideoPlayer from "./VideoPlayer";
import TimelineEditor from "./TimelineEditor";
type Job = {
  id: string;
  source_name: string;
  status: string;
  current_step: string;
  progress: number;
  error: string | null;
  created_at: string;
  attempt: number;
  target_language: string;
  burn_subtitle: boolean;
};
type Output = { name: string; size: number; url: string };
type Log = { timestamp: string; level: string; step: string; message: string };
type Report = {
  ready: boolean;
  checks: { name: string; available: boolean; detail: string; hint: string }[];
};
const languages = [
  ["zh-cn", "Chinese"],
  ["en", "English"],
  ["vi", "Vietnamese"],
  ["ja", "Japanese"],
  ["ko", "Korean"],
  ["fr", "French"],
  ["de", "German"],
  ["es", "Spanish"],
];
const voices: Record<string, string[]> = {
  vi: ["vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"],
  en: ["en-US-JennyNeural", "en-US-GuyNeural"],
  "zh-cn": ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"],
  ja: ["ja-JP-NanamiNeural"],
  ko: ["ko-KR-SunHiNeural"],
  fr: ["fr-FR-DeniseNeural"],
  de: ["de-DE-KatjaNeural"],
  es: ["es-ES-ElviraNeural"],
};
const steps: Record<string, string> = {
  ready: "Chưa bắt đầu",
  waiting: "Chờ worker",
  input: "Kiểm tra nguồn",
  downloading: "Downloading",
  transcribing: "Transcribing",
  translating: "Translating",
  dubbing: "Dubbing",
  postprocessing: "Post-processing",
  rendering: "Rendering",
  thumbnail: "Tạo thumbnail",
  done: "Done",
  failed: "Failed",
  interrupted: "Bị gián đoạn",
};
async function api<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api" + url, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : JSON.stringify(payload.detail || `HTTP ${response.status}`),
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
async function upload(file: File, kind: string): Promise<string> {
  const body = new FormData();
  body.append("file", file);
  return (
    await api<{ id: string }>(`/uploads?kind=${kind}`, { method: "POST", body })
  ).id;
}
export default function App() {
  const [tab, setTab] = useState("create");
  const [report, setReport] = useState<Report>();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string>();
  const [editorOpen, setEditorOpen] = useState(false);
  useEffect(() => setEditorOpen(false), [selected]);
  const [files, setFiles] = useState<Output[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [sourceType, setSourceType] = useState("url");
  const [sourceUrl, setSourceUrl] = useState("");
  const [video, setVideo] = useState<File>();
  const [sourceLanguage, setSourceLanguage] = useState("zh-cn");
  const [targetLanguage, setTargetLanguage] = useState("vi");
  const [voice, setVoice] = useState("vi-VN-HoaiMyNeural");
  const [ratio, setRatio] = useState("9:16");
  const [fit, setFit] = useState("crop");
  const [subtitle, setSubtitle] = useState(true);
  const [burn, setBurn] = useState(false);
  const [watermark, setWatermark] = useState(false);
  const [png, setPng] = useState<File>();
  const [position, setPosition] = useState("bottom-right");
  const [opacity, setOpacity] = useState(0.7);
  const [margin, setMargin] = useState(24);
  const [scale, setScale] = useState(0.15);
  const [normalize, setNormalize] = useState(true);
  const [thumbnail, setThumbnail] = useState(true);
  const [mode, setMode] = useState("auto");
  const [timestamp, setTimestamp] = useState(0);
  const [title, setTitle] = useState("");
  const [branding, setBranding] = useState(false);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const latest = await api<Job[]>("/jobs", { signal });
      if (signal?.aborted) return;
      setJobs(latest);
      if (selected) {
        const [outputs, records] = await Promise.all([
          api<Output[]>(`/jobs/${selected}/files`, { signal }),
          api<Log[]>(`/jobs/${selected}/logs`, { signal }),
        ]);
        if (signal?.aborted) return;
        setFiles(outputs);
        setLogs(records);
      }
    },
    [selected],
  );
  useEffect(() => {
    api<Report>("/environment")
      .then(setReport)
      .catch((cause) => setError(String(cause)));
    api<{ source_language: string; target_language: string; voice: string }>(
      "/options",
    )
      .then((options) => {
        setSourceLanguage(options.source_language);
        setTargetLanguage(options.target_language);
        setVoice(options.voice);
      })
      .catch((cause) => setError(String(cause)));
  }, []);
  useEffect(() => {
    let stopped = false;
    const controller = new AbortController();
    const poll = () => {
      if (!stopped)
        refresh(controller.signal).catch((cause) => {
          if (!stopped) setError(String(cause));
        });
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => {
      stopped = true;
      controller.abort();
      clearInterval(interval);
    };
  }, [refresh]);
  async function process(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (sourceType === "local" && !video)
        throw new Error("Chọn video nguồn.");
      if ((watermark || (thumbnail && branding)) && !png)
        throw new Error("Chọn PNG watermark / branding.");
      const sourceFile =
        sourceType === "local" ? await upload(video!, "video") : null;
      const watermarkFile =
        watermark || (thumbnail && branding)
          ? await upload(png!, "watermark")
          : null;
      const job = await api<Job>("/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_type: sourceType,
          source_url: sourceType === "url" ? sourceUrl : null,
          source_file: sourceFile,
          source_language: sourceLanguage,
          target_language: targetLanguage,
          voice,
          output_ratio: ratio,
          fit_mode: fit,
          subtitle_enabled: subtitle,
          burn_subtitle: subtitle && burn,
          watermark_enabled: watermark,
          watermark_file: watermarkFile,
          watermark: { position, opacity, margin, scale },
          normalize_audio: normalize,
          thumbnail_enabled: thumbnail,
          thumbnail_mode: mode,
          thumbnail_timestamp: timestamp,
          thumbnail_title: title,
          thumbnail_branding: thumbnail && branding,
        }),
      });
      setSelected(job.id);
      setTab("jobs");
      await api(`/jobs/${job.id}/start`, { method: "POST" });
      setJobs(await api<Job[]>("/jobs"));
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  async function action(job: Job, kind: string) {
    setBusy(true);
    setError("");
    try {
      if (
        kind === "delete" &&
        !window.confirm("Xóa job và các file của job này?")
      )
        return;
      await api(`/jobs/${job.id}${kind === "delete" ? "" : "/" + kind}`, {
        method: kind === "delete" ? "DELETE" : "POST",
      });
      if (kind === "delete" && selected === job.id) {
        setSelected(undefined);
        setFiles([]);
        setLogs([]);
      }
      setJobs(await api<Job[]>("/jobs"));
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }
  const active = jobs.find((job) => job.id === selected);
  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">LOCAL MEDIA PIPELINE</p>
          <h1>Video Localizer</h1>
          <p>Dịch và lồng tiếng với pyVideoTrans · Xuất video bằng FFmpeg</p>
        </div>
        <span className={`badge ${report?.ready ? "completed" : "queued"}`}>
          {report
            ? report.ready
              ? "Engine sẵn sàng"
              : "Thiếu dependency"
            : "Đang kết nối…"}
        </span>
      </header>
      <nav>
        <button
          className={tab === "create" ? "selected" : ""}
          onClick={() => setTab("create")}
        >
          Create Job
        </button>
        <button
          className={tab === "jobs" ? "selected" : ""}
          onClick={() => setTab("jobs")}
        >
          Jobs ({jobs.length})
        </button>
      </nav>
      {error && (
        <div role="alert" className="error">
          {error}
          <button onClick={() => setError("")}>Đóng</button>
        </div>
      )}
      {report && !report.ready && (
        <section>
          <h2>Thiết lập môi trường</h2>
          {report.checks
            .filter((check) => !check.available)
            .map((check) => (
              <p key={check.name}>
                <b>{check.name}</b>: {check.detail}
                <br />
                {check.hint}
              </p>
            ))}
        </section>
      )}
      {tab === "create" ? (
        <form onSubmit={process}>
          <section>
            <h2>1. Video nguồn</h2>
            <div className="segmented">
              <button
                type="button"
                className={sourceType === "url" ? "selected" : ""}
                onClick={() => setSourceType("url")}
              >
                URL
              </button>
              <button
                type="button"
                className={sourceType === "local" ? "selected" : ""}
                onClick={() => setSourceType("local")}
              >
                Upload
              </button>
            </div>
            {sourceType === "url" ? (
              <label>
                Video URL
                <input
                  type="url"
                  required
                  value={sourceUrl}
                  onChange={(event) => setSourceUrl(event.target.value)}
                  placeholder="https://youtube.com/…"
                />
              </label>
            ) : (
              <label>
                File local
                <input
                  type="file"
                  required
                  accept=".mp4,.mov,.mkv,.webm"
                  onChange={(event) => setVideo(event.target.files?.[0])}
                />
              </label>
            )}
            <p className="note">
              Chỉ xử lý nội dung bạn có quyền sử dụng. File nguồn được giữ trong
              workspace của job.
            </p>
          </section>
          <section>
            <h2>2. Dịch và lồng tiếng</h2>
            <div className="grid">
              <label>
                Source language
                <select
                  value={sourceLanguage}
                  onChange={(event) => setSourceLanguage(event.target.value)}
                >
                  {languages.map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Target language
                <select
                  value={targetLanguage}
                  onChange={(event) => {
                    setTargetLanguage(event.target.value);
                    setVoice(voices[event.target.value][0]);
                  }}
                >
                  {languages.map(([code, label]) => (
                    <option key={code} value={code}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Voice
                <select
                  value={voice}
                  onChange={(event) => setVoice(event.target.value)}
                >
                  {[...new Set([voice, ...(voices[targetLanguage] || [])])].map(
                    (item) => (
                      <option key={item}>{item}</option>
                    ),
                  )}
                </select>
              </label>
            </div>
            <p className="note">
              Giọng Edge-TTS có sẵn. ASR, provider dịch và model cấu hình trong
              .env.
            </p>
          </section>
          <section>
            <h2>3. Video đầu ra</h2>
            <div className="grid">
              <label>
                Format
                <select
                  value={ratio}
                  onChange={(event) => setRatio(event.target.value)}
                >
                  {["original", "16:9", "9:16", "1:1"].map((item) => (
                    <option key={item}>{item}</option>
                  ))}
                </select>
              </label>
              <label>
                Resize
                <select
                  value={fit}
                  onChange={(event) => setFit(event.target.value)}
                >
                  <option value="crop">Crop — lấp đầy khung</option>
                  <option value="pad">Pad — giữ toàn bộ hình</option>
                </select>
              </label>
            </div>
            <div className="checks">
              <label>
                <input
                  type="checkbox"
                  checked={subtitle}
                  onChange={(event) => {
                    setSubtitle(event.target.checked);
                    if (!event.target.checked) setBurn(false);
                  }}
                />
                Subtitle (.srt)
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={burn}
                  disabled={!subtitle}
                  onChange={(event) => setBurn(event.target.checked)}
                />
                Burn subtitle
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={normalize}
                  onChange={(event) => setNormalize(event.target.checked)}
                />
                Normalize audio
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={watermark}
                  onChange={(event) => setWatermark(event.target.checked)}
                />
                Watermark
              </label>
            </div>
            {(watermark || (thumbnail && branding)) && (
              <label>
                PNG watermark / branding
                <input
                  type="file"
                  accept="image/png,.png"
                  required
                  onChange={(event) => setPng(event.target.files?.[0])}
                />
              </label>
            )}
            {watermark && (
              <div className="grid">
                <label>
                  Position
                  <select
                    value={position}
                    onChange={(event) => setPosition(event.target.value)}
                  >
                    {[
                      "top-left",
                      "top-right",
                      "bottom-left",
                      "bottom-right",
                    ].map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Opacity
                  <input
                    type="number"
                    min="0"
                    max="1"
                    step="0.05"
                    value={opacity}
                    onChange={(event) => setOpacity(Number(event.target.value))}
                  />
                </label>
                <label>
                  Margin (px)
                  <input
                    type="number"
                    min="0"
                    max="300"
                    value={margin}
                    onChange={(event) => setMargin(Number(event.target.value))}
                  />
                </label>
                <label>
                  Scale (% chiều rộng)
                  <input
                    type="number"
                    min="1"
                    max="50"
                    value={scale * 100}
                    onChange={(event) =>
                      setScale(Number(event.target.value) / 100)
                    }
                  />
                </label>
              </div>
            )}
          </section>
          <section>
            <h2>4. Thumbnail</h2>
            <label className="check">
              <input
                type="checkbox"
                checked={thumbnail}
                onChange={(event) => setThumbnail(event.target.checked)}
              />
              Generate thumbnail · 1280 × 720
            </label>
            {thumbnail && (
              <>
                <div className="grid">
                  <label>
                    Frame
                    <select
                      value={mode}
                      onChange={(event) => setMode(event.target.value)}
                    >
                      <option value="auto">Auto — 30% thời lượng</option>
                      <option value="timestamp">Timestamp</option>
                    </select>
                  </label>
                  {mode === "timestamp" && (
                    <label>
                      Timestamp (giây)
                      <input
                        type="number"
                        min="0"
                        step="0.1"
                        value={timestamp}
                        onChange={(event) =>
                          setTimestamp(Number(event.target.value))
                        }
                      />
                    </label>
                  )}
                  <label>
                    Title (tùy chọn)
                    <input
                      maxLength={120}
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                  </label>
                </div>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={branding}
                    onChange={(event) => setBranding(event.target.checked)}
                  />
                  Thêm PNG branding lên thumbnail
                </label>
              </>
            )}
          </section>
          <button
            className="primary"
            type="submit"
            disabled={busy || !report?.ready}
          >
            {busy ? "Đang upload / tạo job…" : "Process"}
          </button>
        </form>
      ) : (
        <>
          <section>
            <h2>Jobs</h2>
            <p className="note">
              Tiến độ là tỷ lệ các bước đã hoàn tất, không phải phần trăm thời
              gian render.
            </p>
            {!jobs.length ? (
              <p>Chưa có job. Tạo job để bắt đầu.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Video</th>
                      <th>Status / Current step</th>
                      <th>Progress</th>
                      <th>Created</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr
                        key={job.id}
                        className={selected === job.id ? "active" : ""}
                      >
                        <td>
                          <button
                            className="link"
                            onClick={() => {
                              setSelected(job.id);
                              setFiles([]);
                              setLogs([]);
                            }}
                          >
                            {job.source_name}
                          </button>
                          <small>
                            {job.id.slice(0, 8)} · Lần {job.attempt}
                          </small>
                        </td>
                        <td>
                          <span className={`badge ${job.status}`}>
                            {job.status === "completed"
                              ? "Completed"
                              : job.status}
                          </span>
                          <small>
                            {steps[job.current_step] || job.current_step}
                          </small>
                        </td>
                        <td>
                          <progress max={100} value={job.progress} />
                          <small>{job.progress}%</small>
                        </td>
                        <td>
                          {new Date(job.created_at).toLocaleString("vi-VN")}
                        </td>
                        <td>
                          <div className="actions">
                            <button onClick={() => setSelected(job.id)}>
                              Xem / Log
                            </button>
                            {job.status === "failed" && (
                              <button
                                disabled={busy || !report?.ready}
                                onClick={() => action(job, "retry")}
                              >
                                Retry
                              </button>
                            )}
                            {job.status === "queued" &&
                              job.current_step === "ready" && (
                                <button
                                  disabled={busy || !report?.ready}
                                  onClick={() => action(job, "start")}
                                >
                                  Start
                                </button>
                              )}
                            {["failed", "completed"].includes(job.status) ||
                            job.current_step === "ready" ? (
                              <button
                                disabled={busy}
                                onClick={() => action(job, "delete")}
                              >
                                Xóa
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          {active && (
            <section>
              <h2>Job {active.id.slice(0, 8)}</h2>
              {active.error && <p className="error">{active.error}</p>}
              {active.status === "completed" && (
                <>
                  <button onClick={() => setEditorOpen(!editorOpen)}>
                    {editorOpen ? "Đóng bàn dựng" : "✂ Cắt / ghép video"}
                  </button>
                  {editorOpen && (
                    <TimelineEditor key={active.id} jobId={active.id} />
                  )}
                </>
              )}
              {files.length > 0 && (
                <>
                  {!editorOpen && (
                    <div className="preview">
                      <VideoPlayer
                        key={active.id}
                        src={`/api/jobs/${active.id}/files/final.mp4`}
                        subtitleSrc={
                          files.some((file) => file.name === "subtitle.srt")
                            ? `/api/jobs/${active.id}/subtitle.vtt`
                            : undefined
                        }
                        subtitleLanguage={active.target_language}
                        subtitlesBurned={active.burn_subtitle}
                      />
                      {files.some((file) => file.name === "thumbnail.jpg") && (
                        <img
                          alt="Thumbnail của video"
                          src={`/api/jobs/${active.id}/files/thumbnail.jpg`}
                        />
                      )}
                    </div>
                  )}
                  <div className="downloads">
                    {files.map((file) => (
                      <a key={file.name} href={file.url} download={file.name}>
                        {file.name}
                        <small>{(file.size / 1024).toFixed(1)} KB</small>
                      </a>
                    ))}
                  </div>
                </>
              )}
              <details open={active.status === "failed"}>
                <summary>Log gần nhất ({logs.length})</summary>
                <pre>
                  {logs
                    .map(
                      (record) =>
                        `${record.timestamp} ${record.level} [${record.step}] ${record.message}`,
                    )
                    .join("\n") || "Chưa có log."}
                </pre>
              </details>
            </section>
          )}
        </>
      )}
      <footer>
        Chạy local · SQLite · Một worker · Không tự đăng video lên nền tảng
      </footer>
    </main>
  );
}
