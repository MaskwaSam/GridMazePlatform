import {
  isShareableGameAction,
  normalizeGameAction,
} from "./game-actions.js";
import {
  ROBOT_COMMANDS,
  createMultiplayerMessage,
  normalizeMultiplayerMessage,
  normalizeRobotCommand,
} from "./multiplayer-protocol.js";
import {
  applySessionMessage,
  createMultiplayerSession,
  setSessionConnectionState,
  updateLocalRobotProjection,
} from "./multiplayer-session.js";
import {
  MULTIPLAYER_TRANSPORT_STATES,
  OfflineTransport,
} from "./multiplayer-transport.js";

export const MULTIPLAYER_COMMAND_AUTHORITIES = Object.freeze({
  LOCAL: "local",
  SERVER: "server",
});

/** Exact application-state fields that are never valid multiplayer payloads. */
export const MULTIPLAYER_PRIVATE_FIELDS = Object.freeze([
  "attemptHistory",
  "attempts",
  "blocks",
  "code",
  "editorMode",
  "project",
  "pythonSource",
  "savedState",
  "settings",
  "userSettings",
  "workspace",
]);

const PRIVATE_FIELD_KEYS = new Set(MULTIPLAYER_PRIVATE_FIELDS.map(normalizedFieldKey));
const LOCAL_ROBOT_COMMANDS = new Set(ROBOT_COMMANDS);
const MAX_SEEN_SERVER_MESSAGES = 1_024;

export function assertMultiplayerPrivacyBoundary(value) {
  const visited = new WeakSet();
  const inspect = (candidate) => {
    if (!candidate || typeof candidate !== "object") return;
    if (visited.has(candidate)) return;
    visited.add(candidate);
    for (const [key, nested] of Object.entries(candidate)) {
      if (PRIVATE_FIELD_KEYS.has(normalizedFieldKey(key))) {
        throw new TypeError(`Private field cannot cross the multiplayer boundary: ${key}`);
      }
      inspect(nested);
    }
  };
  inspect(value);
  return true;
}

class ClientEvents {
  constructor() {
    this.listeners = new Set();
  }

  subscribe(listener) {
    if (typeof listener !== "function") throw new TypeError("Multiplayer client listener must be a function.");
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit(event) {
    const frozen = Object.freeze({ ...event });
    for (const listener of [...this.listeners]) {
      try { listener(frozen); }
      catch { /* Client observers are isolated from protocol state. */ }
    }
  }

  clear() {
    this.listeners.clear();
  }
}

export class MultiplayerClient {
  constructor({
    levelId,
    participantId,
    displayName = "Local student",
    robotId = "robot-local",
    transport = new OfflineTransport(),
    commandAuthority = MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL,
    executeLocalCommand = null,
    onRemoteAction = null,
    onSessionChange = null,
    onError = null,
    now = () => Date.now(),
    messageIdFactory = defaultMessageId,
    actionIdFactory = defaultActionId,
    commandTimeoutMs = 15_000,
    setTimeoutFn = globalThis.setTimeout?.bind(globalThis),
    clearTimeoutFn = globalThis.clearTimeout?.bind(globalThis),
    clientVersion = null,
  } = {}) {
    validateTransport(transport);
    validateAuthority(commandAuthority);
    if (commandAuthority !== MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL) {
      throw new TypeError("Multiplayer clients begin with local command authority; server authority requires a validated room snapshot.");
    }
    validateOptionalFunction(executeLocalCommand, "Local command executor");
    validateOptionalFunction(onRemoteAction, "Remote action callback");
    validateOptionalFunction(onSessionChange, "Session callback");
    validateOptionalFunction(onError, "Error callback");
    if (typeof now !== "function" || typeof messageIdFactory !== "function" || typeof actionIdFactory !== "function") {
      throw new TypeError("Multiplayer client clocks and id factories must be functions.");
    }
    if (!Number.isFinite(commandTimeoutMs) || commandTimeoutMs < 1 || commandTimeoutMs > 120_000) {
      throw new TypeError("Multiplayer command timeout is invalid.");
    }
    if (typeof setTimeoutFn !== "function" || typeof clearTimeoutFn !== "function") {
      throw new TypeError("Multiplayer client requires timer functions.");
    }
    if (clientVersion !== null && (typeof clientVersion !== "string" || !clientVersion.trim() || clientVersion.length > 40)) {
      throw new TypeError("Multiplayer client version is invalid.");
    }

    const initialSession = createMultiplayerSession({ levelId, participantId, displayName, robotId });
    this.transport = transport;
    this.participantId = initialSession.localParticipantId;
    this.displayName = initialSession.participants[initialSession.localParticipantId].displayName;
    this.robotId = Object.values(initialSession.robots)
      .find(({ ownerParticipantId }) => ownerParticipantId === initialSession.localParticipantId)?.id || String(robotId);
    this.commandAuthority = commandAuthority;
    this.executeLocalCommand = executeLocalCommand;
    this.onRemoteAction = onRemoteAction;
    this.onSessionChange = onSessionChange;
    this.onError = onError;
    this.now = now;
    this.messageIdFactory = messageIdFactory;
    this.actionIdFactory = actionIdFactory;
    this.commandTimeoutMs = commandTimeoutMs;
    this.setTimeoutFn = setTimeoutFn;
    this.clearTimeoutFn = clearTimeoutFn;
    this.clientVersion = clientVersion === null ? null : clientVersion.trim();
    this.events = new ClientEvents();
    this.connectionSequence = 0;
    this.clientSequence = 0;
    this.actionSequence = 0;
    this.commandSequence = 0;
    this.pendingCommands = new Map();
    this.seenServerMessageIds = new Set();
    this.seenServerMessageOrder = [];
    this.syncRequestedAfter = null;
    this.serverEpoch = null;
    this.awaitingWelcome = false;
    this.rejoinRoomId = null;
    this.rejoinAfterWelcome = null;
    this.destroyed = false;
    this._session = initialSession;
    this.unsubscribeTransport = this.transport.subscribe((event) => this._handleTransportEvent(event));
  }

  get session() {
    return this._session;
  }

  get isConnected() {
    return this.transport.state === MULTIPLAYER_TRANSPORT_STATES.OPEN;
  }

  subscribe(listener) {
    this._assertActive();
    return this.events.subscribe(listener);
  }

  connect(endpoint) {
    this._assertActive();
    if (this.transport instanceof OfflineTransport || this.transport.kind === "offline") return false;
    if (this.isConnected && (this.transport.kind !== "websocket"
      || String(endpoint ?? "").trim() === this.transport.endpoint)) return true;
    this._rejectPendingCommands(new Error("A new multiplayer connection replaced the previous server context."));
    this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
    this._resetServerScope();
    this.rejoinRoomId = null;
    this.rejoinAfterWelcome = null;
    this._replaceSession(setSessionConnectionState(this._session, "offline", { clearRoom: true }), "endpoint-reset");
    this._replaceSession(setSessionConnectionState(this._session, "connecting"), "connecting");
    try {
      const connected = this.transport.connect(endpoint) === true;
      if (!connected) {
        try { this.transport.disconnect({ code: 1000, reason: "Explicit multiplayer connection did not start." }); }
        catch { /* The client state still fails closed. */ }
        this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
        this._replaceSession(setSessionConnectionState(this._session, "offline", { clearRoom: true }), "connect-not-started");
      }
      return connected;
    } catch (error) {
      try { this.transport.disconnect({ code: 1000, reason: "Explicit multiplayer connection failed." }); }
      catch { /* Preserve the original connection error. */ }
      this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
      this._replaceSession(setSessionConnectionState(this._session, "offline", { clearRoom: true }), "connect-failed");
      this._reportError(error, "connect");
      throw error;
    }
  }

  disconnect(options = {}) {
    if (this.destroyed) return false;
    this._rejectPendingCommands(new Error("Multiplayer disconnected before the robot command completed."));
    this.rejoinRoomId = null;
    this.rejoinAfterWelcome = null;
    this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
    this._resetServerScope();
    const disconnected = this.transport.disconnect(options);
    if (this._session.mode !== "offline") {
      this._replaceSession(setSessionConnectionState(this._session, "offline", { clearRoom: true }), "disconnected");
    }
    return disconnected;
  }

  destroy() {
    if (this.destroyed) return false;
    this.disconnect({ code: 1000, reason: "Multiplayer client destroyed." });
    this.destroyed = true;
    this.unsubscribeTransport?.();
    this.unsubscribeTransport = null;
    this.events.clear();
    return true;
  }

  joinRoom(roomId, {
    levelId = this._session.levelId,
    displayName = this.displayName,
  } = {}) {
    this._assertActive();
    if (!this.isConnected) return false;
    const previousSession = this._session;
    this._replaceSession(
      setSessionConnectionState(this._session, "connecting", { roomId }),
      "joining-room",
    );
    const { sent } = this._sendMessage("room.join", { levelId, displayName }, { roomId });
    if (!sent && this._session.mode === "connecting") this._replaceSession(previousSession, "join-not-sent");
    return sent;
  }

  leaveRoom(reason = "Participant left the room.") {
    this._assertActive();
    if (!this.isConnected || !this._session.roomId) return false;
    const { sent } = this._sendMessage("room.leave", { reason }, { roomId: this._session.roomId });
    if (sent) {
      this._rejectPendingCommands(new Error("Left the multiplayer room before the robot command completed."));
      this.rejoinRoomId = null;
      this.rejoinAfterWelcome = null;
      this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
      this._replaceSession(setSessionConnectionState(this._session, "offline", { clearRoom: true }), "left-room");
    }
    return sent;
  }

  shareAction(value, { source = "ui" } = {}) {
    this._assertActive();
    assertMultiplayerPrivacyBoundary(value);
    const action = normalizeGameAction(value, {
      source,
      now: this.now,
      idFactory: () => this.actionIdFactory(this.participantId, ++this.actionSequence),
    });
    if (action.source === "remote") throw new TypeError("Remote game actions cannot be echoed to multiplayer.");
    if (!isShareableGameAction(action)) throw new TypeError("This game action is device-local and cannot be shared.");
    if (!this.isConnected
      || this._session.mode !== "room"
      || !this._session.roomId
      || this._session.needsSync) return false;
    const { sent } = this._sendMessage("action.intent", { action }, { roomId: this._session.roomId });
    return sent;
  }

  sendActionIntent(value, options = {}) {
    return this.shareAction(value, options);
  }

  setCommandAuthority(authority) {
    this._assertActive();
    validateAuthority(authority);
    if (authority === MULTIPLAYER_COMMAND_AUTHORITIES.SERVER
      && (this._session.mode !== "room" || this._session.authority !== "server")) {
      throw new Error("Server command authority requires a validated server-authority room snapshot.");
    }
    return this._setCommandAuthority(authority);
  }

  async executeRobotCommand(command, { robotId = this.robotId } = {}) {
    this._assertActive();
    if (this.commandAuthority === MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL) {
      if (!this.executeLocalCommand) throw new Error("No local robot command executor is configured.");
      const localCommand = normalizeLocalRobotCommand(command);
      return this.executeLocalCommand(localCommand.method, [...localCommand.args], { robotId, authority: "local" });
    }
    const normalized = normalizeRobotCommand(command);
    if (!this.isConnected || this._session.mode !== "room" || !this._session.roomId || this._session.needsSync) {
      throw new Error("Server-authority robot commands require an active, synchronized multiplayer room.");
    }

    const requestId = `command:${this.participantId}:${++this.commandSequence}`;
    return new Promise((resolve, reject) => {
      const timer = this.setTimeoutFn(() => {
        this.pendingCommands.delete(requestId);
        reject(new Error("Server-authority robot command timed out."));
      }, this.commandTimeoutMs);
      this.pendingCommands.set(requestId, { resolve, reject, timer });
      try {
        const { sent } = this._sendMessage("robot.command", {
          robotId,
          requestId,
          command: normalized,
        }, { roomId: this._session.roomId });
        if (!sent) {
          this._settleCommand(requestId, {
            error: "Server-authority robot command was not sent; disconnected messages are never queued.",
          });
        }
      } catch (error) {
        this._settleCommand(requestId, { error: error?.message || String(error) });
      }
    });
  }

  projectLocalRobot(telemetry, {
    robotId = this.robotId,
    status = null,
    levelId = null,
  } = {}) {
    this._assertActive();
    const session = updateLocalRobotProjection(this._session, { robotId, telemetry, status, levelId });
    this._replaceSession(session, "local-robot-projection");
    return session;
  }

  updateLocalRobotProjection(telemetry, options = {}) {
    return this.projectLocalRobot(telemetry, options);
  }

  _handleTransportEvent(event) {
    if (this.destroyed || !event || typeof event !== "object") return;
    switch (event.type) {
      case "open": {
        this.connectionSequence += 1;
        this.clientSequence = 0;
        this.syncRequestedAfter = null;
        this.awaitingWelcome = true;
        this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
        this.rejoinAfterWelcome = event.reconnected ? this.rejoinRoomId : null;
        this._replaceSession(setSessionConnectionState(this._session, "connecting"), event.reconnected ? "reconnected" : "connected");
        const { sent } = this._sendMessage("hello", {
          lastServerEpoch: this.serverEpoch,
          lastServerSequence: this.serverEpoch === null ? null : this._session.serverSequence,
          clientVersion: this.clientVersion,
        }, { roomId: null });
        if (!sent) this._reportError(new Error("Multiplayer hello could not be sent."), "hello");
        this.events.emit({ type: "connection", state: "open", reconnected: Boolean(event.reconnected) });
        break;
      }
      case "message":
        this._handleServerMessage(event.message);
        break;
      case "close":
        this._rejectPendingCommands(new Error("Connection closed before the robot command completed."));
        this.rejoinRoomId = event.willReconnect ? this._session.roomId : null;
        this.awaitingWelcome = false;
        if (!event.willReconnect) this.rejoinAfterWelcome = null;
        this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
        this._replaceSession(
          setSessionConnectionState(this._session, event.willReconnect ? "connecting" : "offline", event.willReconnect
            ? { authority: "local" }
            : { clearRoom: true }),
          event.willReconnect ? "reconnecting" : "closed",
        );
        if (!event.willReconnect) this._resetServerScope();
        this.events.emit({ type: "connection", state: event.willReconnect ? "reconnecting" : "closed", detail: event });
        break;
      case "error":
        this._reportError(event.error || new Error("Multiplayer transport error."), "transport");
        break;
      default:
        this._reportError(new Error(`Unknown multiplayer transport event: ${event.type}`), "transport-event");
    }
  }

  _handleServerMessage(input) {
    let message;
    try {
      message = normalizeMultiplayerMessage(input, { direction: "server" });
      if (this.awaitingWelcome) {
        if (message.type !== "welcome") throw new Error("The first server message on a connection must be welcome.");
        this._prepareWelcome(message);
      } else if (message.type === "welcome") {
        throw new Error("The server sent more than one welcome message on a connection.");
      }
      if (this.seenServerMessageIds.has(message.messageId)) return;
      if (message.type === "room.snapshot" && this._session.serverSequence > 0
        && message.sequence <= this._session.serverSequence) {
        this._rememberServerMessage(message.messageId);
        return;
      }
      if (this._session.roomId && message.roomId && message.roomId !== this._session.roomId) {
        throw new Error("Multiplayer server message belongs to another room.");
      }
      if (message.type !== "room.snapshot" && this._session.serverSequence === 0 && message.sequence !== 1) {
        throw new Error("Initial multiplayer server sequence must begin at one or with a room snapshot.");
      }

      const result = applySessionMessage(this._session, message);
      if (result.needsSync) {
        const expected = this._session.serverSequence + 1;
        this._rejectPendingCommands(new Error("Multiplayer synchronization was lost before the robot command completed."));
        this._replaceSession(result.session, "sequence-gap");
        this._requestSync();
        this.events.emit({
          type: "sequence-gap",
          expected,
          received: message.sequence,
        });
        return;
      }

      this._rememberServerMessage(message.messageId);
      if (!result.applied) return;
      if (message.type === "welcome") this.awaitingWelcome = false;
      this._replaceSession(result.session, message.type);
      if (message.type === "room.snapshot") {
        this.syncRequestedAfter = null;
        this.rejoinRoomId = null;
        this.rejoinAfterWelcome = null;
        this._setCommandAuthority(
          this._session.authority === "server"
            ? MULTIPLAYER_COMMAND_AUTHORITIES.SERVER
            : MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL,
        );
      } else if (this._session.mode === "offline") {
        this.rejoinRoomId = null;
        this.rejoinAfterWelcome = null;
        this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
      }

      if (message.type === "action.commit" && message.participantId !== this.participantId) {
        const remoteAction = normalizeGameAction({ ...message.payload.action, source: "remote" });
        this._safeCallback(this.onRemoteAction, remoteAction, {
          participantId: message.participantId,
          roomId: message.roomId,
          tick: message.payload.tick,
        });
        this.events.emit({
          type: "remote-action",
          action: remoteAction,
          participantId: message.participantId,
          tick: message.payload.tick,
        });
      }
      if (message.type === "robot.result") this._settleCommand(message.payload.requestId, message.payload);
      if (message.type === "error") this._reportError(new Error(message.payload.message), message.payload.code, message.payload);
      if (message.type === "welcome" && this.rejoinAfterWelcome) {
        const roomId = this.rejoinAfterWelcome;
        this.rejoinAfterWelcome = null;
        this.joinRoom(roomId, { levelId: this._session.levelId, displayName: this.displayName });
      }

      if (message.roomId && this._session.roomId && this.isConnected) {
        this._sendMessage("state.ack", { serverSequence: this._session.serverSequence }, { roomId: this._session.roomId });
      }
    } catch (error) {
      this._reportError(error, "server-message");
      if (this.awaitingWelcome || message?.type === "welcome") {
        this.disconnect({ code: 1002, reason: "Invalid multiplayer handshake." });
      }
    }
  }

  _requestSync() {
    if (!this.isConnected || !this._session.roomId) return false;
    const afterSequence = this._session.serverSequence;
    if (this.syncRequestedAfter === afterSequence) return false;
    this.syncRequestedAfter = afterSequence;
    const { sent } = this._sendMessage("sync.request", { afterSequence }, { roomId: this._session.roomId });
    if (!sent) this.syncRequestedAfter = null;
    return sent;
  }

  _sendMessage(type, payload, { roomId = this._session.roomId } = {}) {
    assertMultiplayerPrivacyBoundary(payload);
    if (!this.isConnected) return { sent: false, message: null };
    const sequence = this.clientSequence + 1;
    const message = createMultiplayerMessage(type, payload, {
      roomId,
      participantId: this.participantId,
      sequence,
      messageId: this.messageIdFactory(this.participantId, this.connectionSequence, sequence, type),
      sentAt: safeNow(this.now),
      direction: "client",
    });
    this.clientSequence = sequence;
    let sent = false;
    try {
      sent = this.transport.send(message) === true;
    } finally {
      if (!sent && this.clientSequence === sequence) this.clientSequence -= 1;
    }
    if (sent) this.events.emit({ type: "outbound", message });
    return { sent, message: sent ? message : null };
  }

  _settleCommand(requestId, payload) {
    const pending = this.pendingCommands.get(requestId);
    if (!pending) return false;
    this.pendingCommands.delete(requestId);
    this.clearTimeoutFn(pending.timer);
    if (payload.error) pending.reject(new Error(payload.error));
    else pending.resolve(payload.result ?? null);
    return true;
  }

  _setCommandAuthority(authority) {
    if (this.commandAuthority === authority) return authority;
    if (this.commandAuthority === MULTIPLAYER_COMMAND_AUTHORITIES.SERVER
      && authority === MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL) {
      this._rejectPendingCommands(new Error("Server command authority ended before the robot command completed."));
    }
    this.commandAuthority = authority;
    this.events.emit({ type: "command-authority", authority });
    return authority;
  }

  _rejectPendingCommands(error) {
    for (const [requestId, pending] of this.pendingCommands) {
      this.pendingCommands.delete(requestId);
      this.clearTimeoutFn(pending.timer);
      pending.reject(error);
    }
  }

  _rememberServerMessage(messageId) {
    this.seenServerMessageIds.add(messageId);
    this.seenServerMessageOrder.push(messageId);
    if (this.seenServerMessageOrder.length > MAX_SEEN_SERVER_MESSAGES) {
      this.seenServerMessageIds.delete(this.seenServerMessageOrder.shift());
    }
  }

  _prepareWelcome(message) {
    const nextEpoch = message.payload.serverEpoch;
    const previousEpoch = this.serverEpoch;
    const epochChanged = previousEpoch !== null && previousEpoch !== nextEpoch;
    const establishesEpoch = previousEpoch === null || epochChanged;

    if (establishesEpoch) {
      this._resetServerScope();
      this.serverEpoch = nextEpoch;
      this.awaitingWelcome = true;
      this._setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
      this._replaceSession(
        setSessionConnectionState(
          setSessionConnectionState(this._session, "offline", { clearRoom: true }),
          "connecting",
        ),
        epochChanged ? "server-epoch-changed" : "server-epoch-established",
      );
      if (message.sequence !== 1) throw new Error("A new multiplayer server epoch must begin at sequence one.");
      return;
    }

    if (message.sequence !== this._session.serverSequence + 1) {
      throw new Error("A reconnect within the same server epoch must continue the server sequence.");
    }
    if (this.seenServerMessageIds.has(message.messageId)) {
      throw new Error("A reconnect welcome messageId must be unique within its server epoch.");
    }
  }

  _resetServerScope() {
    this.serverEpoch = null;
    this.awaitingWelcome = false;
    this.seenServerMessageIds.clear();
    this.seenServerMessageOrder.length = 0;
    this.syncRequestedAfter = null;
  }

  _replaceSession(session, reason) {
    if (session === this._session) return;
    this._session = session;
    this._safeCallback(this.onSessionChange, session, reason);
    this.events.emit({ type: "session", session, reason });
  }

  _reportError(value, context, detail = null) {
    const error = value instanceof Error ? value : new Error(String(value || "Unknown multiplayer error."));
    this._safeCallback(this.onError, error, context, detail);
    this.events.emit({ type: "error", error, context, detail });
  }

  _safeCallback(callback, ...args) {
    if (!callback) return;
    try { callback(...args); }
    catch (error) {
      if (callback !== this.onError) {
        try { this.onError?.(error, "consumer-callback"); }
        catch { /* Error observers are isolated too. */ }
      }
    }
  }

  _assertActive() {
    if (this.destroyed) throw new Error("Multiplayer client has been destroyed.");
  }
}

export function createMultiplayerClient(options) {
  return new MultiplayerClient(options);
}

function validateTransport(value) {
  if (!value || typeof value !== "object" || typeof value.subscribe !== "function"
    || typeof value.connect !== "function" || typeof value.send !== "function"
    || typeof value.disconnect !== "function") {
    throw new TypeError("Multiplayer transport is invalid.");
  }
}

function validateAuthority(value) {
  if (value !== MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL && value !== MULTIPLAYER_COMMAND_AUTHORITIES.SERVER) {
    throw new TypeError("Multiplayer command authority must be local or server.");
  }
}

function validateOptionalFunction(value, label) {
  if (value !== null && typeof value !== "function") throw new TypeError(`${label} must be a function.`);
}

function normalizedFieldKey(value) {
  return String(value).replace(/[^a-z0-9]/gi, "").toLowerCase();
}

function safeNow(now) {
  const value = Number(now());
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError("Multiplayer clock must return a non-negative safe integer.");
  return value;
}

function defaultMessageId(participantId, connectionSequence, sequence) {
  return `${participantId}:connection:${connectionSequence}:message:${sequence}`;
}

function defaultActionId(participantId, sequence) {
  return `${participantId}:action:${sequence}`;
}

function normalizeLocalRobotCommand(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || !LOCAL_ROBOT_COMMANDS.has(value.method) || !Array.isArray(value.args) || value.args.length > 4) {
    throw new TypeError("Local robot command is invalid.");
  }
  const args = value.args.map((argument) => {
    if (typeof argument === "number" && Number.isFinite(argument)) return argument;
    if (typeof argument === "string" && argument.length <= 64 && !/[\u0000-\u001f]/.test(argument)) return argument;
    throw new TypeError("Local robot command argument is invalid.");
  });
  return { method: value.method, args };
}
