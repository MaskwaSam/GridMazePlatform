import { isShareableGameAction, normalizeGameAction } from "./game-actions.js";

export const MULTIPLAYER_PROTOCOL = "maskwa-maze-multiplayer";
export const MULTIPLAYER_PROTOCOL_VERSION = 1;
export const MAX_MULTIPLAYER_MESSAGE_BYTES = 65_536;
export const MAX_ROOM_PARTICIPANTS = 64;

export const CLIENT_MESSAGE_TYPES = Object.freeze([
  "hello",
  "room.join",
  "room.leave",
  "action.intent",
  "robot.command",
  "state.ack",
  "sync.request",
  "ping",
]);

export const SERVER_MESSAGE_TYPES = Object.freeze([
  "welcome",
  "room.snapshot",
  "participant.joined",
  "participant.left",
  "action.commit",
  "action.rejected",
  "robot.state",
  "robot.result",
  "pong",
  "error",
]);

export const ROBOT_COMMANDS = Object.freeze([
  "roll",
  "spin",
  "wait",
  "set_heading",
  "set_speed",
  "stop_roll",
  "set_main_led",
  "set_matrix_pixel",
  "clear_matrix",
  "get_heading",
  "get_speed",
  "get_location_x",
  "get_location_y",
]);

const CLIENT_TYPES = new Set(CLIENT_MESSAGE_TYPES);
const SERVER_TYPES = new Set(SERVER_MESSAGE_TYPES);
const ALL_TYPES = new Set([...CLIENT_MESSAGE_TYPES, ...SERVER_MESSAGE_TYPES]);
const ROBOT_COMMAND_SET = new Set(ROBOT_COMMANDS);
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/;
const MESSAGE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9:._-]{2,127}$/;
const LEVEL_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
const MAX_SEQUENCE = Number.MAX_SAFE_INTEGER;
const ENVELOPE_KEYS = new Set([
  "protocol", "version", "type", "messageId", "roomId", "participantId", "sequence", "sentAt", "payload",
]);

export function createMultiplayerMessage(type, payload, {
  roomId = null,
  participantId,
  sequence,
  messageId,
  sentAt = Date.now(),
  direction = "client",
} = {}) {
  return normalizeMultiplayerMessage({
    protocol: MULTIPLAYER_PROTOCOL,
    version: MULTIPLAYER_PROTOCOL_VERSION,
    type,
    messageId,
    roomId,
    participantId,
    sequence,
    sentAt,
    payload,
  }, { direction });
}

export function normalizeMultiplayerMessage(value, { direction = "either" } = {}) {
  if (!isRecord(value)) throw new TypeError("Multiplayer message must be an object.");
  for (const key of Object.keys(value)) {
    if (!ENVELOPE_KEYS.has(key)) throw new TypeError(`Unknown multiplayer envelope field: ${key}`);
  }
  if (value.protocol !== MULTIPLAYER_PROTOCOL) throw new TypeError("Multiplayer protocol is not supported.");
  if (value.version !== MULTIPLAYER_PROTOCOL_VERSION) throw new TypeError("Multiplayer protocol version is not supported.");
  if (!ALL_TYPES.has(value.type)) throw new TypeError(`Unknown multiplayer message type: ${value.type}`);
  if (direction === "client" && !CLIENT_TYPES.has(value.type)) throw new TypeError("Expected a client multiplayer message.");
  if (direction === "server" && !SERVER_TYPES.has(value.type)) throw new TypeError("Expected a server multiplayer message.");
  if (direction !== "client" && direction !== "server" && direction !== "either") {
    throw new TypeError("Multiplayer message direction is invalid.");
  }

  const participantId = normalizedId(value.participantId, "participantId");
  const roomId = value.roomId === null ? null : normalizedId(value.roomId, "roomId");
  if (requiresRoom(value.type) && !roomId) throw new TypeError(`${value.type} requires a roomId.`);
  if (!MESSAGE_ID_PATTERN.test(String(value.messageId || ""))) throw new TypeError("Multiplayer messageId is invalid.");
  const sequence = normalizedSequence(value.sequence, "sequence");
  const sentAt = Number(value.sentAt);
  if (!Number.isSafeInteger(sentAt) || sentAt < 0) throw new TypeError("Multiplayer sentAt is invalid.");

  const message = {
    protocol: MULTIPLAYER_PROTOCOL,
    version: MULTIPLAYER_PROTOCOL_VERSION,
    type: value.type,
    messageId: String(value.messageId),
    roomId,
    participantId,
    sequence,
    sentAt,
    payload: normalizePayload(value.type, value.payload),
  };
  const encoded = JSON.stringify(message);
  if (byteLength(encoded) > MAX_MULTIPLAYER_MESSAGE_BYTES) throw new TypeError("Multiplayer message is too large.");
  return deepFreeze(message);
}

export function encodeMultiplayerMessage(value, options = {}) {
  return JSON.stringify(normalizeMultiplayerMessage(value, options));
}

export function decodeMultiplayerMessage(text, options = {}) {
  if (typeof text !== "string" || !text.trim()) throw new TypeError("Multiplayer message text is empty.");
  if (byteLength(text) > MAX_MULTIPLAYER_MESSAGE_BYTES) throw new TypeError("Multiplayer message is too large.");
  let parsed;
  try { parsed = JSON.parse(text); }
  catch { throw new TypeError("Multiplayer message is not valid JSON."); }
  return normalizeMultiplayerMessage(parsed, options);
}

export function normalizeRobotCommand(value) {
  if (!isRecord(value) || !ROBOT_COMMAND_SET.has(value.method) || !Array.isArray(value.args)) {
    throw new TypeError("Robot command is invalid.");
  }
  const method = value.method;
  const args = value.args.map((item) => normalizeCommandArgument(item));
  if (args.length > 4) throw new TypeError("Robot command has too many arguments.");
  validateCommandArguments(method, args);
  return deepFreeze({ method, args });
}

export function validateMultiplayerEndpoint(value, baseUrl = null, {
  allowedOrigins = [],
} = {}) {
  if (!Array.isArray(allowedOrigins)) throw new TypeError("Multiplayer allowedOrigins must be an array.");
  const rawValue = String(value ?? "").trim();
  if (!rawValue) throw new TypeError("Multiplayer WebSocket URL is invalid.");
  const hasExplicitScheme = /^[A-Za-z][A-Za-z0-9+.-]*:/.test(rawValue);
  let endpoint;
  try { endpoint = new URL(rawValue, baseUrl || undefined); }
  catch { throw new TypeError("Multiplayer WebSocket URL is invalid."); }
  if (!hasExplicitScheme && (endpoint.protocol === "https:" || endpoint.protocol === "http:")) {
    endpoint.protocol = endpoint.protocol === "https:" ? "wss:" : "ws:";
  }
  const localhost = endpoint.hostname === "localhost" || endpoint.hostname === "127.0.0.1" || endpoint.hostname === "[::1]" || endpoint.hostname === "::1";
  if (endpoint.protocol !== "wss:" && !(endpoint.protocol === "ws:" && localhost)) {
    throw new TypeError("Multiplayer requires wss, except for localhost development.");
  }
  if (endpoint.username || endpoint.password || endpoint.hash) throw new TypeError("Multiplayer URL must not contain credentials or a fragment.");

  const permittedOrigins = new Set();
  if (baseUrl !== null && baseUrl !== undefined && baseUrl !== "") {
    permittedOrigins.add(normalizeWebSocketOrigin(baseUrl, "Multiplayer base URL"));
  }
  for (const origin of allowedOrigins) {
    permittedOrigins.add(normalizeWebSocketOrigin(origin, "Multiplayer allowed origin"));
  }
  if (!permittedOrigins.size) {
    throw new TypeError("Multiplayer requires a same-origin base URL or an explicit WebSocket origin allowlist.");
  }
  if (!permittedOrigins.has(endpoint.origin)) {
    throw new TypeError("Multiplayer WebSocket origin is not allowed.");
  }
  return endpoint.toString();
}

function normalizePayload(type, value) {
  const payload = value === undefined ? {} : value;
  if (!isRecord(payload)) throw new TypeError(`${type} payload must be an object.`);
  switch (type) {
    case "hello":
      allowKeys(payload, ["lastServerEpoch", "lastServerSequence", "clientVersion"]);
      {
        const lastServerEpoch = normalizedOptionalId(payload.lastServerEpoch, "lastServerEpoch");
        const lastServerSequence = normalizedOptionalSequence(payload.lastServerSequence);
        if ((lastServerEpoch === null) !== (lastServerSequence === null)) {
          throw new TypeError("hello must provide lastServerEpoch and lastServerSequence together.");
        }
        return {
          lastServerEpoch,
          lastServerSequence,
          clientVersion: normalizedOptionalText(payload.clientVersion, 40),
        };
      }
    case "room.join":
      allowKeys(payload, ["levelId", "displayName"]);
      if (!LEVEL_ID_PATTERN.test(String(payload.levelId || ""))) throw new TypeError("room.join levelId is invalid.");
      return { levelId: String(payload.levelId), displayName: normalizedOptionalText(payload.displayName, 40) };
    case "room.leave":
      allowKeys(payload, ["reason"]);
      return { reason: normalizedOptionalText(payload.reason, 120) };
    case "action.intent":
    case "action.commit": {
      allowKeys(payload, type === "action.commit" ? ["action", "tick"] : ["action"]);
      const action = normalizeGameAction(payload.action);
      if (!isShareableGameAction(action)) throw new TypeError("This game action is device-local and cannot be shared.");
      if (type === "action.intent" && !["ui", "gamepad"].includes(action.source)) {
        throw new TypeError("Client action intents require a local input source.");
      }
      return type === "action.commit"
        ? { action, tick: normalizedSequence(payload.tick, "tick") }
        : { action };
    }
    case "robot.command":
      allowKeys(payload, ["robotId", "requestId", "command"]);
      return {
        robotId: normalizedId(payload.robotId, "robotId"),
        requestId: normalizedMessageId(payload.requestId, "requestId"),
        command: normalizeRobotCommand(payload.command),
      };
    case "state.ack":
    case "sync.request": {
      const key = type === "state.ack" ? "serverSequence" : "afterSequence";
      allowKeys(payload, [key]);
      return { [key]: normalizedSequence(payload[key], key) };
    }
    case "ping":
    case "pong":
      allowKeys(payload, ["nonce"]);
      return { nonce: normalizedText(payload.nonce, 64, "nonce") };
    case "welcome":
      allowKeys(payload, ["serverTime", "serverEpoch", "authority"]);
      return {
        serverTime: normalizedSequence(payload.serverTime, "serverTime"),
        serverEpoch: normalizedId(payload.serverEpoch, "serverEpoch"),
        authority: payload.authority === "server" ? "server" : normalizedId(payload.authority, "authority"),
      };
    case "room.snapshot":
      allowKeys(payload, ["snapshot"]);
      if (!isRecord(payload.snapshot)) throw new TypeError("room.snapshot requires a snapshot object.");
      return { snapshot: cloneJson(payload.snapshot) };
    case "participant.joined":
    case "participant.left":
      allowKeys(payload, type === "participant.joined" ? ["participant"] : ["participantId", "reason"]);
      return type === "participant.joined"
        ? { participant: normalizeParticipant(payload.participant) }
        : { participantId: normalizedId(payload.participantId, "participantId"), reason: normalizedOptionalText(payload.reason, 120) };
    case "action.rejected":
      allowKeys(payload, ["requestId", "reason"]);
      return { requestId: normalizedMessageId(payload.requestId, "requestId"), reason: normalizedText(payload.reason, 240, "reason") };
    case "robot.state":
      allowKeys(payload, ["robotId", "state"]);
      return { robotId: normalizedId(payload.robotId, "robotId"), state: normalizeRobotState(payload.state) };
    case "robot.result":
      allowKeys(payload, ["requestId", "result", "error"]);
      if (payload.result !== undefined && payload.result !== null
        && payload.error !== undefined && payload.error !== null && payload.error !== "") {
        throw new TypeError("robot.result cannot include both result and error.");
      }
      return {
        requestId: normalizedMessageId(payload.requestId, "requestId"),
        result: normalizeResultValue(payload.result),
        error: normalizedOptionalText(payload.error, 500),
      };
    case "error":
      allowKeys(payload, ["code", "message", "recoverable"]);
      return {
        code: normalizedText(payload.code, 40, "code"),
        message: normalizedText(payload.message, 500, "message"),
        recoverable: Boolean(payload.recoverable),
      };
    default:
      throw new TypeError(`Unknown multiplayer payload type: ${type}`);
  }
}

function normalizeParticipant(value) {
  if (!isRecord(value)) throw new TypeError("Participant is invalid.");
  allowKeys(value, ["id", "displayName", "role", "connected"]);
  if (!["student", "teacher", "observer"].includes(value.role)) throw new TypeError("Participant role is invalid.");
  return {
    id: normalizedId(value.id, "participant id"),
    displayName: normalizedText(value.displayName, 40, "displayName"),
    role: value.role,
    connected: Boolean(value.connected),
  };
}

function normalizeRobotState(value) {
  if (!isRecord(value)) throw new TypeError("Robot state is invalid.");
  allowKeys(value, ["x", "z", "heading", "speed", "commandedSpeed", "collisions", "status", "tick"]);
  if (!["ready", "running", "stopped", "solved"].includes(value.status)) throw new TypeError("Robot status is invalid.");
  return {
    x: finiteNumber(value.x, "x"),
    z: finiteNumber(value.z, "z"),
    heading: finiteNumber(value.heading, "heading"),
    speed: finiteNumber(value.speed, "speed"),
    commandedSpeed: finiteNumber(value.commandedSpeed, "commandedSpeed"),
    collisions: normalizedSequence(value.collisions, "collisions"),
    status: value.status,
    tick: normalizedSequence(value.tick, "tick"),
  };
}

function validateCommandArguments(method, args) {
  const count = (expected) => {
    if (args.length !== expected) throw new TypeError(`${method} expects ${expected} arguments.`);
  };
  const number = (index, min, max) => {
    const value = args[index];
    if (typeof value !== "number" || value < min || value > max) throw new TypeError(`${method} argument ${index + 1} is out of range.`);
  };
  switch (method) {
    case "roll": count(3); number(0, -3600, 3600); number(1, 0, 255); number(2, 0, 30); break;
    case "spin": count(2); number(0, -3600, 3600); number(1, 0, 30); break;
    case "wait": count(1); number(0, 0, 30); break;
    case "set_heading": count(1); number(0, -3600, 3600); break;
    case "set_speed": count(1); number(0, 0, 255); break;
    case "stop_roll":
    case "clear_matrix":
    case "get_heading":
    case "get_speed":
    case "get_location_x":
    case "get_location_y": count(0); break;
    case "set_main_led":
      if (args.length === 1 && typeof args[0] === "string" && /^#[0-9a-f]{6}$/i.test(args[0])) break;
      count(3); args.forEach((_, index) => number(index, 0, 255)); break;
    case "set_matrix_pixel":
      count(3); number(0, 0, 7); number(1, 0, 7);
      if (typeof args[2] !== "string" || !/^#[0-9a-f]{6}$/i.test(args[2])) throw new TypeError("set_matrix_pixel colour is invalid.");
      break;
    default: throw new TypeError(`Robot command is not supported: ${method}`);
  }
}

function normalizeCommandArgument(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.length <= 64 && !/[\u0000-\u001f]/.test(value)) return value;
  throw new TypeError("Robot command argument is invalid.");
}

function requiresRoom(type) {
  return !["hello", "welcome", "ping", "pong", "error"].includes(type);
}

function allowKeys(value, allowed) {
  const keys = new Set(allowed);
  for (const key of Object.keys(value)) {
    if (!keys.has(key)) throw new TypeError(`Unknown ${key} field in multiplayer payload.`);
  }
}

function normalizedId(value, label) {
  const text = String(value || "");
  if (!ID_PATTERN.test(text)) throw new TypeError(`${label} is invalid.`);
  return text;
}

function normalizedOptionalId(value, label) {
  return value === undefined || value === null || value === "" ? null : normalizedId(value, label);
}

function normalizedMessageId(value, label) {
  const text = String(value || "");
  if (!MESSAGE_ID_PATTERN.test(text)) throw new TypeError(`${label} is invalid.`);
  return text;
}

function normalizedSequence(value, label) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 0 || number > MAX_SEQUENCE) throw new TypeError(`${label} is invalid.`);
  return number;
}

function normalizedOptionalSequence(value) {
  return value === undefined || value === null ? null : normalizedSequence(value, "sequence");
}

function normalizedText(value, maxLength, label) {
  if (typeof value !== "string") throw new TypeError(`${label} is invalid.`);
  const text = value.trim();
  if (!text || text.length > maxLength || /[\u0000-\u001f]/.test(text)) throw new TypeError(`${label} is invalid.`);
  return text;
}

function normalizedOptionalText(value, maxLength) {
  return value === undefined || value === null || value === "" ? null : normalizedText(value, maxLength, "text");
}

function normalizeWebSocketOrigin(value, label) {
  let origin;
  try { origin = new URL(String(value)); }
  catch { throw new TypeError(`${label} is invalid.`); }
  if (origin.username || origin.password || origin.hash) throw new TypeError(`${label} must not contain credentials or a fragment.`);
  if (origin.protocol === "https:") origin.protocol = "wss:";
  else if (origin.protocol === "http:") origin.protocol = "ws:";
  else if (origin.protocol !== "wss:" && origin.protocol !== "ws:") throw new TypeError(`${label} must use HTTP(S) or WebSocket protocol.`);
  const localhost = origin.hostname === "localhost" || origin.hostname === "127.0.0.1" || origin.hostname === "[::1]" || origin.hostname === "::1";
  if (origin.protocol !== "wss:" && !(origin.protocol === "ws:" && localhost)) {
    throw new TypeError(`${label} requires wss, except for localhost development.`);
  }
  return origin.origin;
}

function finiteNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || Math.abs(number) > 1_000_000) throw new TypeError(`${label} is invalid.`);
  return number;
}

function normalizeResultValue(value) {
  if (value === undefined) return null;
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  throw new TypeError("robot.result value is invalid.");
}

function cloneJson(value) {
  try { return JSON.parse(JSON.stringify(value)); }
  catch { throw new TypeError("Multiplayer payload is not serializable."); }
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function byteLength(value) {
  return typeof TextEncoder === "function" ? new TextEncoder().encode(value).byteLength : value.length;
}

function deepFreeze(value) {
  if (!value || typeof value !== "object" || Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const nested of Object.values(value)) deepFreeze(nested);
  return value;
}
