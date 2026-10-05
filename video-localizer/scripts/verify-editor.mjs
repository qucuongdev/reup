// Real React/editor API/FFmpeg export. Media events and DOM layout are simulated.
// Applies a saved edit to LOCALIZER_EDITOR_JOB; original final files stay untouched.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(repo, "frontend/package.json"));
const ts = require("typescript");
for (const extension of [".tsx", ".ts"])
  require.extensions[extension] = (module, filename) => {
    module._compile(
      ts.transpileModule(readFileSync(filename, "utf8"), {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          jsx: ts.JsxEmit.ReactJSX,
          target: ts.ScriptTarget.ES2022,
        },
      }).outputText,
      filename,
    );
  };
const timeline = require(path.join(repo, "frontend/src/timeline.ts"));
const a = {
  id: crypto.randomUUID(),
  job_id: crypto.randomUUID(),
  start: 1,
  end: 5,
};
const b = { ...a, id: crypto.randomUUID(), start: 0, end: 2 };
assert.equal(timeline.length([a, b]), 6);
assert.equal(timeline.locate([a, b], 4).clip.id, b.id);
assert.equal(timeline.locate([a, b], 5).sourceTime, 1);
assert.equal(timeline.locate([a, b], 999).sourceTime, 2);
assert.equal(timeline.split([a], 2)[1].start, 3);
assert.throws(() => timeline.split([a], 0.01));
assert.equal(timeline.trim(a, "start", 999, 9).start, 4.9);
assert.equal(timeline.trim(a, "end", -999, 9).end, 1.1);
assert.equal(timeline.move([a, b], b.id, 0)[0].id, b.id);
assert.equal(timeline.timeLabel(59.999), "1:00.00");
console.log("TIMELINE GEOMETRY PASS");
if (process.argv.includes("--helpers-only")) process.exit(0);

const id = process.env.LOCALIZER_EDITOR_JOB;
assert(id, "Set LOCALIZER_EDITOR_JOB to a completed video to edit");
const { Window } = await import(
  pathToFileURL(
    process.env.LOCALIZER_DOM_MODULE || require.resolve("happy-dom"),
  ).href
);
const window = new Window({ url: "http://127.0.0.1:5173" });
for (const name of [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "Event",
  "MouseEvent",
])
  Object.defineProperty(globalThis, name, {
    value: name === "window" ? window : window[name],
    configurable: true,
  });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const realFetch = globalThis.fetch;
globalThis.fetch = (url, options) =>
  realFetch(new URL(url, "http://127.0.0.1:8000"), options);
const { createElement, act } = require("react");
const { createRoot } = require("react-dom/client");
const Editor = require(
  path.join(repo, "frontend/src/TimelineEditor.tsx"),
).default;
const base = `/api/jobs/${id}/editor`;
const draft = await (await fetch(base)).json();
assert.equal(
  draft.revision,
  0,
  "Use an untouched editor job to avoid overwriting another timeline",
);
const source = draft.sources.find((item) => item.id === id);
assert(source.duration > 5);
const original = Buffer.from(
  await (await fetch(`/api/jobs/${id}/files/final.mp4`)).arrayBuffer(),
);
const mount = window.document.createElement("div");
window.document.body.append(mount);
const root = createRoot(mount);
const button = (label) =>
  [...mount.querySelectorAll("button")].find(
    (item) => item.textContent.trim() === label,
  );
async function click(label) {
  assert(button(label), label);
  await act(async () => button(label).click());
}
async function waitFor(predicate, timeout = 120000) {
  const end = Date.now() + timeout;
  while (!predicate()) {
    assert(Date.now() < end, mount.textContent);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
  }
}
async function input(element, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set.call(element, String(value));
    element.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}
async function ready() {
  const video = mount.querySelector(".editor-preview video");
  Object.defineProperty(video, "duration", {
    value: source.duration,
    configurable: true,
  });
  video.pause = () => video.dispatchEvent(new window.Event("pause"));
  video.play = async () => video.dispatchEvent(new window.Event("play"));
  await act(async () =>
    video.dispatchEvent(new window.Event("loadedmetadata")),
  );
  return video;
}
await act(async () => root.render(createElement(Editor, { jobId: id })));
await waitFor(() => mount.querySelector(".timeline-clip"));
await ready();
assert.equal(mount.querySelector(".player-timeline").hidden, true);
const trimHandle = mount.querySelector('[aria-label="Cắt cuối đoạn 1"]');
trimHandle.setPointerCapture = () => {}; // DOM has no physical pointer capture.
await act(async () => {
  trimHandle.dispatchEvent(
    new window.PointerEvent("pointerdown", {
      bubbles: true,
      pointerId: 1,
      clientX: 100,
    }),
  );
});
await act(async () => {
  trimHandle.dispatchEvent(
    new window.PointerEvent("pointermove", {
      bubbles: true,
      pointerId: 1,
      clientX: 55,
    }),
  );
  trimHandle.dispatchEvent(
    new window.PointerEvent("pointerup", {
      bubbles: true,
      pointerId: 1,
      clientX: 55,
    }),
  );
});
assert(
  Math.abs(
    Number(mount.querySelectorAll(".editor-inspector input")[1].value) -
      (source.duration - 1),
  ) < 0.018,
);
await click("↶ Hoàn tác");
await input(mount.querySelector('[aria-label="Playhead timeline"]'), 2);
await click("✂ Chia đoạn");
assert.equal(mount.querySelectorAll(".timeline-clip").length, 2);
await click("Xóa đoạn");
assert.equal(mount.querySelectorAll(".timeline-clip").length, 1);
await click("↶ Hoàn tác");
assert.equal(mount.querySelectorAll(".timeline-clip").length, 2);
// Select the second interval then trim it to a short export. Pointer geometry is unit tested separately.
await input(mount.querySelector('[aria-label="Playhead timeline"]'), 3);
await ready();
const controls = mount.querySelectorAll(".editor-inspector input");
await input(controls[1], 4);
await click("← Đưa trước");
assert(
  mount
    .querySelector(".editor-inspector strong")
    .textContent.includes("Đoạn 1"),
);
await click("Lưu timeline");
await waitFor(() => mount.textContent.includes("Đã lưu bản 1"));
const saved = await (await fetch(base)).json();
assert.deepEqual(
  saved.clips.map((item) => [item.start, item.end]),
  [
    [2, 4],
    [0, 2],
  ],
);
let video = await ready();
assert.equal(video.currentTime, 2);
await act(async () => {
  await video.play();
  video.currentTime = 4;
  video.dispatchEvent(new window.Event("timeupdate"));
});
assert.notEqual(mount.querySelector(".editor-preview video"), video);
video = await ready();
assert.equal(video.currentTime, 0);
await act(async () => {
  video.currentTime = 2;
  video.dispatchEvent(new window.Event("timeupdate"));
});
assert(mount.querySelector('button[aria-label="Phát"]'));
await click("Xuất bản dựng");
await waitFor(
  () => mount.querySelectorAll(".editor-exports .downloads a").length === 4,
);
assert.equal(mount.querySelector("[role=alert]"), null);
const exportState = (await (await fetch(`${base}/exports`)).json())[0];
assert.equal(exportState.status, "completed");
const names = [];
for (const link of mount.querySelectorAll(".editor-exports .downloads a")) {
  const response = await fetch(link.getAttribute("href"));
  assert.equal(response.status, 200);
  const bytes = (await response.arrayBuffer()).byteLength;
  if (link.textContent !== "subtitle.srt") assert(bytes > 0);
  names.push(link.textContent);
}
const result = await (
  await fetch(`${base}/exports/${exportState.id}/files/metadata.json`)
).json();
assert(Math.abs(result.output.duration - 4) < 0.05);
assert(result.output.has_audio);
assert(Number.isInteger(result.subtitle_cues) && result.subtitle_cues >= 0);
assert.deepEqual(
  Buffer.from(
    await (await fetch(`/api/jobs/${id}/files/final.mp4`)).arrayBuffer(),
  ),
  original,
);
writeFileSync(
  path.join(repo, "workspace/editor-verification.json"),
  JSON.stringify(
    {
      job_id: id,
      export_id: exportState.id,
      simulated_dom: true,
      real_ffmpeg: true,
      original_unchanged: true,
      downloaded: names,
      output: result.output,
    },
    null,
    2,
  ),
);
await act(async () => root.unmount());
window.happyDOM.abort();
console.log("REAL EDITOR UI/API/FFMPEG PASS (simulated DOM/media events)");
