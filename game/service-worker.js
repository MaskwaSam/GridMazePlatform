"use strict";

const CACHE_NAME = "maskwa-maze-lab-v32";
const APP_FILES = [
  "./",
  "./index.html",
  "./icon.svg",
  "./styles.css",
  "./manifest.webmanifest",
  "./js/main.js",
  "./js/blocks.js",
  "./js/simulation.js",
  "./js/level-logic.js",
  "./js/python-runtime.js",
  "./js/python-worker.js",
  "./js/storage.js",
  "./js/levels.js",
  "./levels/straight-start.json",
  "./levels/starter-l.json",
  "./levels/mirror-left.json",
  "./levels/zigzag-run.json",
  "./levels/u-turn-trail.json",
  "./levels/switchback.json",
  "./levels/grand-tour.json",
  "./assets/stl/maze_piece_straight_v1.stl",
  "./assets/stl/maze_piece_corner_v1.stl",
  "./assets/stl/maze_piece_end_v1.stl",
  "./vendor/three/three.module.min.js",
  "./vendor/three/three.core.min.js",
  "./vendor/three/STLLoader.js",
  "./vendor/three/OrbitControls.js",
  "./vendor/blockly/blockly.min.js",
  "./vendor/blockly/python_compressed.js",
  "./vendor/blockly/media/sprites.svg",
  "./vendor/blockly/media/dropdown-arrow.svg",
  "./vendor/blockly/media/delete-icon.svg",
  "./vendor/blockly/media/resize-handle.svg",
  "./vendor/blockly/media/foldout-icon.svg",
  "./vendor/blockly/media/1x1.gif",
  "./vendor/blockly/media/pilcrow.png",
  "./vendor/blockly/media/quote0.png",
  "./vendor/blockly/media/quote1.png",
  "./vendor/blockly/media/click.mp3",
  "./vendor/blockly/media/delete.mp3",
  "./vendor/blockly/media/disconnect.mp3",
  "./vendor/blockly/media/drop.mp3",
  "./vendor/blockly/media/handopen.cur",
  "./vendor/blockly/media/handclosed.cur",
  "./vendor/blockly/media/handdelete.cur",
  "./vendor/pyodide/pyodide.js",
  "./vendor/pyodide/pyodide.asm.js",
  "./vendor/pyodide/pyodide.asm.wasm",
  "./vendor/pyodide/python_stdlib.zip",
  "./vendor/pyodide/pyodide-lock.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

async function cachedFallback(request) {
  const exact = await caches.match(request);
  if (exact) return exact;
  const versionAgnostic = await caches.match(request, { ignoreSearch: true });
  if (versionAgnostic) return versionAgnostic;
  if (request.mode === "navigate") {
    const appShell = await caches.match("./index.html", { ignoreSearch: true });
    if (appShell) return appShell;
  }
  return Response.error();
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || new URL(event.request.url).origin !== self.location.origin) return;
  event.respondWith(
    fetch(event.request).then((response) => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }).catch(() => cachedFallback(event.request)),
  );
});
