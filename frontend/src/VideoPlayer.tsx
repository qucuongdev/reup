import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { CSSProperties, KeyboardEvent } from "react";

const speeds = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
function clock(seconds: number): string {
  const total = Math.floor(Math.max(0, seconds));
  const hours = Math.floor(total / 3600);
  return `${hours ? hours + ":" : ""}${String(Math.floor((total % 3600) / 60)).padStart(hours ? 2 : 1, "0")}:${String(total % 60).padStart(2, "0")}`;
}
function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    play: "M8 5v14l11-7Z",
    pause: "M7 5v14M17 5v14",
    volume: "M4 9h4l5-4v14l-5-4H4ZM17 8a6 6 0 0 1 0 8M20 5a10 10 0 0 1 0 14",
    muted: "M4 9h4l5-4v14l-5-4H4ZM17 9l5 6M22 9l-5 6",
    settings:
      "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM10 2h4l1 3 3 1 3 2-1 4 1 4-3 2-3 1-1 3h-4l-1-3-3-1-3-2 1-4-1-4 3-2 3-1Z",
    fullscreen: "M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5",
    theater: "M3 6h18v12H3Z",
    pip: "M3 5h18v14H3ZM12 11h7v6h-7Z",
    back: "M15 5l-7 7 7 7",
    cc: "M3 5h18v14H3ZM10 10H7v4h3M18 10h-3v4h3",
  };
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={paths[name]}
        fill={name === "play" ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth={name === "pause" ? 4 : 1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function SeekIcon({ forward = false }: { forward?: boolean }) {
  return (
    <svg
      width="24"
      height="24"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <g
        transform={forward ? "translate(24 0) scale(-1 1)" : undefined}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M5 8a8 8 0 1 1-1 7" />
        <path d="M5 3v5h5" />
      </g>
      <text
        x="12"
        y="16"
        textAnchor="middle"
        fontSize="8"
        fontWeight="600"
        fill="currentColor"
      >
        10
      </text>
    </svg>
  );
}

type Props = {
  src: string;
  subtitleSrc?: string;
  subtitleLanguage?: string;
  subtitlesBurned?: boolean;
  onTimeChange?: (time: number) => void;
  onPlaybackChange?: (playing: boolean) => void;
  onReady?: () => void;
  onEnded?: () => void;
  showSeekBar?: boolean;
  displayPosition?: { current: number; duration: number };
};
export type VideoPlayerHandle = {
  seek: (time: number) => void;
  pause: () => void;
  play: () => Promise<void>;
};
const VideoPlayer = forwardRef<VideoPlayerHandle, Props>(function VideoPlayer(
  {
    src,
    subtitleSrc,
    subtitleLanguage = "vi",
    subtitlesBurned = false,
    onTimeChange,
    onPlaybackChange,
    onReady,
    onEnded,
    showSeekBar = true,
    displayPosition,
  }: Props,
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const hideTimer = useRef<number | undefined>(undefined);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [position, setPosition] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [paused, setPaused] = useState(true);
  const [waiting, setWaiting] = useState(false);
  const [muted, setMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [speed, setSpeed] = useState(1);
  const [captions, setCaptions] = useState(false);
  const [captionError, setCaptionError] = useState(false);
  const [controlsVisible, setControlsVisible] = useState(true);
  const [menu, setMenu] = useState<"settings" | "speed" | null>(null);
  const [theater, setTheater] = useState(false);
  const [resolution, setResolution] = useState("");
  const [hoverTime, setHoverTime] = useState<number>();
  const ready = duration > 0 && !error;
  const readyCallback = useRef(onReady);
  readyCallback.current = onReady;
  const timeCallback = useRef(onTimeChange);
  timeCallback.current = onTimeChange;
  useEffect(() => {
    if (paused || !timeCallback.current) return;
    let frame: number;
    function tick() {
      if (video.current) timeCallback.current?.(video.current.currentTime);
      frame = window.requestAnimationFrame(tick);
    }
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [paused]);
  useEffect(() => {
    if (duration > 0) readyCallback.current?.();
  }, [duration]);
  useImperativeHandle(ref, () => ({
    seek,
    pause: () => video.current?.pause(),
    play: async () => {
      await video.current?.play();
    },
  }));
  const ccAvailable = !!subtitleSrc && !subtitlesBurned && !captionError;
  const ccTitle = subtitlesBurned
    ? "Phụ đề đã burn vào video, không thể tắt"
    : captionError
      ? "Không tải được phụ đề"
      : !subtitleSrc
        ? "Video không có phụ đề rời"
        : captions
          ? "Tắt phụ đề (C)"
          : "Bật phụ đề (C)";

  function reveal() {
    setControlsVisible(true);
    window.clearTimeout(hideTimer.current);
    if (!paused && !menu && !waiting)
      hideTimer.current = window.setTimeout(
        () => setControlsVisible(false),
        2500,
      );
  }
  useEffect(() => {
    reveal();
    return () => window.clearTimeout(hideTimer.current);
  }, [paused, menu, waiting]);

  function syncCaptions() {
    if (!video.current) return;
    for (const track of Array.from(video.current.textTracks)) {
      track.mode = captions && ccAvailable ? "showing" : "disabled";
      for (const cue of Array.from(track.cues || [])) {
        if ("line" in cue) (cue as VTTCue).line = controlsVisible ? -4 : -1;
      }
    }
  }
  useEffect(syncCaptions, [captions, ccAvailable, controlsVisible]);

  function seek(seconds: number) {
    if (!video.current || error || !Number.isFinite(seconds)) return;
    const available = Number.isFinite(video.current.duration)
      ? video.current.duration
      : duration;
    if (available <= 0) return;
    const target = Math.min(available, Math.max(0, seconds));
    video.current.currentTime = target;
    setCurrentTime(target);
    onTimeChange?.(target);
    reveal();
  }
  async function togglePlayback() {
    if (!video.current || !ready) return;
    if (!video.current.paused) {
      video.current.pause();
      return;
    }
    try {
      await video.current.play();
    } catch {
      setNotice(
        "Không thể bắt đầu phát. Thử bấm Phát lại hoặc tải final.mp4 để xem.",
      );
    }
  }
  function changeSpeed(value: number) {
    if (!video.current) return;
    video.current.playbackRate = value;
    setSpeed(value);
  }
  function toggleMute() {
    if (video.current) video.current.muted = !video.current.muted;
  }
  async function fullscreen() {
    try {
      if (document.fullscreenElement === stage.current)
        await document.exitFullscreen();
      else await stage.current?.requestFullscreen();
    } catch {
      setNotice("Trình duyệt không cho mở toàn màn hình.");
    }
  }
  async function pictureInPicture() {
    try {
      if (document.pictureInPictureElement)
        await document.exitPictureInPicture();
      else await video.current?.requestPictureInPicture();
    } catch {
      setNotice("Trình duyệt không cho mở cửa sổ nổi ở video này.");
    }
  }
  function keydown(event: KeyboardEvent<HTMLDivElement>) {
    const element = event.target as HTMLElement;
    if (element.closest("input,select,textarea,[contenteditable=true]")) return;
    const key = event.key.toLowerCase();
    if (key === "escape") {
      setMenu(null);
      return;
    }
    if ((key === " " || key === "enter") && element.closest("button,summary,a"))
      return;
    let handled = true;
    if (key === " " || key === "k") void togglePlayback();
    else if (key === "arrowleft") seek(currentTime - 5);
    else if (key === "arrowright") seek(currentTime + 5);
    else if (key === "j") seek(currentTime - 10);
    else if (key === "l") seek(currentTime + 10);
    else if (key === "m") toggleMute();
    else if (key === "c" && ccAvailable) setCaptions((value) => !value);
    else if (key === "f") void fullscreen();
    else if (key === "t") setTheater((value) => !value);
    else if ((key === "arrowup" || key === "arrowdown") && video.current) {
      video.current.volume = Math.max(
        0,
        Math.min(1, video.current.volume + (key === "arrowup" ? 0.05 : -0.05)),
      );
      video.current.muted = false;
    } else if (key === "<" || key === ">")
      changeSpeed(
        speeds[
          Math.max(
            0,
            Math.min(
              speeds.length - 1,
              speeds.indexOf(speed) + (key === ">" ? 1 : -1),
            ),
          )
        ],
      );
    else if (/^[0-9]$/.test(key)) seek((duration * Number(key)) / 10);
    else handled = false;
    if (handled) {
      event.preventDefault();
      reveal();
    }
  }
  function updateBuffer() {
    const ranges = video.current?.buffered;
    setBuffered(ranges?.length ? ranges.end(ranges.length - 1) : 0);
  }

  return (
    <div
      className={`video-player${theater ? " is-theater" : ""}${!controlsVisible ? " controls-hidden" : ""}`}
    >
      <div
        className="player-stage"
        ref={stage}
        tabIndex={0}
        role="region"
        aria-label="Trình phát video"
        onKeyDown={keydown}
        onPointerMove={reveal}
        onPointerDown={reveal}
        onFocus={reveal}
      >
        <video
          ref={video}
          playsInline
          preload="metadata"
          src={src}
          onClick={() => {
            setMenu(null);
            void togglePlayback();
          }}
          onDoubleClick={fullscreen}
          onPlay={() => {
            setPaused(false);
            onPlaybackChange?.(true);
          }}
          onPause={() => {
            setPaused(true);
            onPlaybackChange?.(false);
          }}
          onEnded={() => {
            setPaused(true);
            setWaiting(false);
            onEnded?.();
          }}
          onWaiting={() => setWaiting(true)}
          onPlaying={() => setWaiting(false)}
          onCanPlay={() => setWaiting(false)}
          onVolumeChange={(event) => {
            setMuted(event.currentTarget.muted);
            setVolume(event.currentTarget.volume);
          }}
          onRateChange={(event) => setSpeed(event.currentTarget.playbackRate)}
          onLoadedMetadata={(event) => {
            const item = event.currentTarget;
            setDuration(Number.isFinite(item.duration) ? item.duration : 0);
            setCurrentTime(item.currentTime);
            setResolution(`${item.videoWidth} × ${item.videoHeight}`);
            setError("");
          }}
          onDurationChange={(event) => {
            if (Number.isFinite(event.currentTarget.duration))
              setDuration(event.currentTarget.duration);
          }}
          onTimeUpdate={(event) => {
            setCurrentTime(event.currentTarget.currentTime);
            onTimeChange?.(event.currentTarget.currentTime);
          }}
          onSeeked={(event) => {
            setCurrentTime(event.currentTarget.currentTime);
            setWaiting(false);
          }}
          onProgress={updateBuffer}
          onError={() =>
            setError(
              "Không phát được video trong trình duyệt. Bạn có thể tải final.mp4 để xem trên máy.",
            )
          }
        >
          {subtitleSrc && !subtitlesBurned && (
            <track
              kind="subtitles"
              src={subtitleSrc}
              srcLang={subtitleLanguage}
              label={
                subtitleLanguage === "vi" ? "Tiếng Việt" : subtitleLanguage
              }
              onLoad={syncCaptions}
              onError={() => {
                setCaptionError(true);
                setCaptions(false);
                setNotice(
                  "Không tải được phụ đề rời. File subtitle.srt vẫn có thể tải ở bên dưới.",
                );
              }}
            />
          )}
        </video>
        {paused && ready && !menu && (
          <button
            type="button"
            className="player-center-play"
            aria-label="Phát video"
            onClick={togglePlayback}
          >
            <Icon name="play" />
          </button>
        )}
        {waiting && !paused && (
          <div
            className="player-buffering"
            role="status"
            aria-label="Đang tải video"
          />
        )}
        {menu && (
          <div
            className="player-menu"
            role="dialog"
            aria-label={menu === "speed" ? "Tốc độ phát" : "Cài đặt phát"}
          >
            {menu === "speed" ? (
              <>
                <button
                  className="player-menu-heading"
                  onClick={() => setMenu("settings")}
                >
                  <Icon name="back" />
                  Tốc độ phát
                </button>
                {speeds.map((value) => (
                  <button
                    key={value}
                    className="player-menu-row"
                    aria-pressed={speed === value}
                    onClick={() => {
                      changeSpeed(value);
                      setMenu("settings");
                    }}
                  >
                    <span>{value === 1 ? "Bình thường" : `${value}×`}</span>
                    <span>{speed === value ? "✓" : ""}</span>
                  </button>
                ))}
              </>
            ) : (
              <>
                <div className="player-menu-heading">Cài đặt</div>
                <button
                  className="player-menu-row"
                  onClick={() => setMenu("speed")}
                >
                  <span>Tốc độ phát</span>
                  <span>{speed === 1 ? "Bình thường" : `${speed}×`} ›</span>
                </button>
                <button
                  className="player-menu-row"
                  disabled={!ccAvailable}
                  title={ccTitle}
                  onClick={() => setCaptions((value) => !value)}
                >
                  <span>Phụ đề</span>
                  <span>
                    {subtitlesBurned
                      ? "Đã burn"
                      : !subtitleSrc
                        ? "Không có"
                        : captions
                          ? subtitleLanguage === "vi"
                            ? "Tiếng Việt"
                            : subtitleLanguage
                          : "Tắt"}
                  </span>
                </button>
                <div className="player-menu-row player-source-quality">
                  <span>Chất lượng nguồn</span>
                  <span>{resolution || "Đang tải"}</span>
                </div>
                <form
                  className="player-jump"
                  onSubmit={(event) => {
                    event.preventDefault();
                    seek(Number.parseFloat(position));
                    setMenu(null);
                  }}
                >
                  <label>
                    Đến vị trí (giây)
                    <input
                      type="number"
                      min={0}
                      max={duration || 0}
                      step={0.1}
                      value={position}
                      disabled={!ready}
                      onChange={(event) => setPosition(event.target.value)}
                    />
                  </label>
                  <button
                    type="submit"
                    disabled={
                      !ready || !Number.isFinite(Number.parseFloat(position))
                    }
                  >
                    Đi đến
                  </button>
                </form>
                <small>
                  Space/K: phát · ←/→: tua · J/L: ±10s
                  <br />
                  M: âm thanh · C: phụ đề · F: toàn màn hình
                </small>
              </>
            )}
          </div>
        )}
        <div className="seek-controls">
          <div
            className="player-timeline"
            hidden={!showSeekBar}
            onPointerLeave={() => setHoverTime(undefined)}
          >
            {hoverTime !== undefined && (
              <span
                className="player-time-tooltip"
                style={{
                  left: `clamp(24px, ${duration ? (hoverTime / duration) * 100 : 0}%, calc(100% - 24px))`,
                }}
              >
                {clock(hoverTime)}
              </span>
            )}
            <input
              type="range"
              aria-label="Tua video"
              aria-valuetext={`${clock(currentTime)} / ${clock(duration)}`}
              min={0}
              max={duration || 1}
              step={0.1}
              value={Math.min(currentTime, duration)}
              disabled={!ready}
              onChange={(event) => seek(Number(event.target.value))}
              onPointerMove={(event) => {
                const rect = event.currentTarget.getBoundingClientRect();
                if (ready && rect.width)
                  setHoverTime(
                    Math.max(
                      0,
                      Math.min(
                        duration,
                        ((event.clientX - rect.left) / rect.width) * duration,
                      ),
                    ),
                  );
              }}
              style={
                {
                  "--played": `${duration ? (currentTime / duration) * 100 : 0}%`,
                  "--buffered": `${duration ? (Math.max(currentTime, buffered) / duration) * 100 : 0}%`,
                } as CSSProperties
              }
            />
          </div>
          <div className="seek-actions">
            <button
              type="button"
              className="player-icon"
              disabled={!ready}
              aria-label={paused ? "Phát" : "Tạm dừng"}
              title={paused ? "Phát (K)" : "Tạm dừng (K)"}
              onClick={togglePlayback}
            >
              <Icon name={paused ? "play" : "pause"} />
            </button>
            <button
              type="button"
              className="player-icon player-skip"
              aria-label="Tua lùi 10 giây"
              title="Tua lùi 10 giây (J)"
              disabled={!ready}
              onClick={() => seek(currentTime - 10)}
            >
              <SeekIcon />
            </button>
            <button
              type="button"
              className="player-icon player-skip"
              aria-label="Tua tiến 10 giây"
              title="Tua tiến 10 giây (L)"
              disabled={!ready}
              onClick={() => seek(currentTime + 10)}
            >
              <SeekIcon forward />
            </button>
            <div className="player-volume-group">
              <button
                type="button"
                className="player-icon"
                aria-label={muted ? "Bật âm thanh" : "Tắt âm thanh"}
                title="Âm thanh (M)"
                onClick={toggleMute}
              >
                <Icon name={muted || volume === 0 ? "muted" : "volume"} />
              </button>
              <input
                className="player-volume"
                type="range"
                aria-label="Âm lượng"
                min={0}
                max={1}
                step={0.05}
                value={muted ? 0 : volume}
                onChange={(event) => {
                  if (video.current) {
                    video.current.volume = Number(event.target.value);
                    video.current.muted = false;
                  }
                }}
              />
            </div>
            <output>
              {clock(displayPosition?.current ?? currentTime)} /{" "}
              {clock(displayPosition?.duration ?? duration)}
            </output>
            <div className="player-right-controls">
              <button
                type="button"
                className={`player-icon player-cc${captions ? " enabled" : ""}`}
                aria-label="Phụ đề"
                aria-pressed={captions || subtitlesBurned}
                title={ccTitle}
                disabled={!ccAvailable}
                onClick={() => setCaptions((value) => !value)}
              >
                <Icon name="cc" />
              </button>
              <button
                type="button"
                className={`player-icon${menu ? " enabled" : ""}`}
                aria-label="Cài đặt"
                aria-expanded={!!menu}
                title="Cài đặt"
                onClick={() => setMenu(menu ? null : "settings")}
              >
                <Icon name="settings" />
              </button>
              {document.pictureInPictureEnabled && (
                <button
                  type="button"
                  className="player-icon player-pip"
                  aria-label="Cửa sổ nổi"
                  title="Cửa sổ nổi"
                  disabled={!ready}
                  onClick={pictureInPicture}
                >
                  <Icon name="pip" />
                </button>
              )}
              <button
                type="button"
                className="player-icon player-theater"
                aria-label="Chế độ rạp"
                aria-pressed={theater}
                title="Chế độ rạp (T)"
                onClick={() => setTheater((value) => !value)}
              >
                <Icon name="theater" />
              </button>
              {typeof document.documentElement.requestFullscreen ===
                "function" && (
                <button
                  type="button"
                  className="player-icon"
                  aria-label="Toàn màn hình"
                  title="Toàn màn hình (F)"
                  onClick={fullscreen}
                >
                  <Icon name="fullscreen" />
                </button>
              )}
            </div>
          </div>
          {!ready && !error && <small>Đang tải thông tin video…</small>}
        </div>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {notice && <small role="status">{notice}</small>}
    </div>
  );
});
export default VideoPlayer;
