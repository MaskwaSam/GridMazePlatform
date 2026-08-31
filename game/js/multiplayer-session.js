import {
  MAX_ROOM_PARTICIPANTS,
  MULTIPLAYER_PROTOCOL_VERSION,
  normalizeMultiplayerMessage,
} from "./multiplayer-protocol.js";

const SESSION_MODES = new Set(["offline", "connecting", "room"]);
const PARTICIPANT_ROLES = new Set(["student", "teacher", "observer"]);
const ROBOT_STATUSES = new Set(["ready", "running", "stopped", "solved"]);
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/;
const LEVEL_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

export function createMultiplayerSession({
  levelId,
  participantId,
  displayName = "Local student",
  robotId = "robot-local",
} = {}) {
  const participant = normalizeParticipant({ id: participantId, displayName, role: "student", connected: true });
  const normalizedRobotId = normalizedId(robotId, "robotId");
  const initialLevelId = normalizedLevelId(levelId);
  return freezeSession({
    protocolVersion: MULTIPLAYER_PROTOCOL_VERSION,
    mode: "offline",
    roomId: null,
    levelId: initialLevelId,
    authority: "local",
    localParticipantId: participant.id,
    participants: { [participant.id]: participant },
    robots: {
      [normalizedRobotId]: {
        id: normalizedRobotId,
        ownerParticipantId: participant.id,
        x: 0,
        z: 0,
        heading: 0,
        speed: 0,
        commandedSpeed: 0,
        collisions: 0,
        status: "ready",
        tick: 0,
      },
    },
    tick: 0,
    serverSequence: 0,
    needsSync: false,
    lastAction: null,
    lastError: null,
    lastPongAt: null,
  });
}

export function normalizeSessionSnapshot(value, { localParticipantId = null } = {}) {
  if (!isRecord(value)) throw new TypeError("Multiplayer session snapshot is invalid.");
  allowKeys(value, [
    "roomId", "levelId", "authority", "participants", "robots", "tick", "serverSequence",
  ]);
  const roomId = normalizedId(value.roomId, "roomId");
  const levelId = normalizedLevelId(value.levelId);
  const authority = value.authority === "server" ? "server" : normalizedId(value.authority, "authority");
  if (!Array.isArray(value.participants) || value.participants.length < 1 || value.participants.length > MAX_ROOM_PARTICIPANTS) {
    throw new TypeError("Multiplayer participant list is invalid.");
  }
  const participants = {};
  for (const candidate of value.participants) {
    const participant = normalizeParticipant(candidate);
    if (participants[participant.id]) throw new TypeError("Multiplayer participant ids must be unique.");
    participants[participant.id] = participant;
  }

  if (!Array.isArray(value.robots) || value.robots.length > MAX_ROOM_PARTICIPANTS) {
    throw new TypeError("Multiplayer robot list is invalid.");
  }
  const robots = {};
  for (const candidate of value.robots) {
    const robot = normalizeRobot(candidate);
    if (!participants[robot.ownerParticipantId]) throw new TypeError("Multiplayer robot owner is missing.");
    if (robots[robot.id]) throw new TypeError("Multiplayer robot ids must be unique.");
    robots[robot.id] = robot;
  }

  const normalizedLocalId = localParticipantId && participants[localParticipantId]
    ? localParticipantId
    : Object.keys(participants)[0];
  if (localParticipantId && !participants[localParticipantId]) {
    throw new TypeError("Multiplayer snapshot does not include the local participant.");
  }
  return freezeSession({
    protocolVersion: MULTIPLAYER_PROTOCOL_VERSION,
    mode: "room",
    roomId,
    levelId,
    authority,
    localParticipantId: normalizedLocalId,
    participants,
    robots,
    tick: normalizedSequence(value.tick, "tick"),
    serverSequence: normalizedSequence(value.serverSequence, "serverSequence"),
    needsSync: false,
    lastAction: null,
    lastError: null,
    lastPongAt: null,
  });
}

export function sessionSnapshot(session) {
  const current = normalizeSession(session);
  if (!current.roomId) throw new TypeError("Offline sessions do not have a room snapshot.");
  return Object.freeze({
    roomId: current.roomId,
    levelId: current.levelId,
    authority: current.authority,
    participants: Object.values(current.participants).map((participant) => ({ ...participant })),
    robots: Object.values(current.robots).map((robot) => ({ ...robot })),
    tick: current.tick,
    serverSequence: current.serverSequence,
  });
}

export function applySessionMessage(session, input) {
  const current = normalizeSession(session);
  const message = normalizeMultiplayerMessage(input, { direction: "server" });
  if (message.type === "room.snapshot") {
    const snapshot = normalizeSessionSnapshot(message.payload.snapshot, { localParticipantId: current.localParticipantId });
    if (message.roomId && snapshot.roomId !== message.roomId) throw new TypeError("Snapshot roomId does not match its envelope.");
    if (message.sequence !== snapshot.serverSequence) throw new TypeError("Snapshot sequence does not match its envelope.");
    return { session: snapshot, applied: true, duplicate: false, needsSync: false };
  }
  if (current.roomId && message.roomId && message.roomId !== current.roomId) {
    throw new TypeError("Multiplayer message belongs to a different room.");
  }
  if (message.sequence <= current.serverSequence) {
    return { session: current, applied: false, duplicate: true, needsSync: current.needsSync };
  }
  if (current.serverSequence > 0 && message.sequence !== current.serverSequence + 1) {
    return {
      session: freezeSession({ ...current, needsSync: true }),
      applied: false,
      duplicate: false,
      needsSync: true,
    };
  }

  const next = mutableSession(current);
  next.serverSequence = message.sequence;
  next.needsSync = false;
  if (message.roomId) next.roomId = message.roomId;

  switch (message.type) {
    case "welcome":
      next.mode = "connecting";
      next.authority = message.payload.authority;
      break;
    case "participant.joined":
      next.mode = "room";
      if (!next.participants[message.payload.participant.id]
        && Object.keys(next.participants).length >= MAX_ROOM_PARTICIPANTS) {
        throw new TypeError("Multiplayer room is at its participant limit.");
      }
      next.participants[message.payload.participant.id] = { ...message.payload.participant };
      break;
    case "participant.left":
      if (message.payload.participantId === next.localParticipantId) {
        return {
          session: setSessionConnectionState(freezeSession(next), "offline", { clearRoom: true }),
          applied: true,
          duplicate: false,
          needsSync: false,
        };
      }
      delete next.participants[message.payload.participantId];
      for (const [robotId, robot] of Object.entries(next.robots)) {
        if (robot.ownerParticipantId === message.payload.participantId) delete next.robots[robotId];
      }
      break;
    case "action.commit":
      next.mode = "room";
      next.tick = Math.max(next.tick, message.payload.tick);
      next.lastAction = { ...message.payload.action, payload: { ...message.payload.action.payload } };
      break;
    case "action.rejected":
      next.lastError = { code: "action-rejected", message: message.payload.reason, recoverable: true };
      break;
    case "robot.state":
      next.mode = "room";
      next.tick = Math.max(next.tick, message.payload.state.tick);
      if (!next.robots[message.payload.robotId] && !next.participants[message.participantId]) {
        throw new TypeError("Robot state owner is not a room participant.");
      }
      next.robots[message.payload.robotId] = normalizeRobot({
        id: message.payload.robotId,
        ownerParticipantId: next.robots[message.payload.robotId]?.ownerParticipantId || message.participantId,
        ...message.payload.state,
      });
      break;
    case "robot.result":
      break;
    case "pong":
      next.lastPongAt = message.sentAt;
      break;
    case "error":
      next.lastError = { ...message.payload };
      break;
    default:
      throw new TypeError(`Server message cannot update a session: ${message.type}`);
  }
  return { session: freezeSession(next), applied: true, duplicate: false, needsSync: false };
}

export function updateLocalRobotProjection(session, {
  robotId = "robot-local",
  telemetry,
  status = null,
  levelId = null,
} = {}) {
  const current = normalizeSession(session);
  if (!isRecord(telemetry)) throw new TypeError("Local robot telemetry is invalid.");
  const id = normalizedId(robotId, "robotId");
  const previous = current.robots[id] || {
    id,
    ownerParticipantId: current.localParticipantId,
    status: "ready",
    tick: current.tick,
  };
  const next = mutableSession(current);
  if (levelId !== null) next.levelId = normalizedLevelId(levelId);
  next.tick += 1;
  next.robots[id] = normalizeRobot({
    ...previous,
    x: telemetry.x,
    z: telemetry.z,
    heading: telemetry.heading,
    speed: telemetry.speed,
    commandedSpeed: telemetry.commandedSpeed,
    collisions: telemetry.collisions,
    status: status || inferRobotStatus(telemetry, previous.status),
    tick: next.tick,
  });
  return freezeSession(next);
}

export function setSessionConnectionState(session, state, {
  roomId = null,
  authority = null,
  clearRoom = false,
} = {}) {
  const current = normalizeSession(session);
  if (!SESSION_MODES.has(state)) throw new TypeError("Multiplayer session mode is invalid.");
  if (clearRoom) {
    if (state !== "offline") throw new TypeError("A cleared room must return to offline mode.");
    const localParticipant = current.participants[current.localParticipantId];
    const participants = localParticipant
      ? { [localParticipant.id]: { ...localParticipant, connected: true } }
      : {};
    const robots = Object.fromEntries(
      Object.entries(current.robots)
        .filter(([, robot]) => robot.ownerParticipantId === current.localParticipantId)
        .map(([id, robot]) => [id, { ...robot }]),
    );
    return freezeSession({
      ...current,
      mode: "offline",
      roomId: null,
      authority: "local",
      participants,
      robots,
      serverSequence: 0,
      needsSync: false,
      lastAction: null,
      lastError: null,
      lastPongAt: null,
    });
  }
  return freezeSession({
    ...current,
    mode: state,
    roomId: roomId === null ? current.roomId : normalizedId(roomId, "roomId"),
    authority: authority === null ? current.authority : (authority === "server" ? "server" : normalizedId(authority, "authority")),
  });
}

function normalizeSession(value) {
  if (!isRecord(value) || value.protocolVersion !== MULTIPLAYER_PROTOCOL_VERSION || !SESSION_MODES.has(value.mode)) {
    throw new TypeError("Multiplayer session is invalid.");
  }
  return value;
}

function normalizeParticipant(value) {
  if (!isRecord(value)) throw new TypeError("Participant is invalid.");
  allowKeys(value, ["id", "displayName", "role", "connected"]);
  if (!PARTICIPANT_ROLES.has(value.role)) throw new TypeError("Participant role is invalid.");
  return {
    id: normalizedId(value.id, "participantId"),
    displayName: normalizedText(value.displayName, 40, "displayName"),
    role: value.role,
    connected: Boolean(value.connected),
  };
}

function normalizeRobot(value) {
  if (!isRecord(value)) throw new TypeError("Robot is invalid.");
  allowKeys(value, [
    "id", "ownerParticipantId", "x", "z", "heading", "speed", "commandedSpeed", "collisions", "status", "tick",
  ]);
  if (!ROBOT_STATUSES.has(value.status)) throw new TypeError("Robot status is invalid.");
  return {
    id: normalizedId(value.id, "robotId"),
    ownerParticipantId: normalizedId(value.ownerParticipantId, "ownerParticipantId"),
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

function mutableSession(session) {
  return {
    ...session,
    participants: Object.fromEntries(Object.entries(session.participants).map(([id, value]) => [id, { ...value }])),
    robots: Object.fromEntries(Object.entries(session.robots).map(([id, value]) => [id, { ...value }])),
    lastAction: session.lastAction ? { ...session.lastAction, payload: { ...session.lastAction.payload } } : null,
    lastError: session.lastError ? { ...session.lastError } : null,
  };
}

function inferRobotStatus(telemetry, previous) {
  if (previous === "solved") return "solved";
  if (Math.abs(Number(telemetry.commandedSpeed) || 0) > 0 || Math.abs(Number(telemetry.speed) || 0) > 0) return "running";
  return previous === "running" ? "stopped" : "ready";
}

function normalizedId(value, label) {
  const text = String(value || "");
  if (!ID_PATTERN.test(text)) throw new TypeError(`${label} is invalid.`);
  return text;
}

function normalizedLevelId(value) {
  const text = String(value || "");
  if (!LEVEL_ID_PATTERN.test(text)) throw new TypeError("levelId is invalid.");
  return text;
}

function normalizedText(value, maxLength, label) {
  if (typeof value !== "string") throw new TypeError(`${label} is invalid.`);
  const text = value.trim();
  if (!text || text.length > maxLength || /[\u0000-\u001f]/.test(text)) throw new TypeError(`${label} is invalid.`);
  return text;
}

function normalizedSequence(value, label) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 0) throw new TypeError(`${label} is invalid.`);
  return number;
}

function finiteNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number) || Math.abs(number) > 1_000_000) throw new TypeError(`${label} is invalid.`);
  return number;
}

function allowKeys(value, allowed) {
  const set = new Set(allowed);
  for (const key of Object.keys(value)) {
    if (!set.has(key)) throw new TypeError(`Unknown ${key} field.`);
  }
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function freezeSession(value) {
  Object.freeze(value.participants);
  for (const participant of Object.values(value.participants)) Object.freeze(participant);
  Object.freeze(value.robots);
  for (const robot of Object.values(value.robots)) Object.freeze(robot);
  if (value.lastAction) {
    Object.freeze(value.lastAction.payload);
    Object.freeze(value.lastAction);
  }
  if (value.lastError) Object.freeze(value.lastError);
  return Object.freeze(value);
}
