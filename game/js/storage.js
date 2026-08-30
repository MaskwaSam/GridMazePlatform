const STORAGE_KEY = "mazebot-lab-state-v3";
const PREVIOUS_STORAGE_KEY = "mazebot-lab-state-v2";
const LEGACY_STORAGE_KEY = "mazebot-lab-state-v1";
const SCHEMA_VERSION = 3;

export const PROJECT_FORMAT = "maskwa-maze-lab-project";
export const LEGACY_PROJECT_FORMAT = "mazebot-lab-project";
export const PROJECT_SCHEMA_VERSION = 1;
export const HEADING_SEMANTICS = "robot-relative-v1";
export const MAX_ATTEMPTS_PER_LEVEL = 20;
export const MAX_ATTEMPT_NUMBER = 1_000_000;
export const MAX_PROJECT_BYTES = 3_000_000;
export const MAX_CODE_CHARACTERS = 20_000;

const MAX_BLOCKS_BYTES = 250_000;
const MAX_MESSAGE_CHARACTERS = 500;
const MAX_STORED_BYTES = 4_500_000;
const ATTEMPT_KINDS = new Set(["run", "save"]);
const ATTEMPT_OUTCOMES = new Set([
  "running", "interrupted", "solved", "goal-not-reached", "error", "stopped", "reset",
  "saved", "saved-before-import",
]);
const RUN_OUTCOMES = new Set(["running", "interrupted", "solved", "goal-not-reached", "error", "stopped", "reset"]);
const SAVE_OUTCOMES = new Set(["saved", "saved-before-import"]);

export function loadSavedState(levelId, storage = localStorage) {
  const collection = readCollection(storage);
  const saved = collection.levels[levelId];
  return saved && typeof saved === "object" ? saved : null;
}

export function loadLastLevelId(storage = localStorage) {
  return readCollection(storage).activeLevelId || null;
}

export function hasLegacySavedState(storage = localStorage) {
  try {
    const legacy = parse(storage.getItem(LEGACY_STORAGE_KEY));
    return Boolean(legacy && legacy.schemaVersion === 1 && typeof legacy === "object");
  } catch {
    return false;
  }
}

export function saveState(value, storage = localStorage) {
  try {
    const collection = stageLevelState(readCollection(storage), value);
    const encoded = JSON.stringify(collection);
    if (byteLength(encoded) > MAX_STORED_BYTES) return false;
    serializeProject(collection, new Set(Object.keys(collection.levels)));
    storage.setItem(STORAGE_KEY, encoded);
    return true;
  } catch {
    return false;
  }
}

export function normalizeAttemptHistory(value, { markRunningInterrupted = true } = {}) {
  if (!Array.isArray(value)) return [];
  const attempts = [];
  const seen = new Set();
  for (const candidate of value) {
    const normalized = normalizeAttempt(candidate, false, markRunningInterrupted);
    if (!normalized || seen.has(normalized.id)) continue;
    seen.add(normalized.id);
    attempts.push(normalized);
  }
  attempts.sort(compareAttempts);
  return attempts.slice(-MAX_ATTEMPTS_PER_LEVEL);
}

export function exportProject(knownLevelIds, storage = localStorage, currentState = null) {
  const allowed = knownIds(knownLevelIds);
  const collection = readCollection(storage);
  if (currentState !== null) {
    if (!allowed.has(currentState?.levelId)) throw new Error("The current maze is not available in this game.");
    stageLevelState(collection, currentState);
  }
  return serializeProject(collection, allowed);
}

function serializeProject(collection, allowed) {
  const levels = {};
  for (const levelId of allowed) {
    const saved = collection.levels[levelId];
    if (!saved || typeof saved !== "object") continue;
    levels[levelId] = normalizeLevelRecord(saved, levelId, false);
  }
  if (!Object.keys(levels).length) throw new Error("There is no saved Maskwa Maze Lab work to export yet.");
  const project = {
    format: PROJECT_FORMAT,
    schemaVersion: PROJECT_SCHEMA_VERSION,
    headingSemantics: HEADING_SEMANTICS,
    exportedAt: new Date().toISOString(),
    activeLevelId: allowed.has(collection.activeLevelId) ? collection.activeLevelId : null,
    levels,
  };
  const text = `${JSON.stringify(project, null, 2)}\n`;
  if (byteLength(text) > MAX_PROJECT_BYTES) throw new Error("This Maskwa Maze Lab project is too large to export.");
  return text;
}

export function prepareProjectImport(text, knownLevelIds) {
  if (typeof text !== "string" || !text.trim()) throw new Error("Choose a Maskwa Maze Lab project JSON file.");
  if (byteLength(text) > MAX_PROJECT_BYTES) throw new Error("The selected project is larger than 3 MB.");
  const parsed = parse(text);
  if (!isRecord(parsed)) throw new Error("The selected file is not valid JSON.");
  if (parsed.format !== PROJECT_FORMAT && parsed.format !== LEGACY_PROJECT_FORMAT) {
    throw new Error("This is not a Maskwa Maze Lab project file.");
  }
  if (parsed.schemaVersion !== PROJECT_SCHEMA_VERSION) {
    throw new Error("This Maskwa Maze Lab project version is not supported.");
  }
  if (parsed.headingSemantics !== HEADING_SEMANTICS) {
    throw new Error("This project uses incompatible absolute-heading robot commands.");
  }
  if (!isValidTimestamp(parsed.exportedAt)) throw new Error("The project export date is invalid.");
  if (!isRecord(parsed.levels)) throw new Error("The project does not contain level work.");

  const allowed = knownIds(knownLevelIds);
  const levelIds = Object.keys(parsed.levels);
  if (!levelIds.length) throw new Error("The project does not contain level work.");
  for (const levelId of levelIds) {
    if (!allowed.has(levelId)) throw new Error(`The project contains an unknown maze: ${levelId}.`);
  }
  if (parsed.activeLevelId !== null && parsed.activeLevelId !== undefined && !allowed.has(parsed.activeLevelId)) {
    throw new Error("The project's active maze is not available in this game.");
  }
  if (
    parsed.activeLevelId !== null &&
    parsed.activeLevelId !== undefined &&
    !Object.prototype.hasOwnProperty.call(parsed.levels, parsed.activeLevelId)
  ) {
    throw new Error("The project's active maze is missing from the project file.");
  }

  const levels = {};
  for (const levelId of levelIds) levels[levelId] = normalizeLevelRecord(parsed.levels[levelId], levelId, true);
  return {
    format: PROJECT_FORMAT,
    schemaVersion: PROJECT_SCHEMA_VERSION,
    headingSemantics: HEADING_SEMANTICS,
    exportedAt: new Date(parsed.exportedAt).toISOString(),
    activeLevelId: parsed.activeLevelId ?? null,
    levels,
  };
}

export function commitProjectImport(project, knownLevelIds, storage = localStorage) {
  const allowed = knownIds(knownLevelIds);
  if (
    !isRecord(project) ||
    project.format !== PROJECT_FORMAT ||
    project.schemaVersion !== PROJECT_SCHEMA_VERSION ||
    project.headingSemantics !== HEADING_SEMANTICS ||
    !isRecord(project.levels)
  ) {
    throw new Error("The prepared Maskwa Maze Lab project is invalid.");
  }
  const current = readCollection(storage);
  const importedActiveLevelId = (
    allowed.has(project.activeLevelId) &&
    Object.prototype.hasOwnProperty.call(project.levels, project.activeLevelId)
  ) ? project.activeLevelId : null;
  const staged = {
    schemaVersion: SCHEMA_VERSION,
    activeLevelId: importedActiveLevelId ?? (allowed.has(current.activeLevelId) ? current.activeLevelId : null),
    levels: { ...current.levels },
  };
  let preservedLocalVersions = 0;
  let importedAttempts = 0;

  for (const [levelId, imported] of Object.entries(project.levels)) {
    if (!allowed.has(levelId)) throw new Error(`The project contains an unknown maze: ${levelId}.`);
    const local = current.levels[levelId] ? normalizeLevelRecord(current.levels[levelId], levelId, false) : null;
    let mergedAttempts = mergeAttempts(local?.attempts, imported.attempts);
    let counter = Math.max(
      normalizeCounter(imported.attemptCounter, 0, imported.attempts),
      normalizeCounter(local?.attemptCounter, 0, local?.attempts),
    );
    if (counter >= MAX_ATTEMPT_NUMBER) {
      mergedAttempts = mergedAttempts.map((attempt, index) => ({ ...attempt, number: index + 1 }));
      counter = mergedAttempts.length;
    }
    if (local) {
      const preserved = createBeforeImportAttempt(local, levelId, counter + 1);
      if (preserved && !mergedAttempts.some((attempt) => attempt.id === preserved.id)) {
        mergedAttempts = appendPreservedAttempt(mergedAttempts, preserved);
        counter = Math.max(counter, preserved.number);
        preservedLocalVersions += 1;
      }
    }
    importedAttempts += imported.attempts.filter(
      (attempt) => !local?.attempts?.some((candidate) => candidate.id === attempt.id),
    ).length;
    staged.levels[levelId] = {
      ...imported,
      schemaVersion: SCHEMA_VERSION,
      savedAt: new Date().toISOString(),
      attempts: mergedAttempts,
      attemptCounter: Math.max(counter, ...mergedAttempts.map((attempt) => attempt.number)),
    };
  }

  const encoded = JSON.stringify(staged);
  if (byteLength(encoded) > MAX_STORED_BYTES) throw new Error("The imported work would exceed this browser's safe storage limit.");
  serializeProject(staged, new Set(Object.keys(staged.levels)));
  storage.setItem(STORAGE_KEY, encoded);
  return {
    levelCount: Object.keys(project.levels).length,
    importedAttempts,
    preservedLocalVersions,
  };
}

function readCollection(storage) {
  try {
    const current = parse(storage.getItem(STORAGE_KEY));
    if (current && current.schemaVersion === SCHEMA_VERSION && current.levels && typeof current.levels === "object") {
      return {
        schemaVersion: SCHEMA_VERSION,
        activeLevelId: typeof current.activeLevelId === "string" ? current.activeLevelId : null,
        levels: { ...current.levels },
      };
    }

    const previous = parse(storage.getItem(PREVIOUS_STORAGE_KEY));
    if (previous && previous.schemaVersion === 2 && typeof previous.levelId === "string") {
      return {
        schemaVersion: SCHEMA_VERSION,
        activeLevelId: previous.levelId,
        levels: { [previous.levelId]: previous },
      };
    }
  } catch {
    // Invalid or unavailable browser storage starts with a clean collection.
  }
  return { schemaVersion: SCHEMA_VERSION, activeLevelId: null, levels: {} };
}

function stageLevelState(collection, value) {
  if (!value?.levelId) throw new Error("A maze identifier is required.");
  const previous = collection.levels[value.levelId];
  collection.activeLevelId = value.levelId;
  collection.levels[value.levelId] = {
    ...(previous && typeof previous === "object" ? previous : {}),
    ...value,
    schemaVersion: SCHEMA_VERSION,
    savedAt: new Date().toISOString(),
    attempts: value.attempts === undefined
      ? normalizeAttemptHistory(previous?.attempts, { markRunningInterrupted: false })
      : normalizeAttemptHistory(value.attempts, { markRunningInterrupted: false }),
    attemptCounter: normalizeCounter(value.attemptCounter, previous?.attemptCounter, value.attempts ?? previous?.attempts),
  };
  return collection;
}

function normalizeLevelRecord(value, levelId, strict) {
  if (!isRecord(value)) throw new Error(`${levelId}: saved work is invalid.`);
  if (strict && value.schemaVersion !== SCHEMA_VERSION) throw new Error(`${levelId}: saved-work version is not supported.`);
  if (strict && value.levelId !== levelId) throw new Error(`${levelId}: level identifier does not match.`);
  const editorMode = value.editorMode === "python" ? "python" : "blocks";
  if (strict && value.editorMode !== "blocks" && value.editorMode !== "python") throw new Error(`${levelId}: editor mode is invalid.`);
  const pythonSource = typeof value.pythonSource === "string" ? value.pythonSource : "";
  if (pythonSource.length > MAX_CODE_CHARACTERS) throw new Error(`${levelId}: Python code exceeds 20,000 characters.`);
  const blocks = cloneBlocks(value.blocks, levelId);
  const attempts = normalizeImportedAttempts(value.attempts, levelId, strict);
  const robotPlaced = strict ? strictBoolean(value.robotPlaced, `${levelId}: robot placement is invalid.`) : Boolean(value.robotPlaced);
  const pythonDetached = strict ? strictBoolean(value.pythonDetached, `${levelId}: Python mode is invalid.`) : Boolean(value.pythonDetached);
  const robotStartPose = normalizePose(value.robotStartPose, strict, `${levelId}: starting position is invalid.`);
  if (strict && !isValidTimestamp(value.savedAt)) throw new Error(`${levelId}: save date is invalid.`);
  return {
    schemaVersion: SCHEMA_VERSION,
    savedAt: isValidTimestamp(value.savedAt) ? new Date(value.savedAt).toISOString() : new Date().toISOString(),
    levelId,
    editorMode,
    blocks,
    pythonSource,
    pythonDetached,
    robotPlaced,
    robotStartPose,
    attempts,
    attemptCounter: normalizeCounter(value.attemptCounter, 0, attempts, strict),
  };
}

function normalizeImportedAttempts(value, levelId, strict) {
  if (value === undefined && !strict) return [];
  if (!Array.isArray(value)) {
    if (strict) throw new Error(`${levelId}: attempt history is invalid.`);
    return [];
  }
  if (value.length > MAX_ATTEMPTS_PER_LEVEL) throw new Error(`${levelId}: attempt history exceeds ${MAX_ATTEMPTS_PER_LEVEL} entries.`);
  const attempts = [];
  const ids = new Set();
  for (const candidate of value) {
    const normalized = normalizeAttempt(candidate, strict, true);
    if (!normalized) continue;
    if (ids.has(normalized.id)) {
      if (strict) throw new Error(`${levelId}: attempt identifiers must be unique.`);
      continue;
    }
    ids.add(normalized.id);
    attempts.push(normalized);
  }
  attempts.sort(compareAttempts);
  return attempts;
}

function normalizeAttempt(value, strict, markRunningInterrupted) {
  const fail = (message) => {
    if (strict) throw new Error(message);
    return null;
  };
  if (!isRecord(value)) return fail("An attempt record is invalid.");
  if (typeof value.id !== "string" || !/^[a-z0-9._:-]{1,100}$/i.test(value.id)) return fail("An attempt identifier is invalid.");
  if (!Number.isInteger(value.number) || value.number < 1 || value.number > MAX_ATTEMPT_NUMBER) return fail("An attempt number is invalid.");
  if (!ATTEMPT_KINDS.has(value.kind)) return fail("An attempt kind is invalid.");
  if (!ATTEMPT_OUTCOMES.has(value.outcome)) return fail("An attempt result is invalid.");
  if (value.editorMode !== "blocks" && value.editorMode !== "python") return fail("An attempt editor mode is invalid.");
  if (typeof value.code !== "string" || value.code.length > MAX_CODE_CHARACTERS) return fail("Attempt code exceeds 20,000 characters.");
  if (!isValidTimestamp(value.startedAt)) return fail("An attempt start date is invalid.");
  if (value.finishedAt !== null && value.finishedAt !== undefined && !isValidTimestamp(value.finishedAt)) {
    return fail("An attempt finish date is invalid.");
  }
  const finishedAt = isValidTimestamp(value.finishedAt) ? new Date(value.finishedAt).toISOString() : null;
  if (value.kind === "save" && !SAVE_OUTCOMES.has(value.outcome)) return fail("A saved version has an invalid result.");
  if (value.kind === "run" && !RUN_OUTCOMES.has(value.outcome)) return fail("A run attempt has an invalid result.");
  if (value.outcome === "running" && finishedAt !== null) return fail("A running attempt cannot have a finish date.");
  if (value.kind === "save" && finishedAt === null) return fail("A saved version requires a finish date.");
  if (value.kind === "run" && !["running", "interrupted"].includes(value.outcome) && finishedAt === null) {
    return fail("A finished run requires a finish date.");
  }
  if (typeof value.message !== "string" || value.message.length > MAX_MESSAGE_CHARACTERS) return fail("An attempt note is invalid.");
  if (!Number.isInteger(value.impacts) || value.impacts < 0 || value.impacts > 1_000_000) return fail("An attempt impact count is invalid.");
  const outcome = markRunningInterrupted && value.outcome === "running" ? "interrupted" : value.outcome;
  return {
    id: value.id,
    number: value.number,
    kind: value.kind,
    startedAt: new Date(value.startedAt).toISOString(),
    finishedAt,
    editorMode: value.editorMode,
    code: value.code,
    outcome,
    message: value.message,
    impacts: value.impacts,
    startPose: normalizePose(value.startPose, strict, "An attempt starting position is invalid."),
    finalPose: normalizePose(value.finalPose, strict, "An attempt final position is invalid."),
  };
}

function createBeforeImportAttempt(local, levelId, number) {
  if (typeof local.pythonSource !== "string") return null;
  const now = new Date().toISOString();
  const fingerprint = hashText(`${levelId}\n${local.editorMode}\n${local.pythonSource}`);
  return {
    id: `before-import-${levelId}-${fingerprint}`,
    number,
    kind: "save",
    startedAt: now,
    finishedAt: now,
    editorMode: local.editorMode,
    code: local.pythonSource,
    outcome: "saved-before-import",
    message: "Local code preserved before import.",
    impacts: 0,
    startPose: local.robotStartPose,
    finalPose: null,
  };
}

function mergeAttempts(first, second) {
  const merged = new Map();
  for (const attempt of normalizeAttemptHistory(first)) merged.set(attempt.id, attempt);
  for (const attempt of normalizeAttemptHistory(second)) if (!merged.has(attempt.id)) merged.set(attempt.id, attempt);
  return [...merged.values()].sort(compareAttempts).slice(-MAX_ATTEMPTS_PER_LEVEL);
}

function appendPreservedAttempt(attempts, preserved) {
  const kept = attempts.filter((attempt) => attempt.id !== preserved.id);
  while (kept.length >= MAX_ATTEMPTS_PER_LEVEL) kept.shift();
  kept.push(preserved);
  return kept.sort(compareAttempts);
}

function normalizeCounter(value, fallback, attempts, strict = false) {
  if (strict && (!Number.isInteger(value) || value < 0 || value > MAX_ATTEMPT_NUMBER)) {
    throw new Error("An attempt counter is invalid.");
  }
  const candidate = Number.isInteger(value) && value >= 0 ? value : Number.isInteger(fallback) && fallback >= 0 ? fallback : 0;
  return Math.min(
    MAX_ATTEMPT_NUMBER,
    Math.max(candidate, ...(Array.isArray(attempts) ? attempts.map((attempt) => Number(attempt?.number) || 0) : [0])),
  );
}

function normalizePose(value, strict = false, message = "A saved position is invalid.") {
  if (value === null || value === undefined) return null;
  if (!isRecord(value) || typeof value.x !== "number" || typeof value.z !== "number" || !Number.isFinite(value.x) || !Number.isFinite(value.z)) {
    if (strict) throw new Error(message);
    return null;
  }
  const pose = { x: value.x, z: value.z };
  if (typeof value.heading === "number" && Number.isFinite(value.heading)) pose.heading = value.heading;
  return pose;
}

function cloneBlocks(value, levelId) {
  if (!isRecord(value)) throw new Error(`${levelId}: block workspace is invalid.`);
  let text;
  try { text = JSON.stringify(value); }
  catch { throw new Error(`${levelId}: block workspace is invalid.`); }
  if (byteLength(text) > MAX_BLOCKS_BYTES) throw new Error(`${levelId}: block workspace is too large.`);
  const cloned = parse(text);
  if (!isRecord(cloned)) throw new Error(`${levelId}: block workspace is invalid.`);
  return cloned;
}

function strictBoolean(value, message) {
  if (typeof value !== "boolean") throw new Error(message);
  return value;
}

function knownIds(value) {
  const ids = Array.isArray(value) ? value : [...(value || [])];
  if (!ids.length || ids.some((id) => typeof id !== "string" || !id)) throw new Error("Known maze identifiers are required.");
  return new Set(ids);
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isValidTimestamp(value) {
  return typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));
}

function compareAttempts(first, second) {
  return Date.parse(first.startedAt) - Date.parse(second.startedAt) || first.number - second.number || first.id.localeCompare(second.id);
}

function byteLength(value) {
  return new TextEncoder().encode(value).byteLength;
}

function hashText(value) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function parse(value) {
  if (typeof value !== "string" || !value) return null;
  try { return JSON.parse(value); }
  catch { return null; }
}
