import { useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import VideoPlayer from "./VideoPlayer";
import type { VideoPlayerHandle } from "./VideoPlayer";
import {
  length,
  duration,
  locate,
  move,
  offsetOf,
  split,
  timeLabel,
  trim,
} from "./timeline";
import type { Clip, Media } from "./timeline";

type Draft = { revision: number; clips: Clip[]; sources: Media[] };
type Export = {
  id: string;
  status: string;
  progress: number;
  current_step: string;
  error: string | null;
};
type File = { name: string; size: number; url: string };
function ExportDetails({ url }: { url: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>Xem video bản dựng</summary>
      {open && <ExportPreview url={url} />}
    </details>
  );
}
function ExportLogs({ url }: { url: string }) {
  const [text, setText] = useState("");
  return (
    <details
      onToggle={(event) => {
        if (event.currentTarget.open)
          void request<{ timestamp: string; step: string; message: string }[]>(
            `${url}/logs`,
          )
            .then((records) =>
              setText(
                records
                  .map(
                    (item) =>
                      `${item.timestamp} [${item.step}] ${item.message}`,
                  )
                  .join("\n"),
              ),
            )
            .catch((reason) => setText(reason.message));
      }}
    >
      <summary>Log lỗi xuất video</summary>
      <pre>{text || "Đang tải log…"}</pre>
    </details>
  );
}
function ExportPreview({ url }: { url: string }) {
  const [metadata, setMetadata] = useState<{
    contains_burned_subtitles: boolean;
    subtitle_cues: number;
  }>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    request<{ contains_burned_subtitles: boolean; subtitle_cues: number }>(
      `${url}/files/metadata.json`,
    )
      .then((value) => {
        if (active) setMetadata(value);
      })
      .catch((reason) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, [url]);
  return (
    <>
      {error && <p className="error">{error}</p>}
      <VideoPlayer
        src={`${url}/files/final.mp4`}
        subtitlesBurned={metadata?.contains_burned_subtitles}
        subtitleSrc={
          metadata?.subtitle_cues ? `${url}/subtitle.vtt` : undefined
        }
      />
    </>
  );
}
async function request<T>(url: string, body?: unknown): Promise<T> {
  const result = await fetch(
    url,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await result.json();
  if (!result.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
export default function TimelineEditor({ jobId }: { jobId: string }) {
  const base = `/api/jobs/${jobId}/editor`;
  const [clips, setClips] = useState<Clip[]>([]),
    [sources, setSources] = useState<Media[]>([]);
  const [revision, setRevision] = useState(0),
    [selected, setSelected] = useState("");
  const [cursor, setCursor] = useState(0),
    [zoom, setZoom] = useState(45);
  const [undo, setUndo] = useState<Clip[][]>([]),
    [redo, setRedo] = useState<Clip[][]>([]);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [exports, setExports] = useState<Export[]>([]),
    [files, setFiles] = useState<Record<string, File[]>>({});
  const [importId, setImportId] = useState("");
  const player = useRef<VideoPlayerHandle>(null),
    playing = useRef(false),
    pending = useRef<number | null>(null),
    autoplay = useRef(false);
  const drag = useRef<{
    clips: Clip[];
    id: string;
    edge: "start" | "end";
    x: number;
  } | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const total = length(clips),
    clip = clips.find((item) => item.id === selected) || clips[0];
  const media = sources.find((item) => item.id === clip?.job_id);
  useEffect(() => {
    if (clip && pending.current !== null) player.current?.seek(pending.current);
  }, [clips, selected]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(base, { signal: controller.signal })
      .then(async (response) => {
        const draft = await response.json();
        if (!response.ok) throw new Error(draft.detail);
        return draft as Draft;
      })
      .then((draft) => {
        setClips(draft.clips);
        setSources(draft.sources);
        setRevision(draft.revision);
        setSelected(draft.clips[0].id);
        pending.current = draft.clips[0].start;
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(String(reason.message));
      });
    return () => controller.abort();
  }, [base]);
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const items = await request<Export[]>(`${base}/exports`);
        const pairs = await Promise.all(
          items
            .filter((item) => item.status === "completed")
            .map(
              async (item) =>
                [
                  item.id,
                  await request<File[]>(`${base}/exports/${item.id}/files`),
                ] as const,
            ),
        );
        if (!cancelled) {
          setExports(items);
          setFiles(Object.fromEntries(pairs));
        }
      } catch (reason) {
        if (!cancelled) setError((reason as Error).message);
      }
    }
    void poll();
    const timer = window.setInterval(poll, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [base]);

  function pause() {
    playing.current = false;
    autoplay.current = false;
    player.current?.pause();
  }
  function seek(time: number, plan = clips, resume = false) {
    if (!plan.length) return;
    const located = locate(plan, Math.min(length(plan), Math.max(0, time)));
    setCursor(located.offset + located.sourceTime - located.clip.start);
    if (located.clip.id !== selected) {
      pending.current = located.sourceTime;
      autoplay.current = resume;
      setSelected(located.clip.id);
    } else {
      player.current?.seek(located.sourceTime);
    }
  }
  function change(next: Clip[], history = true) {
    pause();
    if (history) {
      setUndo((old) => [...old.slice(-99), clips]);
      setRedo([]);
    }
    setClips(next);
    setNotice("Có thay đổi chưa lưu");
    // Re-mount after edits so the preview starts inside the selected interval.
    const nextClip = next.find((item) => item.id === selected) || next[0];
    pending.current = nextClip.start;
    setSelected(nextClip.id);
    setCursor(offsetOf(next, nextClip.id));
  }
  function attempt(action: () => void) {
    try {
      setError("");
      action();
    } catch (reason) {
      setError((reason as Error).message);
    }
  }
  function onTime(time: number) {
    if (!clip) return;
    const end = clip.start + duration(clip);
    setCursor(
      offsetOf(clips, clip.id) +
        Math.max(0, Math.min(duration(clip), time - clip.start)),
    );
    if (time < clip.start - 0.04) {
      player.current?.seek(clip.start);
      return;
    }
    if (time >= end - 0.015 && playing.current) {
      const next = clips[clips.indexOf(clip) + 1];
      if (next) {
        pending.current = next.start;
        autoplay.current = true;
        setSelected(next.id);
      } else {
        pause();
        player.current?.seek(end);
      }
    } else if (time > end + 0.04) player.current?.seek(end);
  }
  async function save(exportVideo = false) {
    pause();
    setBusy(true);
    setError("");
    try {
      const saved = await request<Draft>(base, { revision, clips });
      setRevision(saved.revision);
      setNotice(`Đã lưu bản ${saved.revision}`);
      if (exportVideo) {
        const item = await request<Export>(`${base}/exports`, {
          revision: saved.revision,
        });
        setExports((old) => [item, ...old]);
        setNotice("Bản dựng đã vào hàng đợi xuất video");
      }
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function startTrim(
    event: PointerEvent<HTMLButtonElement>,
    item: Clip,
    edge: "start" | "end",
  ) {
    event.stopPropagation();
    event.preventDefault();
    pause();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { clips, id: item.id, edge, x: event.clientX };
    pending.current = item.start;
    setSelected(item.id);
  }
  function dragging(event: PointerEvent<HTMLButtonElement>) {
    const state = drag.current;
    if (!state) return;
    const original = state.clips.find((item) => item.id === state.id)!;
    const source = sources.find((item) => item.id === original.job_id)!;
    const next = trim(
      original,
      state.edge,
      original[state.edge] + (event.clientX - state.x) / zoom,
      source.duration,
    );
    setClips(state.clips.map((item) => (item.id === state.id ? next : item)));
  }
  function finishTrim(cancel = false) {
    const state = drag.current;
    if (!state) return;
    drag.current = null;
    if (cancel) setClips(state.clips);
    else {
      setUndo((old) => [...old.slice(-99), state.clips]);
      setRedo([]);
      setNotice("Có thay đổi chưa lưu");
    }
  }
  if (!clip || !media)
    return (
      <div className="editor">
        <p>{error || "Đang mở bàn dựng…"}</p>
      </div>
    );
  const index = clips.indexOf(clip);
  return (
    <div className="editor" aria-label="Bàn dựng video">
      <header className="editor-heading">
        <div>
          <h3>Bàn dựng video</h3>
          <small>
            Video + audio trên một track · bản xuất giữ tỷ lệ của job này
          </small>
        </div>
        <div className="editor-actions">
          <button disabled={busy} onClick={() => void save()}>
            Lưu timeline
          </button>
          <button
            className="primary"
            disabled={busy}
            onClick={() => void save(true)}
          >
            Xuất bản dựng
          </button>
        </div>
      </header>
      <div className="editor-preview">
        <VideoPlayer
          key={clip.id}
          ref={player}
          src={`/api/jobs/${clip.job_id}/files/final.mp4`}
          subtitleSrc={
            media.subtitle ? `/api/jobs/${clip.job_id}/subtitle.vtt` : undefined
          }
          subtitleLanguage={media.target_language}
          subtitlesBurned={media.burn_subtitle}
          showSeekBar={false}
          displayPosition={{ current: cursor, duration: total }}
          onPlaybackChange={(value) => {
            playing.current = value;
          }}
          onReady={() => {
            player.current?.seek(pending.current ?? clip.start);
            pending.current = null;
            if (autoplay.current) {
              autoplay.current = false;
              void player.current
                ?.play()
                .catch((reason) => setError(reason.message));
            }
          }}
          onTimeChange={onTime}
          onEnded={() => {
            const next = clips[index + 1];
            if (next) {
              pending.current = next.start;
              autoplay.current = true;
              setSelected(next.id);
            } else pause();
          }}
        />
      </div>
      <div className="editor-toolbar">
        <button
          title="Chia đoạn tại playhead"
          onClick={() => attempt(() => change(split(clips, cursor)))}
        >
          ✂ Chia đoạn
        </button>
        <button
          disabled={clips.length === 1}
          onClick={() => change(clips.filter((item) => item.id !== clip.id))}
        >
          Xóa đoạn
        </button>
        <button
          disabled={!undo.length}
          onClick={() => {
            const previous = undo[undo.length - 1];
            setUndo(undo.slice(0, -1));
            setRedo((old) => [...old, clips]);
            change(previous, false);
          }}
        >
          ↶ Hoàn tác
        </button>
        <button
          disabled={!redo.length}
          onClick={() => {
            const next = redo[redo.length - 1];
            setRedo(redo.slice(0, -1));
            setUndo((old) => [...old, clips]);
            change(next, false);
          }}
        >
          ↷ Làm lại
        </button>
        <label>
          Zoom{" "}
          <input
            aria-label="Zoom timeline"
            type="range"
            min="8"
            max="120"
            value={zoom}
            onChange={(event) => setZoom(Number(event.target.value))}
          />
        </label>
        <button
          onClick={() =>
            setZoom(
              Math.max(
                8,
                Math.min(
                  120,
                  ((scroll.current?.clientWidth || 800) - 24) / total,
                ),
              ),
            )
          }
        >
          Vừa timeline
        </button>
      </div>
      <div className="editor-scrub">
        <output>
          {timeLabel(cursor)} / {timeLabel(total)}
        </output>
        <input
          aria-label="Playhead timeline"
          type="range"
          min="0"
          max={total}
          step={1 / 30}
          value={cursor}
          onChange={(event) => {
            pause();
            seek(Number(event.target.value));
          }}
        />
      </div>
      <div className="timeline-scroll" ref={scroll}>
        <div
          className="timeline-canvas"
          style={{ width: Math.max(600, total * zoom) }}
        >
          <div
            className="timeline-ruler"
            onClick={(event) => {
              pause();
              seek(
                (event.clientX -
                  event.currentTarget.getBoundingClientRect().left) /
                  zoom,
              );
            }}
          >
            {Array.from(
              { length: Math.ceil(total / Math.max(1, Math.ceil(70 / zoom))) },
              (_, i) => i * Math.max(1, Math.ceil(70 / zoom)),
            ).map((time) => (
              <span key={time} style={{ left: time * zoom }}>
                {timeLabel(time)}
              </span>
            ))}
          </div>
          <div className="timeline-track">
            {clips.map((item, i) => {
              const source = sources.find((value) => value.id === item.job_id)!;
              return (
                <div
                  key={item.id}
                  className={`timeline-clip ${item.id === clip.id ? "is-selected" : ""}`}
                  style={{ width: duration(item) * zoom }}
                  draggable={!drag.current}
                  onDragStart={(event) => {
                    pause();
                    event.dataTransfer.setData("text/plain", item.id);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    const id = event.dataTransfer.getData("text/plain");
                    if (id !== item.id) change(move(clips, id, i));
                  }}
                  onClick={() => {
                    pause();
                    seek(offsetOf(clips, item.id));
                  }}
                  title={`${source.name} · ${timeLabel(item.start)} → ${timeLabel(item.end)}`}
                >
                  <button
                    className="trim-handle left"
                    aria-label={`Cắt đầu đoạn ${i + 1}`}
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => startTrim(event, item, "start")}
                    onPointerMove={dragging}
                    onPointerUp={() => finishTrim()}
                    onPointerCancel={() => finishTrim(true)}
                  >
                    ⋮
                  </button>
                  {source.thumbnail && (
                    <img draggable={false} src={source.thumbnail} alt="" />
                  )}
                  <span>
                    {i + 1}. {source.name}
                  </span>
                  <small>{timeLabel(duration(item))}</small>
                  <button
                    className="trim-handle right"
                    aria-label={`Cắt cuối đoạn ${i + 1}`}
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => startTrim(event, item, "end")}
                    onPointerMove={dragging}
                    onPointerUp={() => finishTrim()}
                    onPointerCancel={() => finishTrim(true)}
                  >
                    ⋮
                  </button>
                </div>
              );
            })}
          </div>
          <div className="timeline-playhead" style={{ left: cursor * zoom }}>
            <span />
          </div>
        </div>
      </div>
      <div className="editor-inspector">
        <strong>
          Đoạn {index + 1}: {media.name}
        </strong>
        <label>
          Bắt đầu (giây)
          <input
            type="number"
            min="0"
            max={clip.end - 0.1}
            step={1 / 30}
            value={Number(clip.start.toFixed(3))}
            onChange={(event) => {
              if (Number.isFinite(event.target.valueAsNumber))
                change(
                  clips.map((item) =>
                    item.id === clip.id
                      ? trim(
                          item,
                          "start",
                          event.target.valueAsNumber,
                          media.duration,
                        )
                      : item,
                  ),
                );
            }}
          />
        </label>
        <label>
          Kết thúc (giây)
          <input
            type="number"
            min={clip.start + 0.1}
            max={media.duration}
            step={1 / 30}
            value={Number(clip.end.toFixed(3))}
            onChange={(event) => {
              if (Number.isFinite(event.target.valueAsNumber))
                change(
                  clips.map((item) =>
                    item.id === clip.id
                      ? trim(
                          item,
                          "end",
                          event.target.valueAsNumber,
                          media.duration,
                        )
                      : item,
                  ),
                );
            }}
          />
        </label>
        <button
          disabled={index === 0}
          onClick={() => change(move(clips, clip.id, index - 1))}
        >
          ← Đưa trước
        </button>
        <button
          disabled={index === clips.length - 1}
          onClick={() => change(move(clips, clip.id, index + 1))}
        >
          Đưa sau →
        </button>
      </div>
      <div className="editor-import">
        <select
          aria-label="Video để ghép"
          value={importId}
          onChange={(event) => setImportId(event.target.value)}
        >
          <option value="">Chọn video đã hoàn tất để ghép…</option>
          {sources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.name} ({source.id.slice(0, 8)})
            </option>
          ))}
        </select>
        <button
          disabled={!importId || clips.length >= 32}
          onClick={() => {
            const source = sources.find((item) => item.id === importId)!;
            change([
              ...clips,
              {
                id: crypto.randomUUID(),
                job_id: source.id,
                start: 0,
                end: source.duration,
              },
            ]);
          }}
        >
          + Thêm vào cuối
        </button>
      </div>
      {clips.some(
        (item) =>
          sources.find((source) => source.id === item.job_id)?.burn_subtitle,
      ) && (
        <small>
          Đoạn có phụ đề burn sẽ giữ nguyên chữ trong hình. Subtitle rời được
          cắt và đổi thời gian khi xuất.
        </small>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="editor-exports">
        <h4>Bản dựng đã xuất</h4>
        {!exports.length && (
          <small>Chưa có bản xuất. Video gốc vẫn được giữ nguyên.</small>
        )}
        {exports.map((item) => (
          <article key={item.id}>
            <strong>
              {item.id.slice(0, 8)} · {item.status}
            </strong>
            <span>
              {item.current_step} · {item.progress}%
            </span>
            {["queued", "rendering"].includes(item.status) && (
              <progress value={item.progress} max="100" />
            )}
            {item.error && <p className="error">{item.error}</p>}
            {item.error && <ExportLogs url={`${base}/exports/${item.id}`} />}
            <div className="downloads">
              {(files[item.id] || []).map((file) => (
                <a key={file.name} href={file.url} download>
                  {file.name}
                </a>
              ))}
            </div>
            {item.status === "completed" && (
              <ExportDetails url={`${base}/exports/${item.id}`} />
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
