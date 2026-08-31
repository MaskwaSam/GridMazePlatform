import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  applyHeadingOffset,
  advanceState,
  createRobotState,
  durationSteps,
  IDLE_ROTATION_DELAY_MS,
  isMazeRotationShortcut,
  isAtGoal,
  isStartPlacementAllowed,
  isPositionAllowed,
  isStoppedAtGoal,
  mazeFogDistances,
  rollingTransformForMovement,
  shouldAutoRotateView,
  simulateCommands,
  startTileForLevel,
  validatePlayableLevel,
  wallSegmentsForLevel,
} from "../js/level-logic.js";
import {
  LEVEL_CATALOG,
  chooseInitialLevelId,
  nextLevelId,
} from "../js/levels.js";
import {
  commitProjectImport,
  exportProject,
  hasLegacySavedState,
  loadLastLevelId,
  loadSavedState,
  MAX_ATTEMPT_NUMBER,
  MAX_ATTEMPTS_PER_LEVEL,
  normalizeAttemptHistory,
  prepareProjectImport,
  saveState,
} from "../js/storage.js";

const testsDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(testsDir, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const exists = (relative) => fs.existsSync(path.join(root, relative));
const results = [];

function test(name, callback) {
  try {
    callback();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, error });
  }
}

const requiredFiles = [
  "index.html", "styles.css", "manifest.webmanifest", "service-worker.js",
  "js/main.js", "js/blocks.js", "js/simulation.js", "js/level-logic.js",
  "js/python-runtime.js", "js/python-worker.js", "js/storage.js", "js/levels.js", "js/settings.js",
  "js/game-actions.js", "js/gamepad.js", "js/multiplayer-protocol.js", "js/multiplayer-session.js",
  "js/multiplayer-transport.js", "js/multiplayer-client.js",
  ...LEVEL_CATALOG.map((entry) => entry.file.replace(/^\.\//, "")),
  "assets/stl/maze_piece_straight_v1.stl",
  "assets/stl/maze_piece_corner_v1.stl",
  "assets/stl/maze_piece_end_v1.stl",
  "vendor/three/three.module.min.js", "vendor/three/three.core.min.js", "vendor/three/STLLoader.js", "vendor/three/OrbitControls.js",
  "vendor/blockly/blockly.min.js", "vendor/blockly/python_compressed.js",
  "vendor/pyodide/pyodide.js", "vendor/pyodide/pyodide.asm.js",
  "vendor/pyodide/pyodide.asm.wasm", "vendor/pyodide/python_stdlib.zip",
  "vendor/pyodide/pyodide-lock.json",
  "vendor/licenses/Three-MIT.txt", "vendor/licenses/Blockly-Apache-2.0.txt",
  "vendor/licenses/Pyodide-MPL-2.0.txt",
];

test("all runtime and license files are present", () => {
  assert.deepEqual(requiredFiles.filter((file) => !exists(file)), []);
  assert.ok(fs.statSync(path.join(root, "vendor/pyodide/pyodide.asm.wasm")).size > 8_000_000);
});

test("HTML exposes the complete accessible game workflow", () => {
  const html = read("index.html");
  const manifest = JSON.parse(read("manifest.webmanifest"));
  assert.match(html, /<title>Maskwa Maze Lab<\/title>/);
  assert.match(html, /<h1 aria-label="Maskwa Maze Lab">/);
  assert.match(html, /<h2 id="studio-heading" aria-label="Coding Workspace">/);
  assert.match(html, /class="brand-compact" aria-hidden="true">Maskwa Maze<\/span>/);
  assert.match(html, /class="studio-title-compact" aria-hidden="true">Code<\/span>/);
  assert.match(html, /Open Coding Workspace fullscreen/);
  assert.match(html, /accept="\.json,\.maskwamaze,\.mazebot,application\/json"/);
  assert.equal(manifest.name, "Maskwa Maze Lab");
  assert.equal(manifest.short_name, "Maskwa Maze");
  for (const id of [
    "maze-canvas", "maze-panel", "code-studio", "place-button", "idle-tour-button", "maze-fullscreen-button",
    "studio-fullscreen-button", "run-button", "stop-button", "reset-button",
    "blocks-tab", "python-tab", "blockly-editor", "python-editor", "run-state",
    "program-log", "success-banner", "level-select", "next-level-button",
    "save-work-button", "attempt-history-button", "export-work-button", "import-work-button",
    "import-work-file", "save-status", "attempt-history-dialog", "attempt-history-list",
    "settings-button", "settings-dialog", "settings-status", "settings-defaults-button",
    "setting-idle-tour", "setting-reduce-motion", "setting-clear-view", "setting-show-trail",
    "setting-show-impact-markers", "setting-show-grid", "setting-confirm-reset",
    "setting-controller-enabled", "controller-panel", "controller-status",
  ]) {
    assert.match(html, new RegExp(`id=["']${id}["']`), `missing #${id}`);
  }
  assert.match(html, /role="tablist"/);
  assert.match(html, /aria-live="assertive"/);
  assert.match(html, /Robot-relative direction key/);
  assert.match(html, /FORWARD · 0°/);
  assert.match(html, /Drop anywhere on the blue START piece/);
  assert.match(html, /N means North \(0°\)/);
  assert.match(html, /After a turn, forward follows its new facing/);
  assert.match(html, /70 mm sphere robot/);
  assert.match(html, /id="maze-canvas"[^>]+tabindex="0"/);
  assert.match(html, /id="maze-canvas"[^>]+aria-keyshortcuts="Control\+R"/);
  assert.match(html, /id="idle-tour-button"[^>]+aria-pressed="true"/);
  assert.match(html, /id="maze-fullscreen-button"[^>]+aria-controls="maze-panel"/);
  assert.match(html, /id="studio-fullscreen-button"[^>]+aria-controls="code-studio"/);
  assert.ok(
    html.indexOf('id="success-banner"') < html.indexOf('<section class="studio-card"'),
    "the solved banner must remain inside the fullscreen maze panel",
  );
  assert.match(html, /release point becomes its starting position/i);
  assert.match(html, /Every Run and manual Save records the exact code/);
  assert.match(html, /id="python-editor"[^>]+maxlength="20000"/);
  assert.doesNotMatch(html, /(?:src|href)=["']https?:\/\//i);
});

test("every authored runtime reference is local and exists", () => {
  const html = read("index.html");
  const refs = [...html.matchAll(/(?:src|href)=["']([^"']+)["']/g)].map((match) => match[1]);
  for (const reference of refs) {
    if (reference.startsWith("#")) continue;
    assert.ok(!/^https?:/i.test(reference), `remote reference: ${reference}`);
    const clean = reference.replace(/^\.\//, "").split(/[?#]/)[0];
    assert.ok(exists(clean), `missing local reference: ${reference}`);
  }
  for (const relative of ["index.html", "styles.css", "service-worker.js", ...requiredFiles.filter((file) => file.startsWith("js/"))]) {
    assert.doesNotMatch(read(relative), /https?:\/\//i, `remote URL in ${relative}`);
  }
});

test("phone portrait and short-landscape layouts keep controls touchable and the game visible", () => {
  const html = read("index.html");
  const css = read("styles.css");
  const main = read("js/main.js");
  const landscapeStart = css.indexOf("@media (max-width: 920px) and (orientation: landscape) and (max-height: 520px)");
  const compactLandscapeStart = css.indexOf("@media (max-width: 620px) and (orientation: landscape) and (max-height: 520px)");
  const landscapeCss = css.slice(landscapeStart, compactLandscapeStart);
  const compactLandscapeCss = css.slice(compactLandscapeStart, css.indexOf("@media (prefers-reduced-motion: reduce)"));
  assert.match(html, /id="idle-tour-button"[^>]+data-mobile-label="Tour on"/);
  assert.match(html, /id="place-button"[^>]+data-mobile-label="Center start"/);
  assert.match(html, /id="idle-tour-button"[^>]+aria-label="Turn idle tour off"/);
  assert.match(html, /id="place-button"[^>]+aria-label="Place robot at start center"/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /--app-header-height: 84px/);
  assert.match(css, /height: calc\(100dvh - var\(--app-header-height\) - env\(safe-area-inset-top\)\)/);
  assert.match(css, /@media \(max-width: 620px\)/);
  assert.match(css, /@media \(max-width: 920px\) and \(orientation: landscape\) and \(max-height: 520px\)/);
  assert.match(css, /grid-template-columns: minmax\(0, 0\.92fr\) minmax\(0, 1\.08fr\)/);
  assert.match(css, /grid-template-rows: minmax\(480px, 62dvh\) minmax\(610px, 84dvh\)/);
  assert.match(css, /@media \(max-width: 360px\) and \(orientation: portrait\)[\s\S]*?\.scene-heading \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(css, /\.work-button \{[^}]*min-height: 44px;/);
  assert.match(css, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(css, /\.blocklyTreeRow \{ height: 42px !important;/);
  assert.match(css, /\.dialog-close \{[^}]*min-width: 44px;[^}]*min-height: 44px;/);
  assert.match(landscapeCss, /#level-select \{[^}]*min-height: 44px;/);
  assert.match(landscapeCss, /\.fullscreen-button \{[^}]*min-height: 44px;/);
  assert.match(landscapeCss, /\.run-bar > \.button \{[^}]*min-height: 44px;/);
  assert.match(landscapeCss, /\.editor-tab \{[^}]*min-height: 44px;/);
  assert.match(landscapeCss, /\.work-button \{[^}]*min-height: 44px;/);
  assert.match(landscapeCss, /\.heading-key \{ display: none; \}/);
  assert.match(css, /max-width: calc\(100vw - env\(safe-area-inset-left\) - env\(safe-area-inset-right\) - 0\.75rem\)/);
  assert.match(css, /max-height: calc\(100dvh - env\(safe-area-inset-top\) - env\(safe-area-inset-bottom\) - 0\.75rem\)/);
  assert.match(css, /inset-block-start: env\(safe-area-inset-top\)/);
  assert.match(compactLandscapeCss, /\.run-bar > \.button \{[^}]*min-width: 44px;[^}]*font-size: 0\.72rem;/);
  assert.match(compactLandscapeCss, /\.scene-actions \.button:not\(\.fullscreen-button\) \{ min-width: 44px; \}/);
  assert.match(compactLandscapeCss, /\.attempt-readout \{ display: none; \}/);
  assert.doesNotMatch(compactLandscapeCss, /\.run-bar > \.button \{[^}]*font-size: 0;/);
  assert.match(css, /position: sticky;/);
  assert.doesNotMatch(css, /isolation:\s*isolate/);
  assert.match(main, /window\.addEventListener\("orientationchange", scheduleInteractiveResize/);
  assert.match(main, /window\.visualViewport\?\.addEventListener\("resize", scheduleInteractiveResize/);
  assert.match(main, /const stateLabel = paused \? "paused" : enabled \? "on" : "off"/);
  assert.match(main, /dataset\.mobileLabel = `Tour \$\{stateLabel\}`/);
  assert.match(css, /\.header-settings-button \{[\s\S]*?min-height: 44px;/);
  assert.match(css, /\.settings-footer-actions \.button \{ min-height: 44px;/);
});

test("device settings are persistent, accessible, and separate from student projects", () => {
  const html = read("index.html");
  const css = read("styles.css");
  const main = read("js/main.js");
  const simulation = read("js/simulation.js");
  const settings = read("js/settings.js");
  const storage = read("js/storage.js");
  const stateRecordSource = main.slice(main.indexOf("function currentStateRecord"), main.indexOf("function currentCode"));
  const settingsBehavior = spawnSync(process.execPath, [path.join(testsDir, "settings.mjs")], { encoding: "utf8" });

  assert.equal(settingsBehavior.status, 0, `${settingsBehavior.stdout}\n${settingsBehavior.stderr}`);
  assert.match(settingsBehavior.stdout, /PASS settings defaults, normalization, persistence, and storage failures/);
  assert.match(settings, /maskwa-maze-lab-settings-v1/);
  assert.match(settings, /schemaVersion: SETTINGS_SCHEMA_VERSION/);
  assert.doesNotMatch(storage, /maskwa-maze-lab-settings|settings\.js/);
  assert.doesNotMatch(stateRecordSource, /userSettings|confirmReset|clearView/);
  assert.match(html, /id="settings-button"[^>]+aria-haspopup="dialog"[^>]+aria-controls="settings-dialog"/);
  assert.match(html, /id="settings-dialog"[^>]+aria-labelledby="settings-title"[^>]+aria-describedby="settings-description"/);
  assert.equal((html.match(/class="settings-row"/g) || []).length, 8);
  assert.equal((html.match(/type="checkbox" role="switch"/g) || []).length, 8);
  assert.match(html, /never change your code, attempt history, imported files, or robot physics/i);
  for (const key of ["idleTour", "reduceMotion", "clearView", "showTrail", "showImpactMarkers", "showGrid", "confirmReset", "controllerEnabled"]) {
    assert.match(main, new RegExp(`${key}: \\"setting-`));
  }
  assert.match(main, /saveSettings\(userSettings\)/);
  assert.match(main, /function requestReset\(\)[\s\S]*userSettings\.confirmReset[\s\S]*window\.confirm/);
  assert.match(simulation, /applyVisualSettings\(settings = \{\}\)/);
  assert.match(simulation, /this\.scene\.fog = null/);
  assert.match(simulation, /this\.trail\.visible = this\.visualSettings\.showTrail/);
  assert.match(simulation, /this\.grid\.visible = this\.visualSettings\.showGrid/);
  assert.match(simulation, /this\.visualSettings\.showImpactMarkers && this\.hasImpactMarker/);
  assert.match(simulation, /rollSphere\(movementX, movementZ\) \{\s*if \(this\.isReducedMotionActive\(\)\) return;/);
  assert.match(css, /\.settings-row input\[role="switch"\]/);
  assert.match(css, /html\[data-reduce-motion="true"\]/);
});

test("opt-in Xbox controls share the on-screen action boundary without steering the robot", () => {
  const html = read("index.html");
  const main = read("js/main.js");
  const gamepad = read("js/gamepad.js");
  const actions = read("js/game-actions.js");
  const settings = read("js/settings.js");
  const gamepadBehavior = spawnSync(process.execPath, [path.join(testsDir, "gamepad.mjs")], { encoding: "utf8" });
  const actionBehavior = spawnSync(process.execPath, [path.join(testsDir, "game-actions.mjs")], { encoding: "utf8" });

  assert.equal(gamepadBehavior.status, 0, `${gamepadBehavior.stdout}\n${gamepadBehavior.stderr}`);
  assert.match(gamepadBehavior.stdout, /PASS gamepad adapter lifecycle, mappings, edge handling, gating, reconnect, and deadzone/);
  assert.equal(actionBehavior.status, 0, `${actionBehavior.stdout}\n${actionBehavior.stderr}`);
  assert.match(actionBehavior.stdout, /PASS game actions normalize, route, isolate UI-only actions, and surface failures/);
  assert.match(settings, /controllerEnabled: false/);
  assert.match(html, /id="setting-controller-enabled"[^>]+role="switch"[^>]+aria-controls="controller-panel"/);
  assert.match(html, /id="controller-panel"[^>]+hidden/);
  for (const label of ["Place robot / Run", "Stop", "Reset", "Blocks / Python", "Attempts", "Settings", "Previous maze", "Next maze"]) {
    assert.ok(html.includes(label), `missing controller mapping: ${label}`);
  }
  assert.match(html, /controller never drives or turns the sphere directly/i);
  assert.match(main, /createGamepadController\(\{/);
  assert.match(main, /onAction: handleGamepadAction/);
  assert.match(main, /shouldHandleInput: shouldHandleGamepadInput/);
  assert.match(main, /gamepadController\?\.setEnabled\(userSettings\.controllerEnabled\)/);
  assert.match(main, /actionRouter\.register\(GAME_ACTION_KINDS\.RUN/);
  assert.match(main, /dispatchGameAction\(GAME_ACTION_KINDS\.RUN/);
  const runAgainHandler = main.slice(
    main.indexOf("actionRouter.register(GAME_ACTION_KINDS.RUN_AGAIN"),
    main.indexOf("actionRouter.register(GAME_ACTION_KINDS.TOGGLE_EDITOR"),
  );
  assert.match(runAgainHandler, /const source = prepareProgramSource\(\);\s*if \(source === null\) return false;/);
  assert.ok(
    runAgainHandler.indexOf("prepareProgramSource()") < runAgainHandler.indexOf("resetAttempt()"),
    "Run again must preflight code before resetting a solved attempt",
  );
  const gamepadHandler = main.slice(main.indexOf("function handleGamepadAction"), main.indexOf("function shouldHandleGamepadInput"));
  assert.doesNotMatch(gamepadHandler, /simulation|executeRpc|roll\(|spin\(/);
  assert.doesNotMatch(gamepad, /simulation|executeRpc|localStorage|WebSocket/);
  assert.match(actions, /OPEN_SETTINGS: "open-settings"/);
});

test("multiplayer groundwork is strict, private, command-routed, and offline by default", () => {
  const main = read("js/main.js");
  const client = read("js/multiplayer-client.js");
  const transport = read("js/multiplayer-transport.js");
  const protocol = read("js/multiplayer-protocol.js");
  const serviceWorker = read("service-worker.js");
  const multiplayerDocs = read("MULTIPLAYER.md");
  const behavior = spawnSync(process.execPath, [path.join(testsDir, "multiplayer.mjs")], { encoding: "utf8" });

  assert.equal(behavior.status, 0, `${behavior.stdout}\n${behavior.stderr}`);
  assert.match(behavior.stdout, /PASS multiplayer protocol, offline\/loopback\/WebSocket transports, sequencing, privacy, and command authority/);
  assert.match(main, /createMultiplayerClient\(\{/);
  assert.match(main, /executeLocalCommand: \(method, args\) => simulation\.executeRpc\(method, args\)/);
  assert.match(main, /onRpc: \(method, args\) => multiplayerClient\.executeRobotCommand\(\{ method, args \}\)/);
  assert.match(main, /actionRouter\.subscribe\(\(action\) =>/);
  assert.match(main, /!isShareableGameAction\(action\)/);
  assert.doesNotMatch(main, /new WebSocket|wss?:\/\//);
  assert.match(client, /transport = new OfflineTransport\(\)/);
  assert.match(client, /Server command authority requires a validated server-authority room snapshot/);
  assert.match(client, /Private field cannot cross the multiplayer boundary/);
  assert.match(transport, /only connect\(endpoint\)[\s\S]*constructs a socket/i);
  assert.match(transport, /messages sent while not open[\s\S]*never queued or replayed/i);
  assert.match(protocol, /MAX_MULTIPLAYER_MESSAGE_BYTES = 65_536/);
  assert.match(protocol, /Multiplayer requires wss, except for localhost development/);
  for (const module of [
    "game-actions", "gamepad", "multiplayer-protocol", "multiplayer-session",
    "multiplayer-transport", "multiplayer-client",
  ]) assert.match(serviceWorker, new RegExp(`"\\./js/${module}\\.js"`), `${module} is not cached offline`);
  assert.match(multiplayerDocs, /does \*\*not\*\* expose `\/ws`/);
  assert.match(multiplayerDocs, /It must never carry:[\s\S]*Python source/);
  assert.match(multiplayerDocs, /server is authoritative for room membership, ordering, committed actions/);
});

test("all authored JavaScript parses in Node", () => {
  const scripts = ["service-worker.js", ...fs.readdirSync(path.join(root, "js")).filter((file) => file.endsWith(".js")).map((file) => `js/${file}`)];
  for (const script of scripts) {
    const result = spawnSync(process.execPath, ["--check", path.join(root, script)], { encoding: "utf8" });
    assert.equal(result.status, 0, `${script}: ${result.stderr}`);
  }
});

test("Blockly defines exactly the 13 intended sphere-robot command blocks", () => {
  const source = read("js/blocks.js");
  const listSource = source.slice(source.indexOf("export const SPHERO_BLOCK_TYPES"), source.indexOf("]);", source.indexOf("export const SPHERO_BLOCK_TYPES")) + 2);
  const types = [...listSource.matchAll(/["'](sphero_[a-z_]+)["']/g)].map((match) => match[1]);
  assert.equal(types.length, 13);
  assert.equal(new Set(types).size, 13);
  for (const type of types) assert.match(source, new RegExp(`PY\\.forBlock\\.${type}`));
  assert.match(source, /roll %1° from facing/);
  assert.doesNotMatch(source, /drive at a compass heading/);
});

test("Python runs in a terminating worker with only allowlisted robot RPC", () => {
  const worker = read("js/python-worker.js");
  const runtime = read("js/python-runtime.js");
  assert.match(worker, /const ALLOWED_RPC = new Set/);
  assert.match(worker, /__ast\.Import/);
  assert.match(worker, /__ast\.Attribute/);
  assert.match(worker, /__SAFE_BUILTINS/);
  assert.match(worker, /20,000 character limit/);
  assert.match(worker, /set_main_led\(\*colour\)/);
  assert.match(worker, /async def roll\(heading, speed, seconds\)/);
  assert.match(worker, /async def set_heading\(heading\)/);
  assert.match(read("js/simulation.js"), /setLed\(\.\.\.args\)/);
  assert.match(runtime, /new Worker/);
  assert.match(runtime, /PROGRAM_TIMEOUT_MS = 25_000/);
  assert.match(runtime, /this\.terminate\("Program stopped after the 25 second safety limit\."\)/);
  assert.match(runtime, /worker\.addEventListener\("error"[\s\S]*this\.terminate\(error\.message\)/);
  const behavior = spawnSync(process.execPath, [path.join(testsDir, "python-runtime.mjs")], { encoding: "utf8" });
  assert.equal(behavior.status, 0, `${behavior.stdout}\n${behavior.stderr}`);
  assert.match(behavior.stdout, /PASS Python runtime rejects boot, timeout, and worker crashes promptly/);
});

test("per-level saves preserve v2 work and isolate v3 programs without executing v1 controls", () => {
  const v1 = { schemaVersion: 1, levelId: "starter-l", pythonSource: "old absolute headings" };
  const v2 = { schemaVersion: 2, levelId: "starter-l", pythonSource: "relative starter program", blocks: { blocks: [] } };
  const storage = memoryStorage({
    "mazebot-lab-state-v1": JSON.stringify(v1),
    "mazebot-lab-state-v2": JSON.stringify(v2),
  });

  assert.equal(hasLegacySavedState(storage), true);
  assert.deepEqual(loadSavedState("starter-l", storage), v2);
  assert.equal(loadSavedState("mirror-left", storage), null);
  assert.equal(loadLastLevelId(storage), "starter-l");

  const chosenPose = { x: -35.5, z: 227.25, heading: 0 };
  assert.equal(saveState({
    levelId: "mirror-left",
    pythonSource: "left program",
    blocks: { blocks: [] },
    robotPlaced: true,
    robotStartPose: chosenPose,
  }, storage), true);
  assert.equal(loadSavedState("starter-l", storage).pythonSource, "relative starter program");
  assert.equal(loadSavedState("mirror-left", storage).pythonSource, "left program");
  assert.deepEqual(loadSavedState("mirror-left", storage).robotStartPose, chosenPose);
  assert.equal(loadLastLevelId(storage), "mirror-left");
  assert.deepEqual(JSON.parse(storage.getItem("mazebot-lab-state-v1")), v1, "v1 backup was changed");
  assert.deepEqual(JSON.parse(storage.getItem("mazebot-lab-state-v2")), v2, "v2 record was changed");
  assert.equal(JSON.parse(storage.getItem("mazebot-lab-state-v3")).schemaVersion, 3);
  assert.equal(hasLegacySavedState({ getItem() { throw new Error("storage blocked"); } }), false);
});

test("attempt history and portable projects are bounded, validated, and imported without losing local code", () => {
  const knownLevelIds = LEVEL_CATALOG.map((entry) => entry.id);
  const sourceStorage = memoryStorage();
  const startedAt = "2026-08-29T18:00:00.000Z";
  const attempt = {
    id: "attempt-straight-start-1",
    number: 1,
    kind: "run",
    startedAt,
    finishedAt: "2026-08-29T18:00:02.000Z",
    editorMode: "python",
    code: "await roll(0, 160, 1)\n",
    outcome: "goal-not-reached",
    message: "Program finished before stopping on GOAL.",
    impacts: 0,
    startPose: { x: 0, z: 250, heading: 0 },
    finalPose: { x: 0, z: 150, heading: 0 },
  };
  assert.equal(saveState({
    levelId: "straight-start",
    editorMode: "python",
    blocks: { blocks: [] },
    pythonSource: attempt.code,
    pythonDetached: true,
    robotPlaced: true,
    robotStartPose: attempt.startPose,
    attempts: [attempt],
    attemptCounter: 1,
  }, sourceStorage), true);

  const exported = exportProject(knownLevelIds, sourceStorage);
  const envelope = JSON.parse(exported);
  assert.equal(envelope.format, "maskwa-maze-lab-project");
  assert.equal(envelope.schemaVersion, 1);
  assert.equal(envelope.headingSemantics, "robot-relative-v1");
  assert.deepEqual(Object.keys(envelope.levels), ["straight-start"]);
  assert.equal(envelope.levels["straight-start"].attempts[0].code, attempt.code);

  const prepared = prepareProjectImport(exported, knownLevelIds);
  const legacyPrepared = prepareProjectImport(JSON.stringify({ ...envelope, format: "mazebot-lab-project" }), knownLevelIds);
  assert.equal(legacyPrepared.format, "maskwa-maze-lab-project", "legacy project format was not normalized");
  const v1 = { schemaVersion: 1, levelId: "starter-l", pythonSource: "legacy absolute" };
  const v2 = { schemaVersion: 2, levelId: "starter-l", pythonSource: "relative backup", blocks: { blocks: [] } };
  const targetStorage = memoryStorage({
    "mazebot-lab-state-v1": JSON.stringify(v1),
    "mazebot-lab-state-v2": JSON.stringify(v2),
  });
  assert.equal(saveState({
    levelId: "straight-start",
    editorMode: "blocks",
    blocks: { blocks: [] },
    pythonSource: "await roll(0, 80, 1)\n",
    pythonDetached: false,
    robotPlaced: false,
    robotStartPose: null,
    attempts: [],
    attemptCounter: 0,
  }, targetStorage), true);
  assert.equal(saveState({
    levelId: "mirror-left",
    editorMode: "python",
    blocks: { blocks: [] },
    pythonSource: "keep this omitted level\n",
    pythonDetached: true,
    robotPlaced: false,
    robotStartPose: null,
    attempts: [],
    attemptCounter: 0,
  }, targetStorage), true);

  const imported = commitProjectImport(prepared, knownLevelIds, targetStorage);
  assert.equal(imported.levelCount, 1);
  assert.equal(imported.preservedLocalVersions, 1);
  const restored = loadSavedState("straight-start", targetStorage);
  assert.equal(restored.pythonSource, attempt.code);
  assert.equal(restored.attempts.some((entry) => entry.outcome === "saved-before-import"), true);
  assert.equal(restored.attempts.some((entry) => entry.id === attempt.id), true);
  assert.equal(loadSavedState("mirror-left", targetStorage).pythonSource, "keep this omitted level\n");
  assert.deepEqual(JSON.parse(targetStorage.getItem("mazebot-lab-state-v1")), v1);
  assert.deepEqual(JSON.parse(targetStorage.getItem("mazebot-lab-state-v2")), v2);

  commitProjectImport(prepared, knownLevelIds, targetStorage);
  const repeated = loadSavedState("straight-start", targetStorage).attempts;
  assert.equal(new Set(repeated.map((entry) => entry.id)).size, repeated.length, "repeated import duplicated history");
  assert.ok(repeated.length <= MAX_ATTEMPTS_PER_LEVEL);

  const futureAttempts = Array.from({ length: MAX_ATTEMPTS_PER_LEVEL }, (_, index) => ({
    ...attempt,
    id: "attempt-future-" + index,
    number: index + 1,
    kind: "save",
    outcome: "saved",
    startedAt: new Date(Date.parse("2099-01-01T00:00:00.000Z") + index * 1000).toISOString(),
    finishedAt: new Date(Date.parse("2099-01-01T00:00:00.000Z") + index * 1000).toISOString(),
  }));
  const futureEnvelope = {
    ...envelope,
    levels: {
      "straight-start": {
        ...envelope.levels["straight-start"],
        attempts: futureAttempts,
        attemptCounter: MAX_ATTEMPTS_PER_LEVEL,
      },
    },
  };
  const futureStorage = memoryStorage();
  assert.equal(saveState({
    levelId: "straight-start",
    editorMode: "python",
    blocks: { blocks: [] },
    pythonSource: "local code must survive\n",
    pythonDetached: true,
    robotPlaced: false,
    robotStartPose: null,
    attempts: [],
    attemptCounter: 0,
  }, futureStorage), true);
  const futurePrepared = prepareProjectImport(JSON.stringify(futureEnvelope), knownLevelIds);
  const futureResult = commitProjectImport(futurePrepared, knownLevelIds, futureStorage);
  const futureHistory = loadSavedState("straight-start", futureStorage).attempts;
  assert.equal(futureResult.preservedLocalVersions, 1);
  assert.equal(futureHistory.length, MAX_ATTEMPTS_PER_LEVEL);
  assert.equal(futureHistory.some((entry) => entry.outcome === "saved-before-import" && entry.code === "local code must survive\n"), true);

  const manyAttempts = Array.from({ length: MAX_ATTEMPTS_PER_LEVEL + 5 }, (_, index) => ({
    ...attempt,
    id: "attempt-cap-" + index,
    number: index + 1,
    startedAt: new Date(Date.parse(startedAt) + index * 1000).toISOString(),
    outcome: index === MAX_ATTEMPTS_PER_LEVEL + 4 ? "running" : "saved",
    kind: index === MAX_ATTEMPTS_PER_LEVEL + 4 ? "run" : "save",
    finishedAt: index === MAX_ATTEMPTS_PER_LEVEL + 4 ? null : attempt.finishedAt,
  }));
  const normalized = normalizeAttemptHistory(manyAttempts);
  assert.equal(normalized.length, MAX_ATTEMPTS_PER_LEVEL);
  assert.equal(normalized.at(-1).outcome, "interrupted");

  const beforeInvalid = targetStorage.getItem("mazebot-lab-state-v3");
  const wrongHeadings = { ...envelope, headingSemantics: "absolute-v1" };
  assert.throws(
    () => prepareProjectImport(JSON.stringify(wrongHeadings), knownLevelIds),
    /incompatible absolute-heading/,
  );
  assert.throws(
    () => commitProjectImport(wrongHeadings, knownLevelIds, targetStorage),
    /prepared Maskwa Maze Lab project is invalid/,
  );
  const unknownLevel = {
    ...envelope,
    levels: { ...envelope.levels, "unknown-maze": envelope.levels["straight-start"] },
  };
  assert.throws(
    () => prepareProjectImport(JSON.stringify(unknownLevel), knownLevelIds),
    /unknown maze/,
  );

  const missingActiveLevel = { ...envelope, activeLevelId: "starter-l" };
  assert.throws(
    () => prepareProjectImport(JSON.stringify(missingActiveLevel), knownLevelIds),
    /active maze is missing/,
  );
  const inconsistentAttempt = {
    ...envelope,
    levels: {
      "straight-start": {
        ...envelope.levels["straight-start"],
        attempts: [{ ...attempt, kind: "save", outcome: "running", finishedAt: null }],
      },
    },
  };
  assert.throws(
    () => prepareProjectImport(JSON.stringify(inconsistentAttempt), knownLevelIds),
    /saved version has an invalid result/,
  );
  const invalidCounter = {
    ...envelope,
    levels: {
      "straight-start": {
        ...envelope.levels["straight-start"],
        attempts: [],
        attemptCounter: MAX_ATTEMPT_NUMBER + 1,
      },
    },
  };
  assert.throws(
    () => prepareProjectImport(JSON.stringify(invalidCounter), knownLevelIds),
    /attempt counter is invalid/,
  );
  const maxCounterProject = prepareProjectImport(JSON.stringify({
    ...envelope,
    levels: {
      "straight-start": {
        ...envelope.levels["straight-start"],
        attempts: [],
        attemptCounter: MAX_ATTEMPT_NUMBER,
      },
    },
  }), knownLevelIds);
  const maxCounterStorage = memoryStorage();
  assert.equal(saveState({
    levelId: "straight-start",
    editorMode: "python",
    blocks: { blocks: [] },
    pythonSource: "# local before max-counter import\n",
    pythonDetached: true,
    robotPlaced: false,
    robotStartPose: null,
    attempts: [],
    attemptCounter: 0,
  }, maxCounterStorage), true);
  commitProjectImport(maxCounterProject, knownLevelIds, maxCounterStorage);
  const maxCounterSaved = loadSavedState("straight-start", maxCounterStorage);
  assert.ok(maxCounterSaved.attemptCounter < MAX_ATTEMPT_NUMBER);
  assert.equal(maxCounterSaved.attempts.some((entry) => entry.outcome === "saved-before-import"), true);
  assert.equal(targetStorage.getItem("mazebot-lab-state-v3"), beforeInvalid, "invalid import mutated storage");
});

test("portable projects restore their active maze and can recover current work without storage", () => {
  const knownLevelIds = LEVEL_CATALOG.map((entry) => entry.id);
  const source = memoryStorage();
  for (const levelId of ["straight-start", "starter-l"]) {
    assert.equal(saveState({
      levelId,
      editorMode: "python",
      blocks: { blocks: [] },
      pythonSource: `# ${levelId}\n`,
      pythonDetached: true,
      robotPlaced: false,
      robotStartPose: null,
      attempts: [],
      attemptCounter: 0,
    }, source), true);
  }
  const prepared = prepareProjectImport(exportProject(knownLevelIds, source), knownLevelIds);
  assert.equal(prepared.activeLevelId, "starter-l");

  const target = memoryStorage();
  assert.equal(saveState({
    levelId: "straight-start",
    editorMode: "python",
    blocks: { blocks: [] },
    pythonSource: "# local\n",
    pythonDetached: true,
    robotPlaced: false,
    robotStartPose: null,
    attempts: [],
    attemptCounter: 0,
  }, target), true);
  commitProjectImport(prepared, knownLevelIds, target);
  assert.equal(loadLastLevelId(target), "starter-l");

  const unavailableStorage = { getItem() { throw new Error("storage unavailable"); } };
  const recovery = JSON.parse(exportProject(knownLevelIds, unavailableStorage, {
    levelId: "mirror-left",
    editorMode: "python",
    blocks: { blocks: [] },
    pythonSource: "# unsaved recovery\n",
    pythonDetached: true,
    robotPlaced: false,
    robotStartPose: null,
    attempts: [],
    attemptCounter: 0,
  }));
  assert.equal(recovery.activeLevelId, "mirror-left");
  assert.equal(recovery.levels["mirror-left"].pythonSource, "# unsaved recovery\n");
});

test("an oversized full project can still export the current maze as a recovery file", () => {
  const knownLevelIds = LEVEL_CATALOG.map((entry) => entry.id);
  const storage = memoryStorage();
  const largeCode = "r".repeat(19_500);
  const largeAttempts = Array.from({ length: MAX_ATTEMPTS_PER_LEVEL }, (_, index) => ({
    id: "recovery-capacity-" + index,
    number: index + 1,
    kind: "save",
    startedAt: new Date(Date.parse("2026-01-01T00:00:00.000Z") + index * 1000).toISOString(),
    finishedAt: new Date(Date.parse("2026-01-01T00:00:00.000Z") + index * 1000).toISOString(),
    editorMode: "python",
    code: largeCode,
    outcome: "saved",
    message: "Saved by student.",
    impacts: 0,
    startPose: null,
    finalPose: null,
  }));
  for (const levelId of knownLevelIds) {
    assert.equal(saveState({
      levelId,
      editorMode: "python",
      blocks: { blocks: [] },
      pythonSource: largeCode,
      pythonDetached: true,
      robotPlaced: false,
      robotStartPose: null,
      attempts: largeAttempts.map((entry) => ({ ...entry, id: entry.id + "-" + levelId })),
      attemptCounter: MAX_ATTEMPTS_PER_LEVEL,
    }, storage), true);
  }

  const snapshot = {
    ...loadSavedState("grand-tour", storage),
    levelId: "grand-tour",
    blocks: { padding: "b".repeat(249_000) },
  };
  assert.throws(
    () => exportProject(knownLevelIds, storage, snapshot),
    /too large to export/,
  );
  const recovery = JSON.parse(exportProject([snapshot.levelId], storage, snapshot));
  assert.deepEqual(Object.keys(recovery.levels), ["grand-tour"]);
  assert.equal(recovery.activeLevelId, "grand-tour");
  assert.equal(recovery.levels["grand-tour"].blocks.padding.length, 249_000);
});

test("autosave refuses quota failures and projects that cannot remain portable", () => {
  const blockedStorage = {
    getItem() { return null; },
    setItem() { throw new Error("quota exceeded"); },
  };
  assert.equal(saveState({
    levelId: "straight-start",
    blocks: { blocks: [] },
    pythonSource: "await wait(1)\n",
  }, blockedStorage), false);

  const storage = memoryStorage();
  const largeCode = "x".repeat(19_000);
  const largeAttempts = Array.from({ length: MAX_ATTEMPTS_PER_LEVEL }, (_, index) => ({
    id: "attempt-capacity-" + index,
    number: index + 1,
    kind: "save",
    startedAt: new Date(Date.parse("2026-01-01T00:00:00.000Z") + index * 1000).toISOString(),
    finishedAt: new Date(Date.parse("2026-01-01T00:00:00.000Z") + index * 1000).toISOString(),
    editorMode: "python",
    code: largeCode,
    outcome: "saved",
    message: "Saved by student.",
    impacts: 0,
    startPose: null,
    finalPose: null,
  }));
  let refused = false;
  for (const levelId of LEVEL_CATALOG.map((entry) => entry.id)) {
    const before = storage.getItem("mazebot-lab-state-v3");
    const saved = saveState({
      levelId,
      editorMode: "python",
      blocks: { padding: "b".repeat(200_000) },
      pythonSource: largeCode,
      pythonDetached: true,
      robotPlaced: false,
      robotStartPose: null,
      attempts: largeAttempts.map((entry) => ({ ...entry, id: entry.id + "-" + levelId })),
      attemptCounter: MAX_ATTEMPTS_PER_LEVEL,
    }, storage);
    if (!saved) {
      refused = true;
      assert.equal(storage.getItem("mazebot-lab-state-v3"), before, "a refused autosave changed stored work");
      break;
    }
  }
  assert.equal(refused, true, "oversized multi-level work was allowed to become unexportable");
});

test("the ordered catalogue, picker, next action, and offline cache cover every level", () => {
  assert.equal(LEVEL_CATALOG.length, 7);
  assert.equal(new Set(LEVEL_CATALOG.map((entry) => entry.id)).size, LEVEL_CATALOG.length);
  assert.deepEqual(LEVEL_CATALOG.map((entry) => entry.sequence), [1, 2, 3, 4, 5, 6, 7]);
  assert.ok(LEVEL_CATALOG.every((entry) => entry.difficulty === "Beginning"));
  assert.deepEqual(
    LEVEL_CATALOG.map((entry) => entry.name),
    ["Straight Start", "Starter L-Turn", "Mirror Left", "Double Turn", "U-Turn Trail", "Return Route", "Four-Turn Finish"],
  );
  assert.equal(chooseInitialLevelId("mirror-left", "starter-l"), "mirror-left");
  assert.equal(chooseInitialLevelId("missing", "starter-l"), "starter-l");
  assert.equal(chooseInitialLevelId("missing", "also-missing"), "straight-start");
  assert.equal(nextLevelId("straight-start"), "starter-l");
  assert.equal(nextLevelId("grand-tour"), null);

  const main = read("js/main.js");
  const serviceWorker = read("service-worker.js");
  assert.match(main, /switchLevel/);
  assert.doesNotMatch(main, /fetch\("\.\/levels\/starter-l\.json"/);
  assert.match(serviceWorker, /maskwa-maze-lab-v40/);
  assert.match(main, /register\("\.\/service-worker\.js\?v=40", \{ updateViaCache: "none" \}\)/);
  const html = read("index.html");
  assert.match(html, /register\("\.\/service-worker\.js\?v=40", \{ updateViaCache: "none" \}\)/);
  assert.match(html, /src="\.\/js\/main\.js\?v=38"/);
  assert.match(main, /from "\.\/simulation\.js\?v=36"/);
  assert.match(main, /from "\.\/blocks\.js\?v=36"/);
  assert.match(main, /from "\.\/settings\.js\?v=36"/);
  assert.match(main, /from "\.\/multiplayer-client\.js\?v=37"/);
  assert.match(serviceWorker, /"\.\/js\/settings\.js"/);
  assert.match(serviceWorker, /caches\.match\(request, \{ ignoreSearch: true \}\)/);
  assert.match(serviceWorker, /request\.mode === "navigate"/);
  assert.match(serviceWorker, /caches\.match\("\.\/index\.html", \{ ignoreSearch: true \}\)/);
  assert.match(serviceWorker, /cache\.put\(event\.request, copy\)\)\.catch\(\(\) => \{\}\)/);
  for (const entry of LEVEL_CATALOG) {
    const relative = entry.file.replace(/^\.\//, "");
    assert.ok(exists(relative), `${entry.id}: missing catalogue file`);
    assert.match(serviceWorker, new RegExp(escapeRegExp(entry.file)), `${entry.id}: not cached offline`);
    const authored = JSON.parse(read(relative));
    assert.equal(authored.id, entry.id);
    assert.equal(authored.name, entry.name);
    assert.equal(authored.difficulty, entry.difficulty);
    assert.equal(authored.sequence, entry.sequence);
  }
});

test("stale runs cannot overwrite current Run-again controls", () => {
  const main = read("js/main.js");
  assert.match(main, /let activeRunId = 0/);
  assert.match(main, /const runId = \+\+activeRunId/);
  assert.match(main, /if \(activeRunId !== runId\) return/);
  assert.match(main, /if \(activeRunId === runId\)/);
  assert.ok((main.match(/activeRunId \+= 1/g) || []).length >= 2, "Stop and Reset must invalidate old runs");
});

test("level replacement is transactional and releases prior WebGL resources", () => {
  const main = read("js/main.js");
  const simulation = read("js/simulation.js");
  assert.match(simulation, /Promise\.allSettled/);
  assert.ok(
    simulation.indexOf("validatePlayableLevel(level)") < simulation.indexOf("const loader = new STLLoader()"),
    "malformed levels must fail before any replacement assets are committed",
  );
  assert.match(simulation, /disposeObject3D\(nextMazeGroup\)/);
  assert.match(simulation, /disposeObject3D\(previousMazeGroup\)/);
  assert.ok(
    simulation.indexOf("const failedLoad") < simulation.indexOf("this.level = level"),
    "the active simulation level must not change before every STL is ready",
  );
  assert.match(main, /const previousLevel = level/);
  assert.match(main, /level = previousLevel/);
  assert.match(main, /Staying on \$\{level\.name\}/);
  assert.match(main, /simulation\.level\?\.id !== previousLevel\.id/);
  assert.match(main, /await simulation\.loadLevel\(previousLevel\)/);
  assert.match(main, /const previousState = cloneLevelStateRecord/);
  assert.match(main, /const previousSimulationSession = simulation\.captureSession\(\)/);
  assert.match(main, /statePersistenceSuspended = true/);
  assert.match(main, /statePersistenceSuspended = false;[\s\S]*if \(!persistState\(\)\)/);
  assert.match(main, /restoreProgramsFromState\(previousState\)/);
  assert.match(main, /simulation\.restoreSession\(previousSimulationSession\)/);
  assert.match(main, /if \(statePersistenceSuspended\) return;/);
  assert.match(main, /levelLoading = recoveryFailed/);
  assert.match(simulation, /captureSession\(\) \{/);
  assert.match(simulation, /restoreSession\(snapshot\) \{/);
  assert.match(simulation, /this\.emitCallback\("onLoaded"\)/);
  assert.match(simulation, /Maze simulation \$\{name\} callback failed/);
});

test("stopped-goal success terminates runaway Python and survives its rejection", () => {
  const main = read("js/main.js");
  const simulation = read("js/simulation.js");
  assert.match(main, /if \(programSucceeded\) return;/);
  assert.match(main, /runtime\?\.terminate\("Goal stop confirmed\."\)/);
  assert.match(main, /SUCCESS: The robot stopped on GOAL\./);
  assert.doesNotMatch(main, /SUCCESS: The robot reached GOAL\./);
  assert.match(simulation, /goalReached: isStoppedAtGoal\(this\.level, movedState\)/);
  assert.ok(
    main.indexOf("if (programSucceeded) return;") < main.indexOf("setStatus(\"Program needs debugging\""),
    "the error path must preserve a solved run",
  );
});

test("Save, Import, Export, and every terminal run path preserve a visible code history", () => {
  const main = read("js/main.js");
  const blocks = read("js/blocks.js");
  for (const outcome of ["goal-not-reached", "error", "stopped", "reset", "solved"]) {
    assert.match(main, new RegExp(`finalizeHistoryEntry\\([^\\n]+["']${outcome}["']`), `${outcome} is not finalized`);
  }
  assert.match(main, /recordHistoryEntry\("run", source\)/);
  assert.match(main, /recordHistoryEntry\("save", source\)/);
  assert.match(main, /attempts: attemptHistory/);
  assert.match(main, /attemptCounter/);
  assert.match(main, /attemptCounter >= MAX_ATTEMPT_NUMBER/);
  assert.match(main, /Not saved · shorten the program or export a recovery copy/);
  assert.match(main, /if \(persistCurrent && !persistState\(\)\)/);
  assert.match(main, /exportProject\(KNOWN_LEVEL_IDS, storage, snapshot\)/);
  assert.match(main, /exportProject\(\[snapshot\.levelId\], storage, snapshot\)/);
  assert.match(main, /Maskwa-Maze-Lab-Current-Maze-Recovery-/);
  assert.doesNotMatch(main, /if \(!persistState\(\)\) throw new Error\("Browser storage is unavailable\."\)/);
  assert.match(main, /prepareProjectImport/);
  assert.match(main, /validateBlocksState\(record\.blocks\)/);
  assert.match(main, /commitProjectImport/);
  assert.match(main, /switchLevel\(importedActiveLevelId, \{ persistCurrent: false \}\)/);
  assert.match(main, /Imported code was not run/);
  assert.match(main, /Maskwa-Maze-Lab-Work-/);
  assert.match(main, /\.maskwamaze\.json/);
  assert.match(main, /\(\?:json\|maskwamaze\|mazebot\)/);
  assert.match(main, /date\.getFullYear\(\)/);
  assert.match(blocks, /new Blockly\.Workspace\(\)/);
  const importSource = main.slice(main.indexOf("async function importStudentWork"), main.indexOf("function setSaveStatus"));
  assert.doesNotMatch(importSource, /runProgram\(/);
});

const authoredLevels = LEVEL_CATALOG.map((entry) => JSON.parse(read(entry.file.replace(/^\.\//, ""))));
const level = authoredLevels.find((candidate) => candidate.id === "starter-l");

test("students can choose an exact collision-safe start anywhere on the first printable piece", () => {
  const simulation = read("js/simulation.js");
  const main = read("js/main.js");
  assert.match(simulation, /createLabel\("START AREA · NORTH"/);
  for (const authored of authoredLevels) {
    const startTile = startTileForLevel(authored);
    assert.ok(startTile, `${authored.id}: missing starting piece`);
    assert.equal(authored.start.snapRadius, undefined, `${authored.id}: obsolete snap radius remains`);
    assert.equal(isStartPlacementAllowed(authored, authored.start.x, authored.start.z), true);

    const offCentre = { x: Number(startTile.x) + 25, z: Number(startTile.z), heading: authored.start.heading };
    assert.equal(isStartPlacementAllowed(authored, offCentre.x, offCentre.z), true, `${authored.id}: legal off-centre drop rejected`);
    const state = createRobotState(authored, offCentre);
    assert.equal(state.x, offCentre.x);
    assert.equal(state.z, offCentre.z);

    const adjacentTile = authored.tiles[1];
    assert.equal(isPositionAllowed(authored, adjacentTile.x, adjacentTile.z), true, `${authored.id}: adjacent route tile should be navigable`);
    assert.equal(isStartPlacementAllowed(authored, adjacentTile.x, adjacentTile.z), false, `${authored.id}: adjacent piece accepted as START`);

    const tooCloseToWallX = Number(startTile.x) + 70;
    assert.equal(isStartPlacementAllowed(authored, tooCloseToWallX, startTile.z), false, `${authored.id}: wall-overlapping drop accepted`);

    const reordered = { ...authored, tiles: [...authored.tiles.slice(1), authored.tiles[0]] };
    assert.equal(startTileForLevel(reordered).x, startTile.x, `${authored.id}: START depends on tile ordering`);
    assert.equal(startTileForLevel(reordered).z, startTile.z, `${authored.id}: START depends on tile ordering`);
    assert.equal(isStartPlacementAllowed(reordered, authored.start.x, authored.start.z), true, `${authored.id}: reordered START was rejected`);
    assert.equal(validatePlayableLevel(reordered), reordered);
  }

  const malformed = { ...authoredLevels[0], tray: { x: Number.NaN, z: 0 } };
  assert.throws(() => validatePlayableLevel(malformed), /robot tray is invalid/);

  assert.match(simulation, /isStartPlacementAllowed\(this\.level, dropPose\.x, dropPose\.z\)/);
  assert.match(simulation, /new THREE\.SphereGeometry\(ROBOT_MODEL_RADIUS, 36, 24\)/);
  assert.match(simulation, /this\.robot\.scale\.setScalar\(level\.robotRadius \/ ROBOT_MODEL_RADIUS\)/);
  assert.match(simulation, /this\.placeOnStart\(dropPose\)/);
  assert.match(simulation, /this\.startPose = \{/);
  assert.match(simulation, /this\.placeOnStart\(this\.startPose\)/);
  assert.match(simulation, /createRobotState\(this\.level, this\.startPose \|\| this\.level\.start\)/);
  assert.match(simulation, /this\.emitCallback\("onPlacement", true, \{ \.\.\.this\.startPose \}\)/);
  assert.match(simulation, /cancelDrag\(\) \{/);
  assert.match(simulation, /this\.controls\.enabled = true/);
  assert.doesNotMatch(simulation, /snapRadius/);
  assert.match(main, /robotStartPose/);
  assert.match(main, /simulation\.placeOnStart\(restorePose\)/);
  assert.match(main, /simulation\.cancelDrag\(\)/);
  assert.match(main, /typeof pose\?\.x !== "number" \|\| typeof pose\?\.z !== "number"/);
  assert.match(main, /robotStartPose,/);
  assert.doesNotMatch(main, /snapped to START/i);
});

test("the rolling band follows the shell while the facing arrow stays upright", () => {
  const simulation = read("js/simulation.js");
  assert.match(simulation, /new THREE\.TorusGeometry\(18\.15, 1\.05, 8, 16, ROLL_INDICATOR_ARC\)/);
  assert.match(simulation, /this\.robotSphere\.add\(equator, this\.rollIndicator\)/);
  assert.match(simulation, /this\.robot\.add\(this\.robotSphere, this\.headingMarker\)/);
  assert.match(simulation, /this\.robotSphere\.quaternion\.premultiply\(delta\)/);
  assert.match(simulation, /this\.rollSphere\(after\.movementX, after\.movementZ\)/);
  assert.doesNotMatch(simulation, /this\.robot\.add\(this\.robotSphere, equator/);
  assert.ok(
    (simulation.match(/this\.robotSphere\.quaternion\.identity\(\)/g) || []).length >= 3,
    "the visible rolling shell must reset on placement, tray return, and a new attempt",
  );
});

test("the camera starts a reduced-motion-safe idle tour after 20 seconds", () => {
  const simulation = read("js/simulation.js");
  assert.equal(IDLE_ROTATION_DELAY_MS, 20_000);
  assert.equal(shouldAutoRotateView(19_999, 0), false);
  assert.equal(shouldAutoRotateView(20_000, 0), true);
  assert.equal(shouldAutoRotateView(40_000, 0, { moving: true }), false);
  assert.equal(shouldAutoRotateView(40_000, 0, { dragging: true }), false);
  assert.equal(shouldAutoRotateView(40_000, 0, { reducedMotion: true }), false);
  assert.equal(shouldAutoRotateView(40_000, 0, { hidden: true }), false);
  assert.equal(shouldAutoRotateView(40_000, 0, { controlsDisabled: true }), false);
  assert.equal(shouldAutoRotateView(40_000, 0, { tourDisabled: true }), false);
  assert.match(simulation, /const IDLE_ROTATION_SPEED = 0\.5/);
  assert.match(simulation, /this\.controls\.autoRotateSpeed = IDLE_ROTATION_SPEED/);
  assert.match(simulation, /this\.controls\.update\(deltaSeconds\)/);
  assert.match(simulation, /\["pointerdown", "pointerup", "wheel", "keydown"\]/);
  assert.match(simulation, /event\.buttons \|\| event\.pressure > 0/);
  assert.match(simulation, /setIdleTourEnabled\(enabled\)/);
  assert.match(simulation, /data(?:set)?\.idleRotating|dataset\.idleRotating/);
  const main = read("js/main.js");
  assert.match(main, /idleTour: !userSettings\.idleTour/);
  assert.match(main, /applyUserSettings\(\{ persist: true \}\)/);
  assert.match(main, /setAttribute\("aria-pressed", String\(enabled\)\)/);
});

test("Ctrl+R starts rotation only from the focused maze view", () => {
  assert.equal(isMazeRotationShortcut({ key: "r", ctrlKey: true }), true);
  assert.equal(isMazeRotationShortcut({ key: "R", ctrlKey: true }), true);
  assert.equal(isMazeRotationShortcut({ key: "r", ctrlKey: false }), false);
  assert.equal(isMazeRotationShortcut({ key: "r", ctrlKey: true, shiftKey: true }), false);
  assert.equal(isMazeRotationShortcut({ key: "r", ctrlKey: true, altKey: true }), false);
  assert.equal(isMazeRotationShortcut({ key: "r", ctrlKey: true, metaKey: true }), false);

  const main = read("js/main.js");
  const simulation = read("js/simulation.js");
  const styles = read("styles.css");
  const handler = main.slice(
    main.indexOf("function handleMazeRotationShortcut"),
    main.indexOf("async function togglePanelFullscreen"),
  );
  assert.match(main, /elements\["maze-canvas"\]\.addEventListener\("keydown", handleMazeRotationShortcut\)/);
  assert.match(handler, /if \(!isMazeRotationShortcut\(event\)\) return/);
  assert.match(handler, /event\.preventDefault\(\)/);
  assert.match(handler, /simulation\.startIdleTour\(\)/);
  assert.ok(
    handler.indexOf("if (!isMazeRotationShortcut(event)) return") < handler.indexOf("event.preventDefault()"),
    "reload must only be suppressed after the exact focused-canvas shortcut matches",
  );
  assert.match(simulation, /this\.canvas\.focus\(\{ preventScroll: true \}\)/);
  assert.match(simulation, /startIdleTour\(time = performance\.now\(\)\)/);
  assert.match(simulation, /this\.idleTourEnabled = true/);
  assert.match(simulation, /this\.lastViewActivityTime = time - IDLE_ROTATION_DELAY_MS/);
  assert.match(styles, /#maze-canvas:focus \{ outline: none; \}/);
  assert.doesNotMatch(styles, /#maze-canvas:focus-visible/);
});

test("maze and Coding Workspace headers expose reversible fullscreen focus controls", () => {
  const main = read("js/main.js");
  const styles = read("styles.css");
  assert.match(main, /panel\.requestFullscreen\(\)/);
  assert.match(main, /document\.exitFullscreen\(\)/);
  assert.match(main, /document\.addEventListener\("fullscreenchange", updateFullscreenControls\)/);
  assert.match(main, /document\.fullscreenElement === panel/);
  assert.match(main, /simulation\?\.resize\(\)/);
  assert.match(main, /Blockly\.svgResize\(workspace\)/);
  assert.match(main, /setAttribute\("aria-pressed", String\(active\)\)/);
  assert.match(styles, /\.scene-card:fullscreen, \.studio-card:fullscreen/);
  assert.match(styles, /height: 100dvh/);
});

test("level-scaled fog begins beyond the complete maze footprint", () => {
  const small = mazeFogDistances(827.4, 331.1);
  const largeMaximumCameraDistance = 1508.6 * 1.25;
  const large = mazeFogDistances(largeMaximumCameraDistance, 603.4);
  assert.ok(small.near > 827.4 + 331.1);
  assert.ok(large.near > largeMaximumCameraDistance + 603.4);
  assert.ok(large.far >= large.near + 900);
  assert.ok(large.near > small.near);
  const simulation = read("js/simulation.js");
  assert.match(simulation, /mazeFogDistances\(view\.maxCameraDistance, view\.footprintRadius\)/);
  assert.match(simulation, /this\.camera\.far = Math\.max\(2600, fog\.far \+ 500\)/);
  assert.match(simulation, /this\.camera\.updateProjectionMatrix\(\)/);
});

test("physical movement maps to the correct visible rolling axis", () => {
  const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-12, `${actual} != ${expected}`);
  const directionCases = [
    { movement: [0, -10], axis: [-1, 0] },
    { movement: [10, 0], axis: [0, -1] },
    { movement: [0, 10], axis: [1, 0] },
    { movement: [-10, 0], axis: [0, 1] },
  ];
  for (const { movement, axis } of directionCases) {
    const roll = rollingTransformForMovement(movement[0], movement[1], 35);
    near(roll.axisX, axis[0]);
    near(roll.axisZ, axis[1]);
    near(roll.angle, 10 / 35);
  }
  const diagonal = rollingTransformForMovement(10, -10, 35);
  near(diagonal.axisX, -Math.SQRT1_2);
  near(diagonal.axisZ, -Math.SQRT1_2);
  near(diagonal.angle, Math.hypot(10, 10) / 35);
  assert.equal(rollingTransformForMovement(0, 0, 35), null);
  assert.equal(rollingTransformForMovement(10, 0, 0), null);
});

const PIECE_PROFILES = Object.freeze({
  straight: {
    openSides: ["east", "west"],
    closedSides: ["north", "south"],
    asset: "maze_piece_straight_v1.stl",
    sha256: "829be69bd204a1baaa08bc60fc4465f43336b0e0995d593d028500d87d2dc344",
  },
  corner: {
    openSides: ["north", "east"],
    closedSides: ["south", "west"],
    asset: "maze_piece_corner_v1.stl",
    sha256: "6030523d3d9a61f6822ee7738a10e165174d6a57adbcf91b861ea8a72a83f296",
  },
  end: {
    openSides: ["north"],
    closedSides: ["east", "south", "west"],
    asset: "maze_piece_end_v1.stl",
    sha256: "36eb808fcdabec30fa4e0f1a3dbf01f2f1fdcff700644e233ab4d48d2b573265",
  },
});
const SIDE_VECTORS = Object.freeze({
  north: { x: 0, z: -1, opposite: "south" },
  east: { x: 1, z: 0, opposite: "west" },
  south: { x: 0, z: 1, opposite: "north" },
  west: { x: -1, z: 0, opposite: "east" },
});
const SIDES = Object.freeze(Object.keys(SIDE_VECTORS));

test("starter level uses three project STL pieces with coherent geometry", () => {
  assert.equal(level.schemaVersion, 2);
  assert.equal(level.tiles.length, 4);
  assert.equal(new Set(level.tiles.map((tile) => tile.piece)).size, 3);
  assert.equal(level.start.heading, 0);
  assert.equal(level.navigationPolygon.length, 8);
  assert.ok(level.physics.driveAcceleration > 0);
  assert.ok(level.physics.wallRestitution > 0 && level.physics.wallRestitution < 1);
  assert.equal(wallSegmentsForLevel(level).length, 10);
  for (const [piece, file] of Object.entries(level.assets)) {
    const relative = file.replace(/^\.\//, "");
    const assetPath = path.join(root, relative);
    const info = readBinaryStl(assetPath);
    assert.ok(info.triangles > 3000);
    assert.equal(
      createHash("sha256").update(fs.readFileSync(assetPath)).digest("hex"),
      PIECE_PROFILES[piece].sha256,
      `${piece}: printable mesh fingerprint changed`,
    );
    assert.deepEqual(
      readTopWallSides(assetPath),
      [...PIECE_PROFILES[piece].closedSides].sort(),
      `${piece}: declared walls do not match the STL top-wall geometry`,
    );
    const roundedBounds = info.bounds.map((pair) => pair.map((bound) => {
      const rounded = Math.round(bound);
      return Object.is(rounded, -0) ? 0 : rounded;
    }));
    assert.deepEqual(roundedBounds, [[0, 200], [0, 200], [0, 82]]);
  }
});

test("every level's logical walls match printable openings, transforms, and corridor outline", () => {
  for (const authoredLevel of authoredLevels) {
    const tilesByPosition = new Map(authoredLevel.tiles.map((tile) => [`${tile.x},${tile.z}`, tile]));
    assert.equal(tilesByPosition.size, authoredLevel.tiles.length, `${authoredLevel.id}: repeated tile position`);
    for (const tile of authoredLevel.tiles) {
      const profile = PIECE_PROFILES[tile.piece];
      assert.ok(profile, `${authoredLevel.id}: unknown printable piece profile: ${tile.piece}`);
      assert.equal(path.basename(authoredLevel.assets[tile.piece]), profile.asset, `${authoredLevel.id}/${tile.piece}: asset/profile mismatch`);
      assert.deepEqual(authoredLevel.collisionProfiles[tile.piece].closedSides, profile.closedSides, `${authoredLevel.id}/${tile.piece}: collision walls changed`);
      assert.equal(authoredLevel.collisionProfiles[tile.piece].wallInset, 19.2, `${authoredLevel.id}/${tile.piece}: wall inset changed`);
      assert.equal(Math.abs(tile.x % authoredLevel.tileSize), 0, `${authoredLevel.id}: off-grid tile x`);
      assert.equal(Math.abs(tile.z % authoredLevel.tileSize), 0, `${authoredLevel.id}: off-grid tile z`);
      assert.ok([0, 90, 180, -90].includes(tile.yawDegrees), `${authoredLevel.id}: unsupported tile yaw`);
      const openings = transformedOpenings(tile, profile.openSides);
      for (const side of openings) {
        const direction = SIDE_VECTORS[side];
        const neighbour = tilesByPosition.get(`${tile.x + direction.x * authoredLevel.tileSize},${tile.z + direction.z * authoredLevel.tileSize}`);
        assert.ok(neighbour, `${authoredLevel.id}: ${tile.piece} at ${tile.x},${tile.z} has an unconnected ${side} opening`);
        const neighbourOpenings = transformedOpenings(neighbour, PIECE_PROFILES[neighbour.piece].openSides);
        assert.ok(neighbourOpenings.includes(direction.opposite), `${authoredLevel.id}: ${tile.piece} at ${tile.x},${tile.z} opens into a wall`);
      }
    }

    const xs = authoredLevel.navigationPolygon.map((point) => point.x);
    const zs = authoredLevel.navigationPolygon.map((point) => point.z);
    for (let x = Math.floor(Math.min(...xs) / 5) * 5; x <= Math.max(...xs); x += 5) {
      for (let z = Math.floor(Math.min(...zs) / 5) * 5; z <= Math.max(...zs); z += 5) {
        assert.equal(
          isPositionAllowed(authoredLevel, x, z, 0),
          printableCorridorContains(authoredLevel, x, z),
          `${authoredLevel.id}: logical/printable corridor mismatch near x=${x}, z=${z}`,
        );
      }
    }
  }
});

test("starter solution stops on the goal deterministically", () => {
  assert.equal(level.referenceSolution.at(-1).heading, 0, "the post-spin roll must use the sphere's new forward direction");
  const first = simulateCommands(level, level.referenceSolution);
  const second = simulateCommands(level, level.referenceSolution);
  assert.deepEqual(first, second);
  assert.equal(first.goalReached, true);
  assert.equal(isStoppedAtGoal(level, first), true);
  assert.equal(first.speed, 0);
  assert.equal(first.actualSpeed, 0);
  assert.equal(first.velocityX, 0);
  assert.equal(first.velocityZ, 0);
  assert.equal(first.collided, false);
  assert.equal(first.collisions, 0);
});

test("crossing the goal while moving does not solve the maze", () => {
  const stopLevel = {
    robotRadius: 5,
    start: { x: 0, z: 100, heading: 0 },
    goal: { x: 0, z: 0, radius: 12 },
    navigationPolygon: [
      { x: -200, z: -200 },
      { x: 200, z: -200 },
      { x: 200, z: 200 },
      { x: -200, z: 200 },
    ],
  };
  const movingAtGoal = {
    ...createRobotState(stopLevel, { x: 0, z: 0, heading: 0 }),
    speed: 160,
    actualSpeed: 160,
    velocityX: 0,
    velocityZ: -100,
  };
  assert.equal(isAtGoal(stopLevel, movingAtGoal.x, movingAtGoal.z), true);
  assert.equal(isStoppedAtGoal(stopLevel, movingAtGoal), false);
  assert.equal(advanceState(stopLevel, movingAtGoal).goalReached, false);

  let crossing = { ...createRobotState(stopLevel), speed: 160 };
  let enteredWhileMoving = false;
  for (let step = 0; step < durationSteps(2); step += 1) {
    crossing = advanceState(stopLevel, crossing);
    if (isAtGoal(stopLevel, crossing.x, crossing.z)) {
      enteredWhileMoving = true;
      assert.equal(crossing.goalReached, false);
    }
  }
  assert.equal(enteredWhileMoving, true, "the moving sphere never crossed the goal test zone");

  const overshot = simulateCommands(stopLevel, [
    { command: "roll", heading: 0, speed: 160, seconds: 2 },
  ]);
  assert.equal(overshot.goalReached, false);
  assert.equal(isAtGoal(stopLevel, overshot.x, overshot.z), false);

  const parked = simulateCommands(stopLevel, [
    { command: "roll", heading: 0, speed: 160, seconds: 1 },
  ]);
  assert.equal(parked.goalReached, true);
  assert.equal(isStoppedAtGoal(stopLevel, parked), true);
  assert.equal(parked.actualSpeed, 0);
  assert.equal(parked.velocityX, 0);
  assert.equal(parked.velocityZ, 0);
});

test("spin makes the sphere's new facing the reference for roll zero", () => {
  assert.equal(applyHeadingOffset(0, -90), 270);
  assert.equal(applyHeadingOffset(350, 20), 10);
  const openLevel = {
    robotRadius: 5,
    start: { x: 0, z: 100, heading: 0 },
    goal: { x: 400, z: 400, radius: 2 },
    navigationPolygon: [
      { x: -500, z: -500 },
      { x: 500, z: -500 },
      { x: 500, z: 500 },
      { x: -500, z: 500 },
    ],
  };
  const result = simulateCommands(openLevel, [
    { command: "roll", heading: 0, speed: 160, seconds: 1 },
    { command: "spin", degrees: 90, seconds: 0.5 },
    { command: "roll", heading: 0, speed: 160, seconds: 1 },
  ]);
  assert.equal(result.heading, 90);
  assert.ok(result.x > 80, "roll zero after a right spin should travel east");
  assert.ok(result.z < 20, "the first roll should still travel north");
  assert.equal(result.collisions, 0);
  assert.equal(isPositionAllowed(openLevel, result.x, result.z), true);

  const instantTurn = simulateCommands(openLevel, [
    { command: "setHeading", heading: 90 },
    { command: "roll", heading: 0, speed: 160, seconds: 1 },
  ]);
  assert.equal(instantTurn.heading, 90);
  assert.ok(instantTurn.x > 80, "an instant relative turn should establish the next forward direction");

  const accumulatedTurn = simulateCommands({
    ...openLevel,
    start: { ...openLevel.start, heading: 90 },
  }, [
    { command: "roll", heading: 90, speed: 160, seconds: 1 },
  ]);
  assert.equal(accumulatedTurn.heading, 180);
  assert.ok(accumulatedTurn.z > 180, "roll 90 from an east-facing sphere should turn south, not overwrite to east");

  const browserSimulation = read("js/simulation.js");
  assert.ok(
    (browserSimulation.match(/applyHeadingOffset\(this\.state\.heading, numeric\(0\)\)/g) || []).length >= 2,
    "browser roll and set_heading must both use the persistent sphere reference",
  );
});

test("an incorrect program bounces and remains inside the maze", () => {
  const result = simulateCommands(level, [{ command: "roll", heading: 180, speed: 200, seconds: 3 }]);
  assert.equal(result.goalReached, false);
  assert.equal(result.collided, true);
  assert.ok(result.collisions >= 1);
  assert.equal(isPositionAllowed(level, result.x, result.z), true);
});

test("head-on impacts reverse wall-normal velocity without stopping the command", () => {
  let state = { ...createRobotState(level), heading: 180, speed: 200 };
  for (let step = 0; step < 120 && !state.collision; step += 1) state = advanceState(level, state);
  assert.equal(state.collision, true);
  assert.ok(state.collisionNormalZ < -0.99);
  assert.ok(state.velocityZ < 0, "southward motion should rebound north");
  assert.equal(state.speed, 200, "the student's drive command should remain active after impact");
  assert.equal(isPositionAllowed(level, state.x, state.z), true);
});

test("oblique impacts retain damped tangent motion", () => {
  let state = {
    ...createRobotState(level, { x: 40, z: 0, heading: 135 }),
    speed: 200,
  };
  for (let step = 0; step < 120 && !state.collision; step += 1) state = advanceState(level, state);
  assert.equal(state.collision, true);
  assert.ok(state.collisionNormalX < -0.99);
  assert.ok(state.velocityX < 0, "wall-normal velocity should rebound west");
  assert.ok(state.velocityZ > 0, "southward tangent velocity should continue");
  assert.equal(isPositionAllowed(level, state.x, state.z), true);
});

test("45-degree wall normals produce a legal angled rebound", () => {
  const angledLevel = {
    robotRadius: 10,
    start: { x: 0, z: 0, heading: 45 },
    goal: { x: 0, z: 80, radius: 4 },
    navigationPolygon: [
      { x: -100, z: 0 },
      { x: 0, z: -100 },
      { x: 100, z: 0 },
      { x: 0, z: 100 },
    ],
  };
  let state = { ...createRobotState(angledLevel), speed: 255 };
  for (let step = 0; step < 180 && !state.collision; step += 1) state = advanceState(angledLevel, state);
  assert.equal(state.collision, true);
  assert.ok(Math.abs(state.collisionNormalX) > 0.65 && Math.abs(state.collisionNormalZ) > 0.65);
  assert.ok(state.velocityX * state.collisionNormalX + state.velocityZ * state.collisionNormalZ > 0);
  assert.equal(isPositionAllowed(angledLevel, state.x, state.z), true);
});

test("explicit printable wall segments block sustained drive inside a permissive arena", () => {
  const internalWallLevel = {
    robotRadius: 10,
    start: { x: -60, z: 0, heading: 90 },
    goal: { x: 70, z: 70, radius: 4 },
    navigationPolygon: [
      { x: -100, z: -100 },
      { x: 100, z: -100 },
      { x: 100, z: 100 },
      { x: -100, z: 100 },
    ],
    wallSegments: [{ id: "visible-centre-wall", x1: 0, z1: -100, x2: 0, z2: 100 }],
  };
  let state = { ...createRobotState(internalWallLevel), speed: 255 };
  for (let step = 0; step < 600; step += 1) {
    state = advanceState(internalWallLevel, state);
    assert.equal(isPositionAllowed(internalWallLevel, state.x, state.z), true);
    assert.ok(state.x <= -internalWallLevel.robotRadius + 0.01, `crossed internal wall at step ${step}`);
  }
  assert.ok(state.collisions >= 1);
});

test("roll, set-speed, wait, and stop use robot-like timing", () => {
  const rolled = simulateCommands(level, [
    { command: "roll", heading: 0, speed: 160, seconds: 1 },
  ]);
  assert.equal(rolled.speed, 0);
  assert.equal(rolled.actualSpeed, 0);
  assert.ok(rolled.z < level.start.z - 80 && rolled.z > level.start.z - 120);

  const continued = simulateCommands(level, [
    { command: "setHeading", heading: 0 },
    { command: "setSpeed", speed: 100 },
    { command: "wait", seconds: 1 },
  ]);
  assert.equal(continued.speed, 100);
  assert.ok(continued.actualSpeed > 90);
  const stopped = simulateCommands(level, [
    { command: "setHeading", heading: 0 },
    { command: "setSpeed", speed: 100 },
    { command: "wait", seconds: 1 },
    { command: "stop" },
  ]);
  assert.equal(stopped.speed, 0);
  assert.equal(stopped.actualSpeed, 0);
});

test("every authored maze has a legal deterministic reference solution", () => {
  const levelFiles = fs.readdirSync(path.join(root, "levels")).filter((file) => file.endsWith(".json")).sort();
  const catalogFiles = LEVEL_CATALOG.map((entry) => path.basename(entry.file)).sort();
  assert.deepEqual(levelFiles, catalogFiles, "level catalogue and JSON directory differ");
  const ids = new Set();
  const allowedCommands = new Set(["roll", "spin", "wait", "setHeading", "setSpeed", "stop"]);
  for (const authoredLevel of authoredLevels) {
    const file = `${authoredLevel.id}.json`;
    assert.equal(authoredLevel.schemaVersion, 2, `${file}: unsupported schema`);
    assert.equal(ids.has(authoredLevel.id), false, `${file}: duplicate id`);
    ids.add(authoredLevel.id);
    assert.equal(authoredLevel.start.heading, 0, `${file}: classroom start must face north`);
    assert.equal(authoredLevel.tileSize, 200, `${file}: printable grid size changed`);
    assert.equal(authoredLevel.baseTop, 10, `${file}: printable base height changed`);
    assert.equal(authoredLevel.robotDiameter, 70, `${file}: sphere diameter must match the 70 mm classroom robot`);
    assert.equal(authoredLevel.robotRadius, 35, `${file}: rendered and collision sphere sizes differ`);
    assert.equal(authoredLevel.robotDiameter / authoredLevel.tileSize, 0.35, `${file}: sphere-to-plate scale changed`);
    assert.ok(authoredLevel.tiles.length >= 3 && authoredLevel.tiles.length <= 10, `${file}: unsupported classroom footprint`);
    assert.ok(Array.isArray(authoredLevel.navigationPolygon) && authoredLevel.navigationPolygon.length >= 3, `${file}: missing wall polygon`);
    assert.ok(wallSegmentsForLevel(authoredLevel).length > 0, `${file}: missing printable wall colliders`);
    assert.equal(isPositionAllowed(authoredLevel, authoredLevel.start.x, authoredLevel.start.z), true, `${file}: illegal start`);
    assert.equal(isPositionAllowed(authoredLevel, authoredLevel.goal.x, authoredLevel.goal.z), true, `${file}: illegal goal`);
    assert.ok(Array.isArray(authoredLevel.referenceSolution) && authoredLevel.referenceSolution.length > 0, `${file}: missing reference commands`);
    for (const command of authoredLevel.referenceSolution) {
      assert.ok(allowedCommands.has(command.command), `${file}: unknown reference command ${command.command}`);
    }
    const nominalSeconds = authoredLevel.referenceSolution.reduce((total, command) => total + Number(command.seconds || 0), 0);
    assert.ok(nominalSeconds < 23, `${file}: reference route is too close to the 25 second browser limit`);
    const first = simulateCommands(authoredLevel, authoredLevel.referenceSolution);
    const second = simulateCommands(authoredLevel, authoredLevel.referenceSolution);
    assert.deepEqual(first, second, `${file}: nondeterministic result`);
    assert.equal(first.goalReached, true, `${file}: reference commands do not solve the maze`);
    assert.equal(isStoppedAtGoal(authoredLevel, first), true, `${file}: reference commands do not stop on the goal`);
    assert.equal(first.speed, 0, `${file}: reference commands leave drive enabled`);
    assert.equal(first.actualSpeed, 0, `${file}: reference commands leave the sphere moving`);
    assert.equal(first.velocityX, 0, `${file}: reference commands leave x velocity`);
    assert.equal(first.velocityZ, 0, `${file}: reference commands leave z velocity`);
    assert.equal(first.collisions, 0, `${file}: reference commands hit a wall`);
    assert.equal(isPositionAllowed(authoredLevel, first.x, first.z), true, `${file}: solution left the maze`);
  }
});

test("generated level JSON is current with the reusable grid-path definitions", () => {
  const repositoryRoot = path.resolve(root, "..");
  const generator = path.join(repositoryRoot, "scripts", "generate_game_levels.mjs");
  assert.ok(fs.existsSync(generator));
  const result = spawnSync(process.execPath, [generator], { cwd: repositoryRoot, encoding: "utf8" });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stdout, /7 level definitions validated/);
});

for (const result of results) {
  if (result.ok) console.log(`PASS ${result.name}`);
  else console.error(`FAIL ${result.name}\n${result.error?.stack || result.error}`);
}
const failures = results.filter((result) => !result.ok);
console.log(`\n${results.length - failures.length}/${results.length} checks passed`);
if (failures.length) process.exitCode = 1;

function transformedOpenings(tile, openSides) {
  const radians = Number(tile.yawDegrees || 0) * Math.PI / 180;
  const cosine = Math.cos(radians);
  const sine = Math.sin(radians);
  return openSides.map((side) => {
    const vector = SIDE_VECTORS[side];
    const worldX = Math.round(cosine * vector.x + sine * vector.z);
    const worldZ = Math.round(-sine * vector.x + cosine * vector.z);
    return SIDES.find((candidate) => (
      SIDE_VECTORS[candidate].x === worldX && SIDE_VECTORS[candidate].z === worldZ
    ));
  });
}

function printableCorridorContains(authoredLevel, x, z) {
  const halfTile = authoredLevel.tileSize / 2;
  const wallInnerFace = halfTile - 19.2;
  const epsilon = 1e-6;
  return authoredLevel.tiles.some((tile) => {
    const profile = PIECE_PROFILES[tile.piece];
    if (!profile) return false;
    const radians = Number(tile.yawDegrees || 0) * Math.PI / 180;
    const cosine = Math.cos(radians);
    const sine = Math.sin(radians);
    const worldX = x - tile.x;
    const worldZ = z - tile.z;
    const localX = cosine * worldX - sine * worldZ;
    const localZ = sine * worldX + cosine * worldZ;
    if (Math.abs(localX) > halfTile + epsilon || Math.abs(localZ) > halfTile + epsilon) return false;

    const closedSides = SIDES.filter((side) => !profile.openSides.includes(side));
    if (closedSides.includes("north") && localZ < -wallInnerFace - epsilon) return false;
    if (closedSides.includes("east") && localX > wallInnerFace + epsilon) return false;
    if (closedSides.includes("south") && localZ > wallInnerFace + epsilon) return false;
    if (closedSides.includes("west") && localX < -wallInnerFace - epsilon) return false;
    return true;
  });
}

function readTopWallSides(file) {
  const buffer = fs.readFileSync(file);
  const triangles = buffer.readUInt32LE(80);
  const areas = { east: 0, north: 0, south: 0, west: 0 };
  for (let triangle = 0; triangle < triangles; triangle += 1) {
    const start = 84 + triangle * 50 + 12;
    const points = [0, 1, 2].map((vertex) => [
      buffer.readFloatLE(start + vertex * 12),
      buffer.readFloatLE(start + vertex * 12 + 4),
      buffer.readFloatLE(start + vertex * 12 + 8),
    ]);
    if (Math.min(...points.map((point) => point[2])) < 81.5) continue;
    const area = Math.abs(
      (points[1][0] - points[0][0]) * (points[2][1] - points[0][1]) -
      (points[1][1] - points[0][1]) * (points[2][0] - points[0][0]),
    ) / 2;
    if (area < 1e-4) continue;
    const x = (points[0][0] + points[1][0] + points[2][0]) / 3;
    const y = (points[0][1] + points[1][1] + points[2][1]) / 3;
    const distances = { east: 200 - x, north: 200 - y, south: y, west: x };
    const side = Object.keys(distances).sort((first, second) => distances[first] - distances[second])[0];
    areas[side] += area;
  }
  return Object.keys(areas).filter((side) => areas[side] > 100).sort();
}

function readBinaryStl(file) {
  const buffer = fs.readFileSync(file);
  assert.ok(buffer.length >= 84, `${file} is too short`);
  const triangles = buffer.readUInt32LE(80);
  assert.equal(buffer.length, 84 + triangles * 50, `${file} has an invalid binary STL length`);
  const mins = [Infinity, Infinity, Infinity];
  const maxs = [-Infinity, -Infinity, -Infinity];
  for (let triangle = 0; triangle < triangles; triangle += 1) {
    const start = 84 + triangle * 50 + 12;
    for (let vertex = 0; vertex < 3; vertex += 1) {
      for (let axis = 0; axis < 3; axis += 1) {
        const value = buffer.readFloatLE(start + vertex * 12 + axis * 4);
        mins[axis] = Math.min(mins[axis], value);
        maxs[axis] = Math.max(maxs[axis], value);
      }
    }
  }
  return { triangles, bounds: mins.map((min, axis) => [min, maxs[axis]]) };
}

function memoryStorage(seed = {}) {
  const values = new Map(Object.entries(seed));
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); },
  };
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
