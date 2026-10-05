export type Clip = { id: string; job_id: string; start: number; end: number };
export type Media = {
  id: string;
  name: string;
  duration: number;
  width: number;
  height: number;
  target_language: string;
  burn_subtitle: boolean;
  subtitle: boolean;
  thumbnail: string | null;
};
export const length = (clips: Clip[]) =>
  clips.reduce((sum, clip) => sum + duration(clip), 0);
export const duration = (clip: Clip) =>
  Math.floor((clip.end - clip.start) * 30 + 1e-6) / 30;
export const offsetOf = (clips: Clip[], id: string) => {
  let offset = 0;
  for (const clip of clips) {
    if (clip.id === id) return offset;
    offset += duration(clip);
  }
  return offset;
};
export function locate(clips: Clip[], time: number) {
  let offset = 0;
  for (let i = 0; i < clips.length; i++) {
    const clip = clips[i],
      span = duration(clip);
    if (time < offset + span || i === clips.length - 1)
      return {
        clip,
        offset,
        sourceTime: clip.start + Math.max(0, Math.min(span, time - offset)),
      };
    offset += span;
  }
  throw new Error("Timeline is empty");
}
export function trim(
  clip: Clip,
  edge: "start" | "end",
  value: number,
  sourceDuration: number,
): Clip {
  const snapped = Math.round(value * 30) / 30;
  return edge === "start"
    ? { ...clip, start: Math.max(0, Math.min(clip.end - 0.1, snapped)) }
    : {
        ...clip,
        end: Math.max(clip.start + 0.1, Math.min(sourceDuration, snapped)),
      };
}
export function split(clips: Clip[], time: number): Clip[] {
  if (clips.length >= 32) throw new Error("Tối đa 32 đoạn trong một timeline.");
  const { clip, sourceTime } = locate(clips, time);
  const point = Math.round(sourceTime * 30) / 30;
  if (point - clip.start < 0.1 - 1e-8 || clip.end - point < 0.1 - 1e-8)
    throw new Error("Đặt playhead cách hai đầu đoạn ít nhất 0.1 giây.");
  return clips.flatMap((item) =>
    item.id === clip.id
      ? [
          { ...item, end: point },
          { ...item, id: crypto.randomUUID(), start: point },
        ]
      : [item],
  );
}
export function move(clips: Clip[], id: string, index: number): Clip[] {
  const clip = clips.find((item) => item.id === id);
  if (!clip) return clips;
  const remaining = clips.filter((item) => item.id !== id);
  remaining.splice(Math.max(0, Math.min(index, remaining.length)), 0, clip);
  return remaining;
}
export const timeLabel = (time: number) => {
  const centiseconds = Math.round(Math.max(0, time) * 100);
  return `${Math.floor(centiseconds / 6000)}:${((centiseconds % 6000) / 100).toFixed(2).padStart(5, "0")}`;
};
