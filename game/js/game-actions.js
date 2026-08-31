export const GAME_ACTION_KINDS = Object.freeze({
  PLACE_CENTER: "place-center",
  RUN: "run",
  STOP: "stop",
  RESET: "reset",
  RUN_AGAIN: "run-again",
  TOGGLE_EDITOR: "toggle-editor",
  OPEN_SETTINGS: "open-settings",
  OPEN_ATTEMPTS: "open-attempts",
  PREVIOUS_LEVEL: "previous-level",
  NEXT_LEVEL: "next-level",
  SELECT_LEVEL: "select-level",
});

export const GAME_ACTION_SOURCES = Object.freeze(["ui", "gamepad", "remote", "system"]);

const ACTION_KIND_SET = new Set(Object.values(GAME_ACTION_KINDS));
const ACTION_SOURCE_SET = new Set(GAME_ACTION_SOURCES);
const SHAREABLE_ACTION_SET = new Set([
  GAME_ACTION_KINDS.PLACE_CENTER,
  GAME_ACTION_KINDS.RUN,
  GAME_ACTION_KINDS.STOP,
  GAME_ACTION_KINDS.RESET,
  GAME_ACTION_KINDS.RUN_AGAIN,
  GAME_ACTION_KINDS.PREVIOUS_LEVEL,
  GAME_ACTION_KINDS.NEXT_LEVEL,
  GAME_ACTION_KINDS.SELECT_LEVEL,
]);
const LEVEL_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
const ACTION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9:._-]{0,95}$/;
const MAX_PAYLOAD_BYTES = 2_048;
let actionSequence = 0;

export function normalizeGameAction(value, {
  source = "ui",
  now = () => Date.now(),
  idFactory = defaultActionId,
} = {}) {
  const candidate = typeof value === "string" ? { kind: value } : value;
  if (!isRecord(candidate)) throw new TypeError("Game action must be an object or action kind.");
  if (!ACTION_KIND_SET.has(candidate.kind)) throw new TypeError(`Unknown game action: ${candidate.kind}`);

  const normalizedSource = candidate.source ?? source;
  if (!ACTION_SOURCE_SET.has(normalizedSource)) throw new TypeError(`Unknown game action source: ${normalizedSource}`);

  const payload = normalizePayload(candidate.kind, candidate.payload);
  const encodedPayload = JSON.stringify(payload);
  if (byteLength(encodedPayload) > MAX_PAYLOAD_BYTES) throw new TypeError("Game action payload is too large.");

  const createdAt = Number(candidate.createdAt ?? now());
  if (!Number.isFinite(createdAt) || createdAt < 0) throw new TypeError("Game action timestamp is invalid.");
  const id = String(candidate.id ?? idFactory());
  if (!ACTION_ID_PATTERN.test(id)) throw new TypeError("Game action id is invalid.");

  return Object.freeze({
    id,
    kind: candidate.kind,
    source: normalizedSource,
    createdAt,
    payload: Object.freeze(payload),
  });
}

export function isShareableGameAction(value) {
  try {
    return SHAREABLE_ACTION_SET.has(normalizeGameAction(value).kind);
  } catch {
    return false;
  }
}

export class GameActionRouter {
  constructor({ onError = null } = {}) {
    this.handlers = new Map();
    this.listeners = new Set();
    this.onError = typeof onError === "function" ? onError : null;
  }

  register(kind, handler) {
    if (!ACTION_KIND_SET.has(kind)) throw new TypeError(`Unknown game action: ${kind}`);
    if (typeof handler !== "function") throw new TypeError("Game action handler must be a function.");
    this.handlers.set(kind, handler);
    return () => this.handlers.delete(kind);
  }

  subscribe(listener) {
    if (typeof listener !== "function") throw new TypeError("Game action listener must be a function.");
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async dispatch(value, options = {}) {
    const action = normalizeGameAction(value, options);
    const handler = this.handlers.get(action.kind);
    if (!handler) throw new Error(`No handler is registered for game action: ${action.kind}`);
    let result;
    try {
      result = await handler(action);
    } catch (error) {
      this.onError?.(error, action);
      throw error;
    }
    if (result === false) return false;

    for (const listener of this.listeners) {
      try { listener(action); }
      catch (error) { this.onError?.(error, action); }
    }
    return result;
  }
}

function normalizePayload(kind, value) {
  const payload = value === undefined ? {} : value;
  if (!isRecord(payload)) throw new TypeError("Game action payload must be an object.");
  if (kind === GAME_ACTION_KINDS.SELECT_LEVEL) {
    const keys = Object.keys(payload);
    if (keys.length !== 1 || !LEVEL_ID_PATTERN.test(String(payload.levelId || ""))) {
      throw new TypeError("Select-level actions require one valid levelId.");
    }
    return { levelId: String(payload.levelId) };
  }
  if (Object.keys(payload).length) throw new TypeError(`${kind} does not accept a payload.`);
  return {};
}

function defaultActionId() {
  actionSequence = (actionSequence + 1) % Number.MAX_SAFE_INTEGER;
  return `action-${Date.now().toString(36)}-${actionSequence.toString(36)}`;
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function byteLength(value) {
  return typeof TextEncoder === "function" ? new TextEncoder().encode(value).byteLength : value.length;
}
