// React interaction test against the real API/engine, in a simulated DOM.
// This does not verify Chrome layout, playback, or native downloads.
// Optional dependency: happy-dom (LOCALIZER_DOM_MODULE may point to its index.js).
import assert from "node:assert/strict";
import { createRequire, Module } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(repo, "frontend/package.json"));
const domPath = process.env.LOCALIZER_DOM_MODULE;
const { Window } = await import(
  pathToFileURL(domPath || require.resolve("happy-dom")).href
);
const window = new Window({ url: "http://127.0.0.1:5173" });
for (const name of [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "Event",
  "MouseEvent",
]) {
  Object.defineProperty(globalThis, name, {
    value: name === "window" ? window : window[name],
    configurable: true,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const networkFetch = globalThis.fetch;
globalThis.fetch = (url, options) =>
  networkFetch(new URL(url, "http://127.0.0.1:8000"), options);
const React = require("react");
const { act } = React;
const { createRoot } = require("react-dom/client");
const ts = require("typescript");
require.extensions[".tsx"] = (module, filename) => {
  const result = ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  });
  module._compile(result.outputText, filename);
};
require.extensions[".ts"] = require.extensions[".tsx"];
const code = ts.transpileModule(
  readFileSync(path.join(repo, "frontend/src/App.tsx"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX,
      target: ts.ScriptTarget.ES2022,
    },
  },
).outputText;
const compiled = new Module(path.join(repo, "frontend/src/App.test.cjs"));
compiled.filename = path.join(repo, "frontend/src/App.test.cjs");
compiled.paths = Module._nodeModulePaths(path.join(repo, "frontend"));
compiled._compile(code, compiled.filename);
const App = compiled.exports.default;
const mount = window.document.createElement("div");
window.document.body.append(mount);
const root = createRoot(mount);
const button = (name) =>
  [...mount.querySelectorAll("button")].find(
    (element) =>
      element.getAttribute("aria-label") === name ||
      element.textContent.trim() === name,
  );
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 100));
  });
}
async function waitFor(check, timeout = 1800000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    await settle();
    if (check()) return;
  }
  throw new Error("React UI check timed out: " + mount.textContent);
}
await act(async () => {
  root.render(
    React.createElement(
      process.argv.includes("--player-only")
        ? require(path.join(repo, "frontend/src/VideoPlayer.tsx")).default
        : App,
      process.argv.includes("--player-only")
        ? { src: "/example.mp4", subtitleSrc: "/example.vtt" }
        : {},
    ),
  );
});
if (process.argv.includes("--player-only")) {
  const video = mount.querySelector("video");
  const slider = mount.querySelector("input[type=range]");
  assert(!video.hasAttribute("controls"), "Avoid duplicate native controls");
  assert.equal(
    video.parentElement,
    mount.querySelector(".seek-controls").parentElement,
  );
  assert(slider.disabled, "Seeking must wait for media metadata");
  Object.defineProperty(video, "duration", { value: 95, configurable: true });
  const textTrack = { mode: "disabled", cues: [{ line: "auto" }] };
  Object.defineProperty(video, "textTracks", {
    value: [textTrack],
    configurable: true,
  });
  await act(async () => {
    video.dispatchEvent(new window.Event("loadedmetadata"));
  });
  assert(!slider.disabled && slider.max === "95");
  await act(async () => {
    video.dispatchEvent(new window.Event("play"));
  });
  assert(mount.querySelector('button[aria-label="Tạm dừng"]'));
  await act(async () => {
    video.dispatchEvent(new window.Event("pause"));
  });
  assert(mount.querySelector('button[aria-label="Phát"]'));
  video.muted = true;
  await act(async () => {
    video.dispatchEvent(new window.Event("volumechange"));
  });
  assert(mount.querySelector('button[aria-label="Bật âm thanh"]'));
  await act(async () => {
    button("Tua tiến 10 giây").click();
  });
  assert.equal(video.currentTime, 10);
  await act(async () => {
    button("Tua lùi 10 giây").click();
    button("Tua lùi 10 giây").click();
  });
  assert.equal(video.currentTime, 0);
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set.call(slider, "42.5");
    slider.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
  assert.equal(video.currentTime, 42.5);
  assert.equal(mount.querySelector("output").textContent, "0:42 / 1:35");
  await act(async () => {
    button("Phụ đề").click();
  });
  assert.equal(textTrack.mode, "showing");
  assert.equal(textTrack.cues[0].line, -4);
  await act(async () => {
    button("Phụ đề").click();
  });
  assert.equal(textTrack.mode, "disabled");
  const playerStage = mount.querySelector(".player-stage");
  await act(async () => {
    playerStage.dispatchEvent(
      new window.KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
    );
  });
  assert.equal(video.currentTime, 37.5);
  await act(async () => {
    playerStage.dispatchEvent(
      new window.KeyboardEvent("keydown", { key: "5", bubbles: true }),
    );
  });
  assert.equal(video.currentTime, 47.5);
  await act(async () => {
    button("Cài đặt").click();
  });
  await act(async () => {
    mount.querySelector(".player-menu-row").click();
  });
  await act(async () => {
    button("1.5×").click();
  });
  assert.equal(video.playbackRate, 1.5);
  await act(async () => {
    button("Cài đặt").click();
    video.dispatchEvent(new window.Event("play"));
  });
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2700));
  });
  assert(
    mount.querySelector(".controls-hidden"),
    "Controls hide during playback",
  );
  await act(async () => {
    playerStage.dispatchEvent(
      new window.Event("pointermove", { bubbles: true }),
    );
  });
  assert(!mount.querySelector(".controls-hidden"));
  await act(async () => {
    video.dispatchEvent(new window.Event("pause"));
    button("Cài đặt").click();
  });
  const position = mount.querySelector("input[type=number]");
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set.call(position, "80");
    position.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
  await act(async () => {
    mount
      .querySelector("form")
      .dispatchEvent(
        new window.Event("submit", { bubbles: true, cancelable: true }),
      );
  });
  assert.equal(video.currentTime, 80);
  await act(async () => {
    button("Tua tiến 10 giây").click();
  });
  await act(async () => {
    button("Tua tiến 10 giây").click();
  });
  assert.equal(video.currentTime, 95);
  await act(async () => {
    video.dispatchEvent(new window.Event("error"));
  });
  assert(slider.disabled && mount.querySelector("[role=alert]"));
  await act(async () => {
    root.render(
      React.createElement(
        require(path.join(repo, "frontend/src/VideoPlayer.tsx")).default,
        {
          src: "/burned.mp4",
          subtitleSrc: "/example.vtt",
          subtitlesBurned: true,
        },
      ),
    );
  });
  assert(button("Phụ đề").disabled && !mount.querySelector("track"));
  await act(async () => {
    root.unmount();
  });
  window.happyDOM.abort();
  console.log(
    "PLAYER SEEK INTERACTIONS PASS (simulated media events, no playback assertion)",
  );
  process.exit(0);
}
await waitFor(() => mount.textContent.includes("Engine sẵn sàng"), 15000);
assert(button("Process") && !button("Process").disabled);
const source = process.env.LOCALIZER_TEST_URL;
assert(
  source,
  "Set LOCALIZER_TEST_URL to a rights-cleared spoken Chinese video URL",
);
const input = mount.querySelector("input[type=url]");
await act(async () => {
  Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  ).set.call(input, source);
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  input.dispatchEvent(new window.Event("change", { bubbles: true }));
});
// Select a deterministic timestamp and 16:9 pad to exercise form fields.
const labels = [...mount.querySelectorAll("label")];
const format = labels
  .find((label) => label.textContent.startsWith("Format"))
  .querySelector("select");
await act(async () => {
  format.value = "16:9";
  format.dispatchEvent(new window.Event("change", { bubbles: true }));
});
await act(async () => {
  mount
    .querySelector("form")
    .dispatchEvent(
      new window.Event("submit", { bubbles: true, cancelable: true }),
    );
});
await waitFor(() => mount.querySelector("tbody tr"));
const identifier = (
  await (await networkFetch("http://127.0.0.1:8000/api/jobs")).json()
)[0].id;
console.log("REACT_JOB_ID=" + identifier);
await waitFor(
  () =>
    mount.textContent.includes("Completed") &&
    mount.querySelectorAll(".downloads a").length === 4,
);
assert.equal(mount.querySelector("[role=alert]"), null);
assert.equal(mount.querySelector("progress").value, 100);
const outputs = [];
for (const link of mount.querySelectorAll(".downloads a")) {
  const name = link.getAttribute("download");
  const response = await networkFetch(
    new URL(link.getAttribute("href"), "http://127.0.0.1:8000"),
  );
  assert.equal(response.status, 200);
  assert((await response.arrayBuffer()).byteLength > 0);
  outputs.push(name);
}
assert.deepEqual(outputs.sort(), [
  "final.mp4",
  "metadata.json",
  "subtitle.srt",
  "thumbnail.jpg",
]);
writeFileSync(
  path.join(repo, "workspace/react-ui-verification.json"),
  JSON.stringify(
    {
      job_id: identifier,
      simulated_dom: true,
      output_links_downloaded: outputs,
      completed_progress: 100,
    },
    null,
    2,
  ),
);
writeFileSync(
  path.join(repo, "workspace/react-ui-completed.html"),
  mount.innerHTML,
);
await act(async () => {
  root.unmount();
});
window.happyDOM.abort();
console.log("REAL REACT/API/ENGINE INTERACTION PASS (simulated DOM)");
