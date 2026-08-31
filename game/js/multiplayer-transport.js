import {
  MAX_ROOM_PARTICIPANTS,
  createMultiplayerMessage,
  decodeMultiplayerMessage,
  encodeMultiplayerMessage,
  normalizeMultiplayerMessage,
  validateMultiplayerEndpoint,
} from "./multiplayer-protocol.js";

export const MULTIPLAYER_TRANSPORT_STATES = Object.freeze({
  OFFLINE: "offline",
  IDLE: "idle",
  CONNECTING: "connecting",
  OPEN: "open",
  RECONNECTING: "reconnecting",
  CLOSED: "closed",
});

const LOOPBACK_SERVER_ID = "loopback-server";
const LOOPBACK_AUTHORITY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$/;

class TransportEvents {
  constructor() {
    this.listeners = new Set();
  }

  subscribe(listener) {
    if (typeof listener !== "function") throw new TypeError("Transport listener must be a function.");
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event) {
    const frozen = Object.freeze({ ...event });
    for (const listener of [...this.listeners]) {
      try { listener(frozen); }
      catch { /* A consumer cannot break transport delivery to other consumers. */ }
    }
  }

  clear() {
    this.listeners.clear();
  }
}

/**
 * The safe default transport. It has no endpoint, timers, socket constructor,
 * fetch call, or other network-capable dependency.
 */
export class OfflineTransport {
  constructor() {
    this.kind = "offline";
    this.state = MULTIPLAYER_TRANSPORT_STATES.OFFLINE;
    this.endpoint = null;
    this.networkAttempts = 0;
    this.events = new TransportEvents();
  }

  subscribe(listener) {
    return this.events.subscribe(listener);
  }

  connect() {
    return false;
  }

  send() {
    return false;
  }

  disconnect() {
    return false;
  }

  close() {
    return this.disconnect();
  }
}

/**
 * A synchronous, in-memory client transport. It deliberately round-trips all
 * traffic through the protocol encoder/decoder so tests exercise the same wire
 * boundary as WebSocket traffic.
 */
export class LoopbackTransport {
  constructor({ hub } = {}) {
    if (!(hub instanceof LoopbackHub)) throw new TypeError("LoopbackTransport requires a LoopbackHub.");
    this.kind = "loopback";
    this.state = MULTIPLAYER_TRANSPORT_STATES.IDLE;
    this.endpoint = null;
    this.networkAttempts = 0;
    this.hub = hub;
    this.events = new TransportEvents();
  }

  subscribe(listener) {
    return this.events.subscribe(listener);
  }

  connect() {
    if (this.state === MULTIPLAYER_TRANSPORT_STATES.OPEN) return true;
    this.hub._connect(this);
    this.state = MULTIPLAYER_TRANSPORT_STATES.OPEN;
    this.events.emit({ type: "open", transport: this.kind, reconnected: false });
    return true;
  }

  send(message) {
    const encoded = encodeMultiplayerMessage(message, { direction: "client" });
    if (this.state !== MULTIPLAYER_TRANSPORT_STATES.OPEN) return false;
    const decoded = decodeMultiplayerMessage(encoded, { direction: "client" });
    this.hub._receive(this, decoded);
    return true;
  }

  disconnect({ code = 1000, reason = "Loopback client disconnected." } = {}) {
    if (this.state === MULTIPLAYER_TRANSPORT_STATES.CLOSED || this.state === MULTIPLAYER_TRANSPORT_STATES.IDLE) {
      this.state = MULTIPLAYER_TRANSPORT_STATES.CLOSED;
      return false;
    }
    this.hub._disconnect(this, reason);
    this.state = MULTIPLAYER_TRANSPORT_STATES.CLOSED;
    this.events.emit({ type: "close", code, reason, clean: true, willReconnect: false });
    return true;
  }

  close(options = {}) {
    return this.disconnect(options);
  }

  _deliver(message) {
    if (this.state !== MULTIPLAYER_TRANSPORT_STATES.OPEN) return false;
    const encoded = encodeMultiplayerMessage(message, { direction: "server" });
    const decoded = decodeMultiplayerMessage(encoded, { direction: "server" });
    this.events.emit({ type: "message", message: decoded });
    return true;
  }
}

/**
 * A minimal deterministic room server for two-client and reconnect tests. It
 * models protocol sequencing, snapshots, participant presence, action commits,
 * and optional server-authority robot commands without opening a network port.
 */
export class LoopbackHub {
  constructor({
    authority = "local",
    serverEpoch = "loopback-epoch-1",
    now = () => Date.now(),
    executeRobotCommand = null,
  } = {}) {
    if (authority !== "server" && !LOOPBACK_AUTHORITY_PATTERN.test(String(authority))) {
      throw new TypeError("Loopback authority is invalid.");
    }
    if (executeRobotCommand !== null && typeof executeRobotCommand !== "function") {
      throw new TypeError("Loopback robot command executor must be a function.");
    }
    if (!LOOPBACK_AUTHORITY_PATTERN.test(String(serverEpoch))) {
      throw new TypeError("Loopback server epoch is invalid.");
    }
    this.authority = String(authority);
    this.serverEpoch = String(serverEpoch);
    this.now = now;
    this.executeRobotCommand = executeRobotCommand;
    this.connections = new Map();
    this.rooms = new Map();
    this.nextConnectionId = 1;
    this.pending = new Set();
  }

  createTransport() {
    return new LoopbackTransport({ hub: this });
  }

  get connectionCount() {
    return this.connections.size;
  }

  async flush() {
    while (this.pending.size) await Promise.allSettled([...this.pending]);
  }

  /** Deliver a strict server message, optionally with a deliberate sequence. */
  sendServerMessage(transport, type, payload, {
    roomId,
    participantId = LOOPBACK_SERVER_ID,
    sequence = null,
  } = {}) {
    const connection = this._connection(transport);
    const nextSequence = sequence === null ? connection.serverSequence + 1 : sequence;
    const resolvedRoomId = roomId === undefined ? connection.roomId : roomId;
    const message = createMultiplayerMessage(type, payload, {
      roomId: resolvedRoomId ?? null,
      participantId,
      sequence: nextSequence,
      messageId: `server:${connection.id}:${nextSequence}`,
      sentAt: safeNow(this.now),
      direction: "server",
    });
    connection.serverSequence = Math.max(connection.serverSequence, nextSequence);
    transport._deliver(message);
    return message;
  }

  _connect(transport) {
    if (this.connections.has(transport)) return this.connections.get(transport);
    const id = `loopback-${this.nextConnectionId++}`;
    const connection = {
      id,
      participantId: null,
      displayName: null,
      roomId: null,
      roomEpoch: 0,
      levelId: null,
      clientSequence: 0,
      serverSequence: 0,
      messageIds: new Set(),
    };
    this.connections.set(transport, connection);
    return connection;
  }

  _disconnect(transport, reason) {
    const connection = this.connections.get(transport);
    if (!connection) return;
    const room = connection.roomId ? this.rooms.get(connection.roomId) : null;
    if (room) {
      room.members.delete(transport);
      for (const [robotId, robot] of room.robots) {
        if (robot.ownerParticipantId === connection.participantId) room.robots.delete(robotId);
      }
      for (const peer of room.members) {
        this.sendServerMessage(peer, "participant.left", {
          participantId: connection.participantId,
          reason: cleanText(reason, 120),
        }, { roomId: room.id, participantId: connection.participantId });
      }
      if (!room.members.size) this.rooms.delete(room.id);
    }
    this.connections.delete(transport);
  }

  _receive(transport, input) {
    const message = normalizeMultiplayerMessage(input, { direction: "client" });
    const connection = this._connection(transport);
    if (connection.messageIds.has(message.messageId) || message.sequence <= connection.clientSequence) return;
    if (message.sequence !== connection.clientSequence + 1) {
      this._sendError(transport, "client-sequence-gap", "Client message sequence is not contiguous.", true);
      return;
    }
    if (connection.participantId && connection.participantId !== message.participantId) {
      this._sendError(transport, "participant-mismatch", "Client participant id changed during a connection.", false);
      return;
    }
    connection.participantId = message.participantId;
    connection.clientSequence = message.sequence;
    connection.messageIds.add(message.messageId);
    if (connection.messageIds.size > 2_048) connection.messageIds.delete(connection.messageIds.values().next().value);

    switch (message.type) {
      case "hello":
        this.sendServerMessage(transport, "welcome", {
          serverTime: safeNow(this.now),
          serverEpoch: this.serverEpoch,
          authority: this.authority,
        }, { roomId: null });
        break;
      case "room.join":
        this._joinRoom(transport, message);
        break;
      case "room.leave":
        this._leaveRoom(transport, message.payload.reason || "Participant left the room.");
        break;
      case "action.intent":
        this._commitAction(transport, message);
        break;
      case "robot.command":
        this._runRobotCommand(transport, message);
        break;
      case "state.ack":
        break;
      case "sync.request":
        this._sendSnapshot(transport);
        break;
      case "ping":
        this.sendServerMessage(transport, "pong", { nonce: message.payload.nonce }, { roomId: null });
        break;
      default:
        this._sendError(transport, "unsupported-message", `Loopback does not handle ${message.type}.`, false);
    }
  }

  _joinRoom(transport, message) {
    const connection = this._connection(transport);
    if (connection.roomId && connection.roomId !== message.roomId) this._leaveRoom(transport, "Joined another room.");
    let room = this.rooms.get(message.roomId);
    if (room && room.levelId !== message.payload.levelId) {
      this._sendError(transport, "level-mismatch", "Room participants must use the same maze.", true);
      return;
    }
    if (!room) {
      room = {
        id: message.roomId,
        levelId: message.payload.levelId,
        members: new Set(),
        robots: new Map(),
        tick: 0,
      };
      this.rooms.set(room.id, room);
    }
    if (room.members.has(transport)) {
      this._sendSnapshot(transport);
      return;
    }
    if (room.members.size >= MAX_ROOM_PARTICIPANTS) {
      this._sendError(transport, "room-full", "The multiplayer room is full.", true);
      return;
    }
    for (const member of room.members) {
      if (this._connection(member).participantId === connection.participantId) {
        this._sendError(transport, "participant-conflict", "Participant id is already present in this room.", true);
        return;
      }
    }
    connection.roomId = room.id;
    connection.roomEpoch += 1;
    connection.levelId = room.levelId;
    connection.displayName = message.payload.displayName || connection.participantId;
    const existingMembers = [...room.members];
    room.members.add(transport);

    const participant = this._participant(connection);
    for (const peer of existingMembers) {
      this.sendServerMessage(peer, "participant.joined", { participant }, {
        roomId: room.id,
        participantId: connection.participantId,
      });
    }
    this._sendSnapshot(transport);
  }

  _leaveRoom(transport, reason) {
    const connection = this._connection(transport);
    const room = connection.roomId ? this.rooms.get(connection.roomId) : null;
    if (!room) return;
    room.members.delete(transport);
    for (const [robotId, robot] of room.robots) {
      if (robot.ownerParticipantId === connection.participantId) room.robots.delete(robotId);
    }
    connection.roomId = null;
    connection.roomEpoch += 1;
    connection.levelId = null;
    for (const peer of room.members) {
      this.sendServerMessage(peer, "participant.left", {
        participantId: connection.participantId,
        reason: cleanText(reason, 120),
      }, { roomId: room.id, participantId: connection.participantId });
    }
    if (!room.members.size) this.rooms.delete(room.id);
  }

  _commitAction(transport, message) {
    const connection = this._requireRoomMember(transport, message.roomId);
    if (!connection) return;
    const room = this.rooms.get(connection.roomId);
    room.tick += 1;
    for (const peer of room.members) {
      this.sendServerMessage(peer, "action.commit", {
        action: message.payload.action,
        tick: room.tick,
      }, { roomId: room.id, participantId: connection.participantId });
    }
  }

  _runRobotCommand(transport, message) {
    const connection = this._requireRoomMember(transport, message.roomId);
    if (!connection) return;
    if (this.authority !== "server" || !this.executeRobotCommand) {
      this.sendServerMessage(transport, "robot.result", {
        requestId: message.payload.requestId,
        error: "Server command authority is unavailable.",
      }, { roomId: connection.roomId });
      return;
    }

    const commandRoomId = connection.roomId;
    const commandRoomEpoch = connection.roomEpoch;
    const commandStillBelongsToRoom = () => {
      const current = this.connections.get(transport);
      return Boolean(current)
        && current.roomId === commandRoomId
        && current.roomEpoch === commandRoomEpoch;
    };

    const task = Promise.resolve().then(() => this.executeRobotCommand(
      message.payload.command.method,
      [...message.payload.command.args],
      {
        participantId: connection.participantId,
        roomId: commandRoomId,
        robotId: message.payload.robotId,
        requestId: message.payload.requestId,
      },
    )).then((result) => {
      if (!commandStillBelongsToRoom()) return;
      this.sendServerMessage(transport, "robot.result", {
        requestId: message.payload.requestId,
        result,
      }, { roomId: commandRoomId });
    }).catch((error) => {
      if (!commandStillBelongsToRoom()) return;
      this.sendServerMessage(transport, "robot.result", {
        requestId: message.payload.requestId,
        error: cleanText(error?.message || error, 500),
      }, { roomId: commandRoomId });
    });
    this.pending.add(task);
    task.finally(() => this.pending.delete(task));
  }

  _sendSnapshot(transport) {
    const connection = this._connection(transport);
    const room = connection.roomId ? this.rooms.get(connection.roomId) : null;
    if (!room) {
      this._sendError(transport, "not-in-room", "Join a room before requesting a snapshot.", true);
      return;
    }
    const serverSequence = connection.serverSequence + 1;
    const snapshot = {
      roomId: room.id,
      levelId: room.levelId,
      authority: this.authority,
      participants: [...room.members].map((member) => this._participant(this._connection(member))),
      robots: [...room.robots.values()].map((robot) => ({ ...robot })),
      tick: room.tick,
      serverSequence,
    };
    this.sendServerMessage(transport, "room.snapshot", { snapshot }, {
      roomId: room.id,
      sequence: serverSequence,
    });
  }

  _sendError(transport, code, message, recoverable) {
    this.sendServerMessage(transport, "error", {
      code,
      message: cleanText(message, 500),
      recoverable,
    }, { roomId: null });
  }

  _requireRoomMember(transport, roomId) {
    const connection = this._connection(transport);
    const room = connection.roomId ? this.rooms.get(connection.roomId) : null;
    if (!room || room.id !== roomId || !room.members.has(transport)) {
      this._sendError(transport, "not-in-room", "Join the requested room first.", true);
      return null;
    }
    return connection;
  }

  _participant(connection) {
    return {
      id: connection.participantId,
      displayName: connection.displayName || connection.participantId,
      role: "student",
      connected: true,
    };
  }

  _connection(transport) {
    const connection = this.connections.get(transport);
    if (!connection) throw new Error("Loopback transport is not connected.");
    return connection;
  }
}

/**
 * Browser WebSocket transport. Construction is inert; only connect(endpoint)
 * validates an endpoint and constructs a socket. Messages sent while not open
 * are rejected and never queued or replayed.
 */
export class WebSocketTransport {
  constructor({
    WebSocketImpl = null,
    baseUrl = defaultBrowserBaseUrl(),
    allowedOrigins = [],
    maxReconnectAttempts = 3,
    reconnectBaseDelayMs = 250,
    reconnectMaxDelayMs = 4_000,
    setTimeoutFn = globalThis.setTimeout?.bind(globalThis),
    clearTimeoutFn = globalThis.clearTimeout?.bind(globalThis),
  } = {}) {
    if (!Number.isSafeInteger(maxReconnectAttempts) || maxReconnectAttempts < 0 || maxReconnectAttempts > 10) {
      throw new TypeError("WebSocket reconnect attempt limit is invalid.");
    }
    if (!Number.isFinite(reconnectBaseDelayMs) || reconnectBaseDelayMs < 0 || reconnectBaseDelayMs > 60_000) {
      throw new TypeError("WebSocket reconnect delay is invalid.");
    }
    if (!Number.isFinite(reconnectMaxDelayMs) || reconnectMaxDelayMs < reconnectBaseDelayMs || reconnectMaxDelayMs > 300_000) {
      throw new TypeError("WebSocket maximum reconnect delay is invalid.");
    }
    if (typeof setTimeoutFn !== "function" || typeof clearTimeoutFn !== "function") {
      throw new TypeError("WebSocket transport requires timer functions.");
    }
    if (!Array.isArray(allowedOrigins)) throw new TypeError("WebSocket allowedOrigins must be an array.");
    this.kind = "websocket";
    this.state = MULTIPLAYER_TRANSPORT_STATES.IDLE;
    this.endpoint = null;
    this.networkAttempts = 0;
    this.events = new TransportEvents();
    this.WebSocketImpl = WebSocketImpl;
    this.baseUrl = baseUrl;
    this.allowedOrigins = [...allowedOrigins];
    this.maxReconnectAttempts = maxReconnectAttempts;
    this.reconnectBaseDelayMs = reconnectBaseDelayMs;
    this.reconnectMaxDelayMs = reconnectMaxDelayMs;
    this.setTimeoutFn = setTimeoutFn;
    this.clearTimeoutFn = clearTimeoutFn;
    this.socket = null;
    this.generation = 0;
    this.reconnectAttempts = 0;
    this.reconnectTimer = null;
    this.manualClose = false;
    this.fatalGeneration = null;
  }

  subscribe(listener) {
    return this.events.subscribe(listener);
  }

  connect(endpoint) {
    // An explicit replacement owns any pending reconnect attempt. Cancel it
    // before validation so an invalid replacement cannot later reopen the old
    // endpoint behind the caller's newly cleared session state.
    this._cancelReconnect();
    const validatedEndpoint = validateMultiplayerEndpoint(endpoint, this.baseUrl, {
      allowedOrigins: this.allowedOrigins,
    });
    const WebSocketConstructor = this.WebSocketImpl || globalThis.WebSocket;
    if (typeof WebSocketConstructor !== "function") throw new Error("WebSocket is unavailable in this environment.");

    this.manualClose = false;
    this.reconnectAttempts = 0;
    this.endpoint = validatedEndpoint;
    this.generation += 1;
    const previous = this.socket;
    this.socket = null;
    if (previous && previous.readyState < 2) {
      try { previous.close(1000, "Replaced by an explicit connection."); }
      catch { /* The new explicit connection still proceeds. */ }
    }
    this._openSocket(false);
    return true;
  }

  send(message) {
    const encoded = encodeMultiplayerMessage(message, { direction: "client" });
    const socket = this.socket;
    const WebSocketConstructor = this.WebSocketImpl || globalThis.WebSocket;
    const openState = WebSocketConstructor?.OPEN ?? 1;
    if (!socket || this.state !== MULTIPLAYER_TRANSPORT_STATES.OPEN || socket.readyState !== openState) return false;
    try {
      socket.send(encoded);
      return true;
    } catch (error) {
      this.events.emit({ type: "error", error: asError(error), fatal: false });
      return false;
    }
  }

  disconnect({ code = 1000, reason = "Client disconnected." } = {}) {
    this.manualClose = true;
    this._cancelReconnect();
    this.generation += 1;
    const socket = this.socket;
    this.socket = null;
    this.state = MULTIPLAYER_TRANSPORT_STATES.CLOSED;
    if (socket && socket.readyState < 2) {
      try { socket.close(code, cleanText(reason, 120)); }
      catch (error) { this.events.emit({ type: "error", error: asError(error), fatal: false }); }
    }
    this.events.emit({ type: "close", code, reason, clean: true, willReconnect: false, manual: true });
    return Boolean(socket);
  }

  close(options = {}) {
    return this.disconnect(options);
  }

  _openSocket(reconnected) {
    if (this.manualClose || !this.endpoint) return;
    const WebSocketConstructor = this.WebSocketImpl || globalThis.WebSocket;
    const generation = ++this.generation;
    this.state = reconnected
      ? MULTIPLAYER_TRANSPORT_STATES.RECONNECTING
      : MULTIPLAYER_TRANSPORT_STATES.CONNECTING;
    this.networkAttempts += 1;
    let socket;
    try {
      socket = new WebSocketConstructor(this.endpoint);
    } catch (error) {
      this.events.emit({ type: "error", error: asError(error), fatal: false });
      this._scheduleReconnect(generation, { code: 1006, reason: "WebSocket construction failed.", wasClean: false });
      return;
    }
    this.socket = socket;

    socket.addEventListener("open", () => {
      if (generation !== this.generation || socket !== this.socket) return;
      this.reconnectAttempts = 0;
      this.state = MULTIPLAYER_TRANSPORT_STATES.OPEN;
      this.events.emit({ type: "open", transport: this.kind, reconnected });
    });
    socket.addEventListener("message", (event) => {
      if (generation !== this.generation || socket !== this.socket) return;
      try {
        if (typeof event.data !== "string") throw new TypeError("WebSocket multiplayer messages must be UTF-8 text.");
        const message = decodeMultiplayerMessage(event.data, { direction: "server" });
        this.events.emit({ type: "message", message });
      } catch (error) {
        this.fatalGeneration = generation;
        this.events.emit({ type: "error", error: asError(error), fatal: true });
        try { socket.close(1002, "Invalid multiplayer message."); }
        catch { this.state = MULTIPLAYER_TRANSPORT_STATES.CLOSED; }
      }
    });
    socket.addEventListener("error", () => {
      if (generation !== this.generation || socket !== this.socket) return;
      this.events.emit({ type: "error", error: new Error("WebSocket transport error."), fatal: false });
    });
    socket.addEventListener("close", (event) => {
      if (generation !== this.generation || socket !== this.socket) return;
      this.socket = null;
      if (this.manualClose || this.fatalGeneration === generation) {
        this.state = MULTIPLAYER_TRANSPORT_STATES.CLOSED;
        this.events.emit({
          type: "close",
          code: event.code,
          reason: event.reason,
          clean: Boolean(event.wasClean),
          willReconnect: false,
        });
        return;
      }
      this._scheduleReconnect(generation, event);
    });
  }

  _scheduleReconnect(generation, closeEvent) {
    if (generation !== this.generation || this.manualClose) return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.state = MULTIPLAYER_TRANSPORT_STATES.CLOSED;
      this.events.emit({
        type: "close",
        code: closeEvent.code ?? 1006,
        reason: closeEvent.reason || "Reconnect limit reached.",
        clean: Boolean(closeEvent.wasClean),
        willReconnect: false,
      });
      return;
    }
    this.reconnectAttempts += 1;
    const delayMs = Math.min(
      this.reconnectMaxDelayMs,
      this.reconnectBaseDelayMs * (2 ** (this.reconnectAttempts - 1)),
    );
    this.state = MULTIPLAYER_TRANSPORT_STATES.RECONNECTING;
    this.events.emit({
      type: "close",
      code: closeEvent.code ?? 1006,
      reason: closeEvent.reason || "Connection lost.",
      clean: Boolean(closeEvent.wasClean),
      willReconnect: true,
      reconnectAttempt: this.reconnectAttempts,
      delayMs,
    });
    this.reconnectTimer = this.setTimeoutFn(() => {
      this.reconnectTimer = null;
      if (generation !== this.generation || this.manualClose) return;
      this._openSocket(true);
    }, delayMs);
  }

  _cancelReconnect() {
    if (this.reconnectTimer !== null) this.clearTimeoutFn(this.reconnectTimer);
    this.reconnectTimer = null;
  }
}

function cleanText(value, maxLength) {
  const text = String(value ?? "").replace(/[\u0000-\u001f]/g, " ").trim();
  return (text || "Unknown multiplayer error.").slice(0, maxLength);
}

function safeNow(now) {
  const value = Number(now());
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError("Multiplayer clock must return a non-negative safe integer.");
  return value;
}

function asError(value) {
  return value instanceof Error ? value : new Error(String(value || "Unknown multiplayer error."));
}

function defaultBrowserBaseUrl() {
  return typeof globalThis.location?.href === "string" ? globalThis.location.href : null;
}
