import {
  Blockly,
  createStarterProgram,
  createWorkspace,
  generatePython,
  isUiEvent,
  loadBlocks,
  saveBlocks,
  validateBlocksState,
} from "./blocks.js?v=36";
import { isMazeRotationShortcut } from "./level-logic.js?v=36";
import { MazeSimulation } from "./simulation.js?v=36";
import { PythonRuntime } from "./python-runtime.js?v=36";
import {
  GAME_ACTION_KINDS,
  GameActionRouter,
  isShareableGameAction,
} from "./game-actions.js?v=36";
import {
  GAMEPAD_ACTIONS,
  GAMEPAD_STATUS,
  createGamepadController,
} from "./gamepad.js?v=36";
import { createMultiplayerClient } from "./multiplayer-client.js?v=37";
import {
  DEFAULT_SETTINGS,
  loadSettings,
  normalizeSettings,
  saveSettings,
} from "./settings.js?v=36";
import {
  LEVEL_CATALOG,
  chooseInitialLevelId,
  levelEntry,
  nextLevelId,
} from "./levels.js?v=36";
import {
  commitProjectImport,
  exportProject,
  hasLegacySavedState,
  loadLastLevelId,
  loadSavedState,
  MAX_ATTEMPT_NUMBER,
  MAX_ATTEMPTS_PER_LEVEL,
  MAX_CODE_CHARACTERS,
  MAX_PROJECT_BYTES,
  normalizeAttemptHistory,
  prepareProjectImport,
  saveState,
} from "./storage.js?v=36";

const elements = Object.fromEntries([
  "level-name", "level-description", "maze-panel", "maze-canvas", "code-studio", "place-button", "idle-tour-button", "maze-fullscreen-button",
  "studio-fullscreen-button", "run-button", "stop-button", "reset-button",
  "run-state", "telemetry", "scene-help", "scene-loading", "blocks-tab", "python-tab",
  "blocks-panel", "python-panel", "python-editor", "python-mode-label", "regenerate-python",
  "program-log", "clear-log", "success-banner", "run-again-button", "next-level-button",
  "level-select", "level-number", "level-difficulty", "success-level-name",
  "save-work-button", "attempt-history-button", "attempt-count", "export-work-button",
  "import-work-button", "import-work-file", "save-status", "attempt-history-dialog",
  "attempt-history-title", "attempt-history-summary", "attempt-history-list",
  "settings-button", "settings-dialog", "settings-status", "settings-defaults-button",
  "setting-idle-tour", "setting-reduce-motion", "setting-clear-view", "setting-show-trail",
  "setting-show-impact-markers", "setting-show-grid", "setting-confirm-reset", "setting-controller-enabled",
  "controller-panel", "controller-status", "heading-key",
].map((id) => [id, document.getElementById(id)]));

const KNOWN_LEVEL_IDS = LEVEL_CATALOG.map((entry) => entry.id);
const SETTINGS_CONTROL_IDS = Object.freeze({
  idleTour: "setting-idle-tour",
  reduceMotion: "setting-reduce-motion",
  clearView: "setting-clear-view",
  showTrail: "setting-show-trail",
  showImpactMarkers: "setting-show-impact-markers",
  showGrid: "setting-show-grid",
  confirmReset: "setting-confirm-reset",
  controllerEnabled: "setting-controller-enabled",
});

let level;
let workspace;
let simulation;
let runtime;
let actionRouter;
let gamepadController;
let multiplayerClient;
let editorMode = "blocks";
let pythonDetached = false;
let robotPlaced = false;
let robotStartPose = null;
let attemptHistory = [];
let attemptCounter = 0;
let activeAttemptId = null;
let latestTelemetry = { heading: 0, speed: 0, commandedSpeed: 0, collisions: 0, x: 0, z: 0 };
let running = false;
let activeRunId = 0;
let programSucceeded = false;
let saveTimer = 0;
let saveStatusTimer = 0;
let levelLoading = true;
let layoutResizeFrame = 0;
let statePersistenceSuspended = false;
let userSettings = loadSettings();
document.documentElement.dataset.reduceMotion = String(userSettings.reduceMotion);

async function start() {
  try {
    populateLevelSelector();
    const requestedLevelId = new URLSearchParams(location.search).get("level");
    const initialLevelId = chooseInitialLevelId(requestedLevelId, loadLastLevelId());
    level = await loadLevel(initialLevelId);
    renderLevelDetails();

    workspace = createWorkspace("blockly-editor");
    restorePrograms();
    updateGeneratedPython();
    workspace.addChangeListener(handleWorkspaceChange);

    const restorePlacement = robotPlaced;
    const restorePose = robotStartPose;
    simulation = new MazeSimulation(document.getElementById("maze-canvas"), {
      onLoaded: () => { elements["scene-loading"].hidden = true; },
      onPlacement: handlePlacement,
      onTelemetry: updateTelemetry,
      onGoal: handleGoal,
      onCollision: handleCollision,
    });
    await simulation.loadLevel(level);
    if (restorePlacement) simulation.placeOnStart(restorePose);
    configureGameActions();
    multiplayerClient = createMultiplayerClient({
      levelId: level.id,
      participantId: createLocalParticipantId(),
      executeLocalCommand: (method, args) => simulation.executeRpc(method, args),
      onRemoteAction: (action) => dispatchGameAction(action, { source: "remote" }),
      onError: (error, context) => {
        appendLog(`MULTIPLAYER ${String(context || "ERROR").toUpperCase()}: ${String(error?.message || error)}`);
      },
      clientVersion: "static-client-v1",
    });
    actionRouter.subscribe((action) => {
      if (!["ui", "gamepad"].includes(action.source) || !isShareableGameAction(action)) return;
      multiplayerClient.shareAction(action);
    });

    runtime = new PythonRuntime({
      onRpc: (method, args) => multiplayerClient.executeRobotCommand({ method, args }),
      onLog: appendLog,
      onState: handleRuntimeState,
    });
    gamepadController = createGamepadController({
      onAction: handleGamepadAction,
      onStatus: updateControllerStatus,
      shouldHandleInput: shouldHandleGamepadInput,
    });
    bindInterface();
    applyUserSettings({ persist: false, announce: false });
    if (hasLegacySavedState()) {
      appendLog("LEGACY BACKUP: An older absolute-heading program remains stored, but was not loaded under the new robot-relative controls.");
    }
    setEditorMode(editorMode, false);
    updatePythonNotice();
    updateControls();
    if (restorePlacement) setStatus("Ready to run", "ready");
    levelLoading = false;
    updateControls();
    registerServiceWorker();
  } catch (error) {
    elements["scene-loading"].textContent = "The game could not start.";
    setStatus("Loading error", "error");
    appendLog(`ERROR: ${error.message || error}`);
    console.error(error);
  }
}

async function loadLevel(levelId) {
  const entry = levelEntry(levelId);
  if (!entry) throw new Error(`Unknown level: ${levelId}`);
  const response = await fetch(entry.file, { cache: "no-cache" });
  if (!response.ok) throw new Error(`Level file returned ${response.status}.`);
  const loaded = await response.json();
  if (loaded.id !== entry.id) throw new Error(`Level file ${entry.file} has the wrong id.`);
  return loaded;
}

function restorePrograms() {
  restoreProgramsFromState(loadSavedState(level.id));
}

function restoreProgramsFromState(saved) {
  editorMode = "blocks";
  pythonDetached = false;
  robotPlaced = false;
  robotStartPose = null;
  attemptHistory = [];
  attemptCounter = 0;
  activeAttemptId = null;
  elements["python-editor"].value = "";
  if (saved?.blocks) {
    try { loadBlocks(workspace, saved.blocks); }
    catch { createStarterProgram(workspace); }
    editorMode = saved.editorMode === "python" ? "python" : "blocks";
    pythonDetached = Boolean(saved.pythonDetached);
    robotPlaced = Boolean(saved.robotPlaced);
    robotStartPose = robotPlaced ? savedStartPose(saved.robotStartPose) : null;
    attemptHistory = normalizeAttemptHistory(saved.attempts);
    attemptCounter = Math.max(
      Number.isInteger(saved.attemptCounter) ? saved.attemptCounter : 0,
      ...attemptHistory.map((attempt) => attempt.number),
    );
    if (pythonDetached && typeof saved.pythonSource === "string") {
      elements["python-editor"].value = saved.pythonSource.slice(0, 20_000);
    }
  } else {
    createStarterProgram(workspace);
  }
  renderAttemptHistory();
}

function bindInterface() {
  elements["level-select"].addEventListener("change", (event) => dispatchGameAction({
    kind: GAME_ACTION_KINDS.SELECT_LEVEL,
    payload: { levelId: event.currentTarget.value },
  }));
  elements["place-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.PLACE_CENTER));
  elements["idle-tour-button"].addEventListener("click", () => {
    userSettings = { ...userSettings, idleTour: !userSettings.idleTour };
    applyUserSettings({ persist: true });
  });
  elements["maze-canvas"].addEventListener("keydown", handleMazeRotationShortcut);
  elements["maze-fullscreen-button"].addEventListener("click", () => void togglePanelFullscreen(elements["maze-panel"]));
  elements["studio-fullscreen-button"].addEventListener("click", () => void togglePanelFullscreen(elements["code-studio"]));
  elements["run-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.RUN));
  elements["stop-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.STOP));
  elements["reset-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.RESET));
  elements["run-again-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.RUN_AGAIN));
  elements["next-level-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.NEXT_LEVEL));
  elements["save-work-button"].addEventListener("click", saveCurrentVersion);
  elements["attempt-history-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.OPEN_ATTEMPTS));
  elements["export-work-button"].addEventListener("click", exportStudentWork);
  elements["import-work-button"].addEventListener("click", () => elements["import-work-file"].click());
  elements["import-work-file"].addEventListener("change", (event) => void importStudentWork(event));
  elements["settings-button"].addEventListener("click", () => dispatchGameAction(GAME_ACTION_KINDS.OPEN_SETTINGS));
  elements["settings-dialog"].addEventListener("close", () => {
    if (!elements["attempt-history-dialog"].open) elements["settings-button"].focus();
  });
  elements["settings-defaults-button"].addEventListener("click", restoreDefaultSettings);
  for (const [key, id] of Object.entries(SETTINGS_CONTROL_IDS)) {
    elements[id].addEventListener("change", (event) => {
      userSettings = { ...userSettings, [key]: event.currentTarget.checked };
      applyUserSettings({ persist: true });
    });
  }
  elements["clear-log"].addEventListener("click", () => { elements["program-log"].textContent = ""; });
  elements["blocks-tab"].addEventListener("click", () => setEditorMode("blocks"));
  elements["python-tab"].addEventListener("click", () => setEditorMode("python"));
  elements["blocks-tab"].addEventListener("keydown", handleTabKeys);
  elements["python-tab"].addEventListener("keydown", handleTabKeys);
  elements["python-editor"].addEventListener("input", () => {
    pythonDetached = true;
    updatePythonNotice();
    scheduleSave();
  });
  elements["python-editor"].addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    event.preventDefault();
    const editor = event.currentTarget;
    const start = editor.selectionStart;
    editor.setRangeText("    ", start, editor.selectionEnd, "end");
    editor.dispatchEvent(new Event("input", { bubbles: true }));
  });
  elements["regenerate-python"].addEventListener("click", () => {
    if (pythonDetached && !window.confirm("Replace your edited Python with code generated from the blocks?")) return;
    pythonDetached = false;
    updateGeneratedPython();
    updatePythonNotice();
    scheduleSave();
  });
  window.addEventListener("beforeunload", (event) => {
    if (persistState()) return;
    event.preventDefault();
    event.returnValue = "";
  });
  window.addEventListener("pagehide", () => {
    gamepadController?.destroy();
    multiplayerClient?.destroy();
  }, { once: true });
  document.addEventListener("fullscreenchange", updateFullscreenControls);
  document.addEventListener("fullscreenerror", () => appendLog("Fullscreen is unavailable in this browser window."));
  window.addEventListener("resize", scheduleInteractiveResize, { passive: true });
  window.addEventListener("orientationchange", scheduleInteractiveResize, { passive: true });
  window.visualViewport?.addEventListener("resize", scheduleInteractiveResize, { passive: true });
  updateFullscreenControls();
}

function configureGameActions() {
  actionRouter = new GameActionRouter({
    onError: (error, action) => {
      appendLog(`CONTROL ERROR (${action.kind}): ${String(error?.message || error)}`);
      console.error(error);
    },
  });
  actionRouter.register(GAME_ACTION_KINDS.PLACE_CENTER, () => simulation.placeOnStart());
  actionRouter.register(GAME_ACTION_KINDS.RUN, () => runProgram());
  actionRouter.register(GAME_ACTION_KINDS.STOP, () => stopProgram());
  actionRouter.register(GAME_ACTION_KINDS.RESET, () => requestReset());
  actionRouter.register(GAME_ACTION_KINDS.RUN_AGAIN, () => {
    const source = prepareProgramSource();
    if (source === null) return false;
    elements["success-banner"].hidden = true;
    resetAttempt();
    return startProgram(source);
  });
  actionRouter.register(GAME_ACTION_KINDS.TOGGLE_EDITOR, () => {
    if (running || levelLoading) return false;
    setEditorMode(editorMode === "blocks" ? "python" : "blocks");
    elements[`${editorMode}-tab`].focus({ preventScroll: true });
    return true;
  });
  actionRouter.register(GAME_ACTION_KINDS.OPEN_SETTINGS, () => toggleSettings());
  actionRouter.register(GAME_ACTION_KINDS.OPEN_ATTEMPTS, () => toggleAttemptHistory());
  actionRouter.register(GAME_ACTION_KINDS.PREVIOUS_LEVEL, () => switchRelativeLevel(-1));
  actionRouter.register(GAME_ACTION_KINDS.NEXT_LEVEL, () => switchRelativeLevel(1));
  actionRouter.register(GAME_ACTION_KINDS.SELECT_LEVEL, (action) => switchLevel(action.payload.levelId));
}

function dispatchGameAction(value, { source = "ui" } = {}) {
  const pending = actionRouter?.dispatch(value, { source });
  if (!pending) return Promise.resolve(false);
  return pending.catch(() => false);
}

function switchRelativeLevel(offset) {
  if (running || levelLoading) return false;
  const index = LEVEL_CATALOG.findIndex((entry) => entry.id === level.id);
  const target = LEVEL_CATALOG[index + offset];
  if (!target) return false;
  return switchLevel(target.id);
}

function toggleSettings() {
  if (elements["settings-dialog"].open) {
    elements["settings-dialog"].close();
    return false;
  }
  openSettings();
  return true;
}

function toggleAttemptHistory() {
  if (elements["attempt-history-dialog"].open) {
    elements["attempt-history-dialog"].close();
    elements["attempt-history-button"].focus({ preventScroll: true });
    return false;
  }
  if (running || levelLoading) return false;
  openAttemptHistory();
  return true;
}

function handleGamepadAction(action) {
  const options = { source: "gamepad" };
  switch (action) {
    case GAMEPAD_ACTIONS.PRIMARY:
      if (!robotPlaced) return dispatchGameAction(GAME_ACTION_KINDS.PLACE_CENTER, options);
      return dispatchGameAction(programSucceeded ? GAME_ACTION_KINDS.RUN_AGAIN : GAME_ACTION_KINDS.RUN, options);
    case GAMEPAD_ACTIONS.STOP: return dispatchGameAction(GAME_ACTION_KINDS.STOP, options);
    case GAMEPAD_ACTIONS.RESET: return dispatchGameAction(GAME_ACTION_KINDS.RESET, options);
    case GAMEPAD_ACTIONS.TOGGLE_EDITOR: return dispatchGameAction(GAME_ACTION_KINDS.TOGGLE_EDITOR, options);
    case GAMEPAD_ACTIONS.ATTEMPTS: return dispatchGameAction(GAME_ACTION_KINDS.OPEN_ATTEMPTS, options);
    case GAMEPAD_ACTIONS.SETTINGS: return dispatchGameAction(GAME_ACTION_KINDS.OPEN_SETTINGS, options);
    case GAMEPAD_ACTIONS.PREVIOUS_LEVEL: return dispatchGameAction(GAME_ACTION_KINDS.PREVIOUS_LEVEL, options);
    case GAMEPAD_ACTIONS.NEXT_LEVEL: return dispatchGameAction(GAME_ACTION_KINDS.NEXT_LEVEL, options);
    default: return false;
  }
}

function shouldHandleGamepadInput(action) {
  if (action === GAMEPAD_ACTIONS.STOP) return running;
  if (action === GAMEPAD_ACTIONS.SETTINGS) return true;
  if (elements["settings-dialog"].open) return false;
  if (elements["attempt-history-dialog"].open) return action === GAMEPAD_ACTIONS.ATTEMPTS;
  if (isTextEntryActive()) return false;
  if (levelLoading) return false;
  if (running) return action === GAMEPAD_ACTIONS.RESET;
  return true;
}

function isTextEntryActive() {
  const active = document.activeElement;
  return active instanceof HTMLInputElement
    || active instanceof HTMLTextAreaElement
    || active instanceof HTMLSelectElement
    || Boolean(active?.isContentEditable)
    || Boolean(active?.closest?.(".blocklyWidgetDiv, .blocklyDropDownDiv"));
}

function updateControllerStatus(status = { state: GAMEPAD_STATUS.DISABLED }) {
  const messages = {
    [GAMEPAD_STATUS.DISABLED]: "Controller support is off.",
    [GAMEPAD_STATUS.UNSUPPORTED]: "This browser does not provide controller support.",
    [GAMEPAD_STATUS.SEARCHING]: "Waiting for a controller. Pair it in Bluetooth, then press any controller button.",
    [GAMEPAD_STATUS.DISCONNECTED]: "Controller disconnected. Reconnect it, then press any controller button.",
  };
  const connected = status.state === GAMEPAD_STATUS.CONNECTED;
  elements["controller-status"].textContent = connected
    ? `Connected: ${status.label || "controller"}.`
    : messages[status.state] || "Controller status unavailable.";
  elements["controller-status"].dataset.state = status.state;
}

function updateIdleTourButton() {
  const enabled = userSettings.idleTour;
  const paused = enabled && simulation?.isReducedMotionActive();
  const stateLabel = paused ? "paused" : enabled ? "on" : "off";
  elements["idle-tour-button"].setAttribute("aria-pressed", String(enabled));
  elements["idle-tour-button"].setAttribute(
    "aria-label",
    `Turn idle tour ${enabled ? "off" : "on"}${paused ? "; currently paused by reduced motion" : ""}`,
  );
  elements["idle-tour-button"].textContent = `Idle tour: ${stateLabel}`;
  elements["idle-tour-button"].dataset.mobileLabel = `Tour ${stateLabel}`;
}

function handleMazeRotationShortcut(event) {
  if (!isMazeRotationShortcut(event)) return;
  event.preventDefault();
  event.stopPropagation();
  userSettings = { ...userSettings, idleTour: true };
  applyUserSettings({ persist: true, announce: false });
  simulation.startIdleTour();
  updateIdleTourButton();
}

function openSettings() {
  if (elements["attempt-history-dialog"].open) elements["attempt-history-dialog"].close();
  applyUserSettings({ persist: false, announce: false });
  if (!elements["settings-dialog"].open) elements["settings-dialog"].showModal();
  requestAnimationFrame(() => elements["setting-idle-tour"].focus());
}

function applyUserSettings({ persist = false, announce = true } = {}) {
  userSettings = normalizeSettings(userSettings);
  for (const [key, id] of Object.entries(SETTINGS_CONTROL_IDS)) {
    elements[id].checked = userSettings[key];
  }
  document.documentElement.dataset.reduceMotion = String(userSettings.reduceMotion);
  simulation?.applyVisualSettings(userSettings);
  elements["controller-panel"].hidden = !userSettings.controllerEnabled;
  gamepadController?.setEnabled(userSettings.controllerEnabled);
  updateIdleTourButton();
  if (persist) {
    const saved = saveSettings(userSettings);
    elements["settings-status"].textContent = saved
      ? "Saved on this device."
      : "Active for now, but this browser could not save the choice.";
    elements["settings-status"].dataset.state = saved ? "" : "error";
  } else if (announce) {
    elements["settings-status"].textContent = "";
    elements["settings-status"].dataset.state = "";
  }
  scheduleInteractiveResize();
  return { ...userSettings };
}

function restoreDefaultSettings() {
  userSettings = { ...DEFAULT_SETTINGS };
  applyUserSettings({ persist: true });
  if (elements["settings-status"].dataset.state !== "error") {
    elements["settings-status"].textContent = "Defaults restored and saved.";
  }
}

async function togglePanelFullscreen(panel) {
  if (!panel || typeof panel.requestFullscreen !== "function") return;
  try {
    if (document.fullscreenElement === panel) await document.exitFullscreen();
    else if (!document.fullscreenElement) await panel.requestFullscreen();
  } catch {
    appendLog("Fullscreen is unavailable in this browser window.");
  }
}

function updateFullscreenControls() {
  const fullscreenSupported = document.fullscreenEnabled !== false && typeof Element.prototype.requestFullscreen === "function";
  const controls = [
    [elements["maze-fullscreen-button"], elements["maze-panel"], "maze"],
    [elements["studio-fullscreen-button"], elements["code-studio"], "Coding Workspace"],
  ];
  for (const [button, panel, label] of controls) {
    const active = document.fullscreenElement === panel;
    button.hidden = !fullscreenSupported;
    button.setAttribute("aria-pressed", String(active));
    button.setAttribute("aria-label", `${active ? "Exit" : "Open"} ${label} fullscreen`);
    button.title = `${active ? "Exit" : "Open"} ${label} fullscreen`;
  }
  scheduleInteractiveResize();
}

function scheduleInteractiveResize() {
  cancelAnimationFrame(layoutResizeFrame);
  layoutResizeFrame = requestAnimationFrame(() => {
    simulation?.resize();
    if (workspace) Blockly.svgResize(workspace);
  });
}

function populateLevelSelector() {
  elements["level-select"].replaceChildren(...LEVEL_CATALOG.map((entry) => {
    const option = document.createElement("option");
    option.value = entry.id;
    option.textContent = `${entry.sequence} · ${entry.name} — ${entry.difficulty}`;
    return option;
  }));
}

function renderLevelDetails({ updateUrl = true } = {}) {
  const entry = levelEntry(level.id);
  elements["level-select"].value = level.id;
  elements["level-name"].textContent = level.name;
  elements["level-description"].textContent = level.description;
  elements["level-number"].textContent = `Sphere robotics · maze ${String(entry.sequence).padStart(2, "0")} of ${String(LEVEL_CATALOG.length).padStart(2, "0")}`;
  elements["level-difficulty"].textContent = level.difficulty;
  elements["success-level-name"].textContent = `${level.name} solved.`;
  elements["next-level-button"].hidden = !nextLevelId(level.id);
  if (updateUrl) updateLevelUrl(level.id);
}

async function switchLevel(levelId, { persistCurrent = true } = {}) {
  if (levelLoading || running || levelId === level.id || !levelEntry(levelId)) {
    elements["level-select"].value = level.id;
    return false;
  }

  if (persistCurrent && !persistState()) {
    elements["level-select"].value = level.id;
    setSaveStatus("Maze not changed · current work is not saved", "error");
    appendLog("SAVE FAILED: Fix the current program or export a recovery copy before changing mazes.");
    return false;
  }
  const previousLevel = level;
  const savedPreviousState = persistCurrent ? currentStateRecord() : loadSavedState(level.id);
  const previousState = cloneLevelStateRecord(savedPreviousState || currentStateRecord());
  const previousSimulationSession = simulation.captureSession();
  const previousUi = {
    programSucceeded,
    runState: elements["run-state"].textContent,
    runStateKind: elements["run-state"].dataset.state,
    successHidden: elements["success-banner"].hidden,
  };
  clearTimeout(saveTimer);
  saveTimer = 0;
  statePersistenceSuspended = true;
  if (elements["attempt-history-dialog"].open) elements["attempt-history-dialog"].close();
  activeRunId += 1;
  runtime?.terminate("Level changed.");
  simulation.cancelDrag();
  simulation.cancelMotion("Level changed.");
  levelLoading = true;
  running = false;
  programSucceeded = false;
  elements["success-banner"].hidden = true;
  elements["scene-loading"].textContent = "Loading maze pieces…";
  elements["scene-loading"].hidden = false;
  setStatus("Loading level…", "running");
  updateControls();

  let recoveryFailed = false;
  try {
    const nextLevel = await loadLevel(levelId);
    level = nextLevel;
    await simulation.loadLevel(level);
    restorePrograms();
    updateGeneratedPython();
    setEditorMode(editorMode, false);
    updatePythonNotice();
    const restorePlacement = robotPlaced;
    const restorePose = robotStartPose;
    if (restorePlacement) simulation.placeOnStart(restorePose);
    renderLevelDetails();
    setStatus(restorePlacement ? "Ready to run" : "Waiting for robot", restorePlacement ? "ready" : "waiting");
    appendLog(`LEVEL ${level.sequence} OF ${LEVEL_CATALOG.length}: ${level.name}`);
    statePersistenceSuspended = false;
    if (!persistState()) setSaveStatus("Maze loaded · current work could not be saved", "warning");
    return true;
  } catch (error) {
    level = previousLevel;
    if (simulation.level?.id !== previousLevel.id) {
      try {
        await simulation.loadLevel(previousLevel);
      } catch (recoveryError) {
        recoveryFailed = true;
        elements["scene-loading"].textContent = "Reload the page to recover the maze.";
        elements["scene-loading"].hidden = false;
        setStatus("Maze recovery required", "error");
        appendLog(`LEVEL RECOVERY FAILED: ${recoveryError.message || recoveryError}`);
        console.error(recoveryError);
      }
    }
    if (recoveryFailed) return false;
    restoreProgramsFromState(previousState);
    updateGeneratedPython();
    setEditorMode(editorMode, false);
    updatePythonNotice();
    simulation.restoreSession(previousSimulationSession);
    programSucceeded = previousUi.programSucceeded;
    elements["success-banner"].hidden = previousUi.successHidden;
    renderLevelDetails({ updateUrl: false });
    try { updateLevelUrl(previousLevel.id); }
    catch (urlError) {
      appendLog(`LEVEL URL RECOVERY FAILED: ${urlError.message || urlError}`);
      console.error(urlError);
    }
    elements["scene-loading"].hidden = true;
    setStatus(previousUi.runState, previousUi.runStateKind);
    appendLog(`LEVEL LOAD FAILED: ${error.message || error} Staying on ${level.name}.`);
    console.error(error);
    return false;
  } finally {
    statePersistenceSuspended = recoveryFailed;
    levelLoading = recoveryFailed;
    updateControls();
  }
}

function cloneLevelStateRecord(record) {
  return JSON.parse(JSON.stringify(record));
}

function updateLevelUrl(levelId) {
  const url = new URL(location.href);
  url.searchParams.set("level", levelId);
  history.replaceState(null, "", url);
}

function handleTabKeys(event) {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  event.preventDefault();
  const nextMode = editorMode === "blocks" ? "python" : "blocks";
  setEditorMode(nextMode);
  elements[`${nextMode}-tab`].focus();
}

function handleWorkspaceChange(event) {
  if (isUiEvent(event)) return;
  updateGeneratedPython();
  scheduleSave();
}

function updateGeneratedPython() {
  if (!workspace || pythonDetached) return;
  elements["python-editor"].value = generatePython(workspace);
}

function updatePythonNotice() {
  if (pythonDetached) {
    elements["python-mode-label"].textContent = "Independent Python copy";
    elements["python-mode-label"].style.color = "#ffd278";
    elements["regenerate-python"].hidden = false;
  } else {
    elements["python-mode-label"].textContent = "Generated from blocks";
    elements["python-mode-label"].style.color = "";
    elements["regenerate-python"].hidden = true;
  }
}

function setEditorMode(mode, persist = true) {
  editorMode = mode === "python" ? "python" : "blocks";
  const blocksActive = editorMode === "blocks";
  elements["blocks-tab"].classList.toggle("is-active", blocksActive);
  elements["python-tab"].classList.toggle("is-active", !blocksActive);
  elements["blocks-tab"].setAttribute("aria-selected", String(blocksActive));
  elements["python-tab"].setAttribute("aria-selected", String(!blocksActive));
  elements["blocks-panel"].hidden = !blocksActive;
  elements["python-panel"].hidden = blocksActive;
  if (!blocksActive) updateGeneratedPython();
  else requestAnimationFrame(() => Blockly.svgResize(workspace));
  if (persist) scheduleSave();
}

function handlePlacement(placed, pose = null) {
  robotPlaced = placed;
  robotStartPose = placed ? savedStartPose(pose) : null;
  elements["scene-help"].hidden = placed;
  if (placed) {
    setStatus("Ready to run", "ready");
    appendLog(
      `Robot placed on START at x ${formatCoordinate(robotStartPose?.x)}, ` +
      `z ${formatCoordinate(robotStartPose?.z)}, facing world bearing ${level.start.heading}°.`,
    );
  } else {
    setStatus("Waiting for robot", "waiting");
  }
  updateControls();
  scheduleSave();
}

function runProgram() {
  const source = prepareProgramSource();
  if (source === null) return false;
  return startProgram(source);
}

function prepareProgramSource() {
  if (running || !robotPlaced) return null;
  const source = editorMode === "blocks" ? generatePython(workspace) : elements["python-editor"].value;
  if (!source.trim() || source.trimStart().startsWith("# Add blocks")) {
    setStatus("Add some code first", "error");
    return null;
  }
  if (source.length > MAX_CODE_CHARACTERS) {
    setStatus("Program is too long", "error");
    setSaveStatus("Not saved · 20,000-character maximum", "error");
    appendLog("PROGRAM TOO LONG: shorten the generated or Python code to 20,000 characters.");
    return null;
  }
  return source;
}

function startProgram(source) {
  const runId = ++activeRunId;
  running = true;
  programSucceeded = false;
  elements["success-banner"].hidden = true;
  simulation.beginAttempt();
  const attemptId = recordHistoryEntry("run", source).id;
  activeAttemptId = attemptId;
  setStatus("Loading Python…", "running");
  appendLog(`RUN · ${editorMode === "blocks" ? "Blocks → Python" : "Python"}`);
  updateControls();
  void executeProgram(source, runId, attemptId).catch((error) => {
    appendLog(`CONTROL ERROR (run): ${String(error?.message || error)}`);
    console.error(error);
  });
  return true;
}

async function executeProgram(source, runId, attemptId) {
  try {
    await runtime.run(source);
    if (!programSucceeded) {
      setStatus("Finished · stop on goal required", "ready");
      appendLog("Program finished before the robot stopped on GOAL.");
      finalizeHistoryEntry(attemptId, "goal-not-reached", "Program finished before stopping on GOAL.");
    }
  } catch (error) {
    if (activeRunId !== runId) return;
    if (programSucceeded) return;
    const message = String(error?.message || error);
    if (message !== "Stopped by student." && message !== "Reset by student.") {
      const cleaned = cleanError(message);
      setStatus("Program needs debugging", "error");
      appendLog(`ERROR: ${cleaned}`);
      finalizeHistoryEntry(attemptId, "error", cleaned);
    }
  } finally {
    if (activeRunId === runId) {
      running = false;
      updateControls();
    }
  }
}

function stopProgram() {
  if (!running) return false;
  activeRunId += 1;
  runtime.terminate("Stopped by student.");
  simulation.cancelMotion("Stopped by student.");
  simulation.state.speed = 0;
  finalizeHistoryEntry(activeAttemptId, "stopped", "Stopped by student.");
  running = false;
  setStatus("Stopped", "ready");
  appendLog("Program stopped by student.");
  updateControls();
  return true;
}

function resetAttempt() {
  if (running) finalizeHistoryEntry(activeAttemptId, "reset", "Reset before the program finished.");
  activeRunId += 1;
  runtime?.terminate("Reset by student.");
  simulation.reset(true);
  running = false;
  programSucceeded = false;
  elements["success-banner"].hidden = true;
  setStatus(robotPlaced ? "Ready to run" : "Waiting for robot", robotPlaced ? "ready" : "waiting");
  appendLog("Robot reset to your chosen starting position.");
  updateControls();
}

function requestReset() {
  if (userSettings.confirmReset && !window.confirm(
    running
      ? "Stop this run and reset the robot to your chosen starting position?"
      : "Reset the robot to your chosen starting position?",
  )) return false;
  resetAttempt();
  return true;
}

function handleGoal() {
  if (programSucceeded) return;
  programSucceeded = true;
  finalizeHistoryEntry(activeAttemptId, "solved", "Stopped on GOAL.");
  setStatus("Maze solved!", "success");
  elements["success-banner"].hidden = false;
  appendLog("SUCCESS: The robot stopped on GOAL.");
  runtime?.terminate("Goal stop confirmed.");
}

function handleCollision(count) {
  if (running) setStatus("Running · wall bounce", "running");
  appendLog(`IMPACT ${count}: The robot bounced and kept following its command.`);
}

function handleRuntimeState(state, detail) {
  if (state === "loading") {
    setStatus("Loading local Python…", "running");
    appendLog("Starting the local Python runtime (first run can take a moment)…");
  } else if (state === "ready" && detail) {
    appendLog(`Python ${detail} ready.`);
  }
}

function updateTelemetry(data) {
  latestTelemetry = { ...data };
  if (multiplayerClient?.session.mode === "room") {
    multiplayerClient.projectLocalRobot(data, {
      levelId: level.id,
      status: programSucceeded ? "solved" : running ? "running" : null,
    });
  }
  elements.telemetry.textContent = `Facing ${data.heading}° · Drive ${data.commandedSpeed} · Actual ${data.speed} · Impacts ${data.collisions} · x ${data.x}, z ${data.z}`;
}

function setStatus(text, state) {
  elements["run-state"].textContent = text;
  elements["run-state"].dataset.state = state;
}

function updateControls() {
  elements["run-button"].disabled = !robotPlaced || running || levelLoading;
  elements["stop-button"].disabled = !running;
  elements["place-button"].disabled = running || levelLoading;
  elements["reset-button"].disabled = !simulation || levelLoading;
  elements["blocks-tab"].disabled = running || levelLoading;
  elements["python-tab"].disabled = running || levelLoading;
  elements["python-editor"].readOnly = running || levelLoading;
  elements["level-select"].disabled = running || levelLoading;
  elements["next-level-button"].disabled = running || levelLoading;
  elements["save-work-button"].disabled = running || levelLoading;
  elements["attempt-history-button"].disabled = running || levelLoading;
  elements["export-work-button"].disabled = running || levelLoading;
  elements["import-work-button"].disabled = running || levelLoading;
}

function appendLog(text) {
  const log = elements["program-log"];
  const clean = String(text).replace(/\0/g, "").slice(0, 2000);
  const lines = `${log.textContent}${log.textContent ? "\n" : ""}${clean}`.split("\n");
  log.textContent = lines.slice(-80).join("\n");
  log.scrollTop = log.scrollHeight;
}

function cleanError(message) {
  const lines = message.split("\n").filter((line) => !line.includes("pyodide") && !line.includes("__run_student"));
  return lines.slice(-6).join("\n").slice(0, 1200);
}

function scheduleSave() {
  if (statePersistenceSuspended) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const saved = persistState();
    if (!saved) {
      setSaveStatus("Not saved · shorten the program or export a recovery copy", "error");
    } else if (elements["save-status"].dataset.state === "error") {
      setSaveStatus("Autosaved locally", "success");
    }
  }, 250);
}

function persistState() {
  if (statePersistenceSuspended) return false;
  clearTimeout(saveTimer);
  saveTimer = 0;
  if (!workspace || !level) return false;
  try { return saveState(currentStateRecord()); }
  catch { return false; }
}

function currentStateRecord() {
  const editorSource = elements["python-editor"].value;
  return {
    levelId: level.id,
    editorMode,
    blocks: saveBlocks(workspace),
    pythonSource: pythonDetached ? editorSource : editorSource.slice(0, MAX_CODE_CHARACTERS),
    pythonDetached,
    robotPlaced,
    robotStartPose,
    attempts: attemptHistory,
    attemptCounter,
  };
}

function currentCode() {
  return editorMode === "blocks" ? generatePython(workspace) : elements["python-editor"].value;
}

function recordHistoryEntry(kind, source = currentCode()) {
  if (attemptCounter >= MAX_ATTEMPT_NUMBER) {
    attemptHistory = attemptHistory.map((attempt, index) => ({ ...attempt, number: index + 1 }));
    attemptCounter = attemptHistory.length;
  }
  const now = new Date().toISOString();
  const number = ++attemptCounter;
  const entry = {
    id: "attempt-" + level.id + "-" + Date.now().toString(36) + "-" + number,
    number,
    kind,
    startedAt: now,
    finishedAt: kind === "save" ? now : null,
    editorMode,
    code: String(source).slice(0, MAX_CODE_CHARACTERS),
    outcome: kind === "save" ? "saved" : "running",
    message: kind === "save" ? "Saved by student." : "Program started.",
    impacts: 0,
    startPose: robotStartPose ? { ...robotStartPose } : null,
    finalPose: null,
  };
  attemptHistory = normalizeAttemptHistory(
    [...attemptHistory, entry],
    { markRunningInterrupted: false },
  );
  const saved = persistState();
  renderAttemptHistory();
  if (!saved) setSaveStatus("Could not save · browser storage may be full", "error");
  return { id: entry.id, number, saved };
}

function finalizeHistoryEntry(attemptId, outcome, message) {
  if (!attemptId) return false;
  const index = attemptHistory.findIndex((attempt) => attempt.id === attemptId);
  if (index < 0 || attemptHistory[index].outcome !== "running") return false;
  const current = attemptHistory[index];
  const finalPose = {
    x: Number(latestTelemetry.x) || 0,
    z: Number(latestTelemetry.z) || 0,
    heading: Number(latestTelemetry.heading) || 0,
  };
  attemptHistory[index] = {
    ...current,
    finishedAt: new Date().toISOString(),
    outcome,
    message: String(message || "").slice(0, 500),
    impacts: Math.max(0, Math.round(Number(latestTelemetry.collisions) || 0)),
    finalPose,
  };
  attemptHistory = normalizeAttemptHistory(attemptHistory, { markRunningInterrupted: false });
  if (activeAttemptId === attemptId) activeAttemptId = null;
  const saved = persistState();
  renderAttemptHistory();
  if (!saved) setSaveStatus("Attempt finished, but browser storage is full", "error");
  return true;
}

function saveCurrentVersion() {
  const source = currentCode();
  if (source.length > MAX_CODE_CHARACTERS) {
    setSaveStatus("Not saved · 20,000-character maximum", "error");
    appendLog("SAVE FAILED: shorten the generated or Python code to 20,000 characters.");
    return;
  }
  const entry = recordHistoryEntry("save", source);
  if (!entry.saved) return;
  setSaveStatus("Saved version " + entry.number, "success");
  appendLog("SAVED VERSION " + entry.number + ": current " + (editorMode === "blocks" ? "Blocks" : "Python") + " code.");
}

function openAttemptHistory() {
  if (elements["settings-dialog"].open) elements["settings-dialog"].close();
  renderAttemptHistory();
  const dialog = elements["attempt-history-dialog"];
  if (!dialog.open) dialog.showModal();
  requestAnimationFrame(() => {
    elements["attempt-history-list"].scrollTop = elements["attempt-history-list"].scrollHeight;
  });
}

function renderAttemptHistory() {
  if (!elements["attempt-history-list"]) return;
  elements["attempt-count"].textContent = String(attemptHistory.length);
  elements["attempt-history-title"].textContent = (level?.name || "Maze") + " attempt history";
  elements["attempt-history-summary"].textContent = attemptHistory.length
    ? attemptHistory.length + " of " + MAX_ATTEMPTS_PER_LEVEL + " saved entries · Every Run records the exact executed code."
    : "No attempts yet · Run code or select Save. The latest " + MAX_ATTEMPTS_PER_LEVEL + " entries are kept for each maze.";
  const list = elements["attempt-history-list"];
  list.replaceChildren();
  if (!attemptHistory.length) {
    const empty = document.createElement("p");
    empty.className = "attempt-empty";
    empty.textContent = "Your code progress will appear here after the first Run or Save.";
    list.append(empty);
    return;
  }

  attemptHistory.forEach((attempt, index) => {
    const previous = attemptHistory[index - 1];
    const article = document.createElement("article");
    article.className = "attempt-card";

    const header = document.createElement("div");
    header.className = "attempt-card-header";
    const title = document.createElement("div");
    title.className = "attempt-card-title";
    const strong = document.createElement("strong");
    strong.textContent = attempt.kind === "save" ? "Saved version " + attempt.number : "Attempt " + attempt.number;
    const outcome = document.createElement("span");
    outcome.className = "attempt-outcome";
    outcome.dataset.outcome = attempt.outcome;
    outcome.textContent = outcomeLabel(attempt.outcome);
    title.append(strong, outcome);
    const time = document.createElement("time");
    time.dateTime = attempt.startedAt;
    time.textContent = new Date(attempt.startedAt).toLocaleString();
    header.append(title, time);

    const meta = document.createElement("p");
    meta.className = "attempt-meta";
    const changed = previous ? changedLineCount(previous.code, attempt.code) : null;
    const changeText = changed === null
      ? "First recorded version"
      : changed === 0 ? "No code-line changes" : changed + " code line" + (changed === 1 ? "" : "s") + " changed";
    const impactText = attempt.kind === "run" ? " · " + attempt.impacts + " impact" + (attempt.impacts === 1 ? "" : "s") : "";
    meta.textContent = (attempt.editorMode === "blocks" ? "Blocks → Python" : "Python") + impactText + " · " + changeText;

    const note = document.createElement("p");
    note.className = "attempt-note";
    note.textContent = attempt.message;
    const code = document.createElement("pre");
    code.className = "attempt-code";
    code.textContent = attempt.code;
    article.append(header, meta, note, code);
    list.append(article);
  });
}

function outcomeLabel(value) {
  return ({
    running: "Running",
    interrupted: "Interrupted",
    solved: "Solved",
    "goal-not-reached": "Did not stop on goal",
    error: "Needs debugging",
    stopped: "Stopped",
    reset: "Reset",
    saved: "Saved",
    "saved-before-import": "Before import",
  })[value] || value;
}

function changedLineCount(previous, current) {
  const before = String(previous).replace(/\r\n?/g, "\n").split("\n");
  const after = String(current).replace(/\r\n?/g, "\n").split("\n");
  let changed = 0;
  for (let index = 0; index < Math.max(before.length, after.length); index += 1) {
    if (before[index] !== after[index]) changed += 1;
  }
  return changed;
}

function exportStudentWork() {
  try {
    const snapshot = currentStateRecord();
    const persisted = persistState();
    const storage = readableBrowserStorage();
    let currentMazeOnly = false;
    let text;
    try {
      text = exportProject(KNOWN_LEVEL_IDS, storage, snapshot);
    } catch (error) {
      if (String(error?.message || error) !== "This Maskwa Maze Lab project is too large to export.") throw error;
      text = exportProject([snapshot.levelId], storage, snapshot);
      currentMazeOnly = true;
    }
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = currentMazeOnly
      ? "Maskwa-Maze-Lab-Current-Maze-Recovery-" + localDateStamp() + ".maskwamaze.json"
      : "Maskwa-Maze-Lab-Work-" + localDateStamp() + ".maskwamaze.json";
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1_000);
    if (currentMazeOnly) {
      setSaveStatus("Current-maze recovery exported · full project too large", "warning");
      appendLog("RECOVERY EXPORTED: the current maze and its history were saved; the full project exceeded 3 MB.");
    } else {
      setSaveStatus(persisted ? "Project exported" : "Recovery copy exported · local save unavailable", persisted ? "success" : "warning");
      appendLog(
        persisted
          ? "EXPORTED: all saved maze code and attempt history."
          : "RECOVERY EXPORTED: current work was included even though browser storage was unavailable.",
      );
    }
  } catch (error) {
    const message = String(error?.message || error);
    setSaveStatus(message, "error");
    appendLog("EXPORT FAILED: " + message);
  }
}

function readableBrowserStorage() {
  try {
    window.localStorage.getItem("maskwa-maze-storage-check");
    return window.localStorage;
  } catch {
    return { getItem() { return null; } };
  }
}

function localDateStamp(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function importStudentWork(event) {
  const input = event.currentTarget;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    const jsonLike = file.type === "application/json" || /\.(?:json|maskwamaze|mazebot)$/i.test(file.name);
    if (!jsonLike) throw new Error("Choose a Maskwa Maze Lab JSON project file.");
    if (file.size > MAX_PROJECT_BYTES) throw new Error("The selected project is larger than 3 MB.");
    const prepared = prepareProjectImport(await file.text(), KNOWN_LEVEL_IDS);
    for (const [levelId, record] of Object.entries(prepared.levels)) {
      try { validateBlocksState(record.blocks); }
      catch { throw new Error((levelEntry(levelId)?.name || levelId) + ": imported Blocks are invalid."); }
    }
    const confirmed = window.confirm(
      "Import this Maskwa Maze Lab project? Imported code will replace matching mazes. " +
      "Your current code is preserved in Attempt History first, and nothing will run automatically.",
    );
    if (!confirmed) {
      setSaveStatus("Import cancelled");
      return;
    }

    clearTimeout(saveTimer);
    saveTimer = 0;
    if (!persistState()) throw new Error("Current work could not be saved before import.");
    const importedActiveLevelId = prepared.activeLevelId;
    const result = commitProjectImport(prepared, KNOWN_LEVEL_IDS);
    if (importedActiveLevelId && importedActiveLevelId !== level.id) {
      await switchLevel(importedActiveLevelId, { persistCurrent: false });
    } else if (prepared.levels[level.id]) {
      restorePrograms();
      updateGeneratedPython();
      setEditorMode(editorMode, false);
      updatePythonNotice();
      if (robotPlaced) simulation.placeOnStart(robotStartPose);
      else simulation.returnToTray();
      setStatus(robotPlaced ? "Ready to run" : "Waiting for robot", robotPlaced ? "ready" : "waiting");
    }
    updateControls();
    const summary = "Imported " + result.levelCount + " maze" + (result.levelCount === 1 ? "" : "s") + " · " +
      result.preservedLocalVersions + " local version" + (result.preservedLocalVersions === 1 ? "" : "s") + " preserved";
    setSaveStatus(summary, "success");
    appendLog("IMPORTED: " + summary + ". Imported code was not run.");
  } catch (error) {
    const message = String(error?.message || error);
    setSaveStatus(message, "error");
    appendLog("IMPORT FAILED: " + message);
  }
}

function setSaveStatus(text, state = "") {
  clearTimeout(saveStatusTimer);
  elements["save-status"].textContent = text;
  elements["save-status"].dataset.state = state;
  if (state !== "error") {
    saveStatusTimer = setTimeout(() => {
      elements["save-status"].textContent = "Autosaves locally";
      elements["save-status"].dataset.state = "";
    }, 4_500);
  }
}

function savedStartPose(pose) {
  if (typeof pose?.x !== "number" || typeof pose?.z !== "number") return null;
  const x = pose.x;
  const z = pose.z;
  const heading = typeof pose?.heading === "number" ? pose.heading : Number.NaN;
  if (!Number.isFinite(x) || !Number.isFinite(z)) return null;
  return {
    x,
    z,
    heading: Number.isFinite(heading) ? heading : Number(level?.start?.heading || 0),
  };
}

function formatCoordinate(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number * 10) / 10 : "?";
}

function createLocalParticipantId() {
  try {
    const values = crypto.getRandomValues(new Uint32Array(2));
    return `student-${values[0].toString(36)}${values[1].toString(36)}`;
  } catch {
    return `student-${Date.now().toString(36)}-${Math.floor(Math.random() * 0xffffff).toString(36)}`;
  }
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || location.protocol === "file:") return;
  navigator.serviceWorker.register("./service-worker.js?v=40", { updateViaCache: "none" }).catch(() => {
    appendLog("Offline cache is unavailable; the game still works while connected to this server.");
  });
}

void start();
