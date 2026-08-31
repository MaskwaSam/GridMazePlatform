import assert from "node:assert/strict";
import {
  GAME_ACTION_KINDS,
} from "../js/game-actions.js";
import {
  MAX_MULTIPLAYER_MESSAGE_BYTES,
  createMultiplayerMessage,
  decodeMultiplayerMessage,
  encodeMultiplayerMessage,
  normalizeRobotCommand,
  validateMultiplayerEndpoint,
} from "../js/multiplayer-protocol.js";
import {
  MULTIPLAYER_COMMAND_AUTHORITIES,
  assertMultiplayerPrivacyBoundary,
  createMultiplayerClient,
} from "../js/multiplayer-client.js";
import {
  LoopbackHub,
  MULTIPLAYER_TRANSPORT_STATES,
  OfflineTransport,
  WebSocketTransport,
} from "../js/multiplayer-transport.js";

const fixedNow = () => 1_800_000_000_000;

function clientMessage(type, payload, overrides = {}) {
  return createMultiplayerMessage(type, payload, {
    roomId: overrides.roomId ?? null,
    participantId: overrides.participantId ?? "student-1",
    sequence: overrides.sequence ?? 1,
    messageId: overrides.messageId ?? "student-1:message:1",
    sentAt: overrides.sentAt ?? fixedNow(),
    direction: "client",
  });
}

function serverMessage(type, payload, overrides = {}) {
  return createMultiplayerMessage(type, payload, {
    roomId: overrides.roomId ?? null,
    participantId: overrides.participantId ?? "server-1",
    sequence: overrides.sequence ?? 1,
    messageId: overrides.messageId ?? "server-1:message:1",
    sentAt: overrides.sentAt ?? fixedNow(),
    direction: "server",
  });
}

// Protocol normalization is exact, directional, size-bounded, and local-input-only.
{
  const intent = clientMessage("action.intent", {
    action: {
      id: "student-1:action:1",
      kind: GAME_ACTION_KINDS.SELECT_LEVEL,
      source: "gamepad",
      createdAt: fixedNow(),
      payload: { levelId: "mirror-left" },
    },
  }, { roomId: "room-1" });
  assert.deepEqual(decodeMultiplayerMessage(encodeMultiplayerMessage(intent, { direction: "client" }), {
    direction: "client",
  }), intent);
  assert.ok(Object.isFrozen(intent));
  assert.ok(Object.isFrozen(intent.payload.action));

  assert.throws(() => clientMessage("action.intent", {
    action: {
      id: "student-1:action:2",
      kind: GAME_ACTION_KINDS.OPEN_SETTINGS,
      source: "ui",
      createdAt: fixedNow(),
      payload: {},
    },
  }, { roomId: "room-1" }), /device-local/);
  assert.throws(() => clientMessage("action.intent", {
    action: {
      id: "student-1:action:3",
      kind: GAME_ACTION_KINDS.RUN,
      source: "remote",
      createdAt: fixedNow(),
      payload: {},
    },
  }, { roomId: "room-1" }), /local input source/);
  assert.throws(() => decodeMultiplayerMessage("not json", { direction: "server" }), /valid JSON/);
  assert.throws(() => decodeMultiplayerMessage("x".repeat(MAX_MULTIPLAYER_MESSAGE_BYTES + 1)), /too large/);
  assert.throws(() => decodeMultiplayerMessage(JSON.stringify({ ...intent, extra: true })), /Unknown multiplayer envelope/);
  assert.throws(() => encodeMultiplayerMessage(intent, { direction: "server" }), /Expected a server/);
  assert.throws(() => normalizeRobotCommand({ method: "roll", args: [0, 256, 1] }), /out of range/);
  assert.throws(() => normalizeRobotCommand({ method: "wait", args: [31] }), /out of range/);
}

// WebSocket endpoint policy is same-origin by default, allows an explicit
// origin list, and rejects insecure remote hosts or URL-borne secrets.
{
  assert.equal(validateMultiplayerEndpoint("wss://maze.example/ws", "https://maze.example/game"), "wss://maze.example/ws");
  assert.equal(validateMultiplayerEndpoint("/ws", "https://maze.example/game"), "wss://maze.example/ws");
  assert.equal(validateMultiplayerEndpoint("ws://localhost:8080/socket", "http://localhost:8080/game"), "ws://localhost:8080/socket");
  assert.equal(validateMultiplayerEndpoint("ws://127.0.0.1/socket", null, {
    allowedOrigins: ["http://127.0.0.1"],
  }), "ws://127.0.0.1/socket");
  assert.equal(validateMultiplayerEndpoint("wss://classroom.example/ws", "https://maze.example/game", {
    allowedOrigins: ["wss://classroom.example"],
  }), "wss://classroom.example/ws");
  assert.throws(() => validateMultiplayerEndpoint("wss://maze.example/ws"), /same-origin base URL or an explicit/);
  assert.throws(() => validateMultiplayerEndpoint("wss://other.example/ws", "https://maze.example/game"), /origin is not allowed/);
  assert.throws(() => validateMultiplayerEndpoint("ws://localhost:8080/socket", "https://maze.example/game"), /origin is not allowed/);
  for (const endpoint of [
    "http://maze.example/ws",
    "ws://maze.example/ws",
    "wss://student:secret@maze.example/ws",
    "wss://maze.example/ws#token",
    "javascript:alert(1)",
  ]) {
    assert.throws(() => validateMultiplayerEndpoint(endpoint, "https://maze.example/game"));
  }

  assert.throws(() => clientMessage("hello", {
    lastServerSequence: 4,
    clientVersion: "test",
  }), /provide lastServerEpoch and lastServerSequence together/);
  assert.throws(() => serverMessage("welcome", {
    serverTime: fixedNow(),
    authority: "local",
  }), /serverEpoch/);
}

// The default client is offline and cannot construct sockets or call fetch.
{
  const originalWebSocket = Object.getOwnPropertyDescriptor(globalThis, "WebSocket");
  const originalFetch = Object.getOwnPropertyDescriptor(globalThis, "fetch");
  let socketConstructions = 0;
  let fetchCalls = 0;
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    writable: true,
    value: class NetworkTripwire {
      constructor() { socketConstructions += 1; }
    },
  });
  Object.defineProperty(globalThis, "fetch", {
    configurable: true,
    writable: true,
    value: () => { fetchCalls += 1; throw new Error("network tripwire"); },
  });
  try {
    const client = createMultiplayerClient({
      levelId: "starter-l",
      participantId: "offline-student",
      now: fixedNow,
    });
    assert.ok(client.transport instanceof OfflineTransport);
    assert.equal(client.session.mode, "offline");
    assert.equal(client.transport.networkAttempts, 0);
    assert.equal(client.connect("wss://maze.example/ws"), false);
    assert.equal(client.transport.send(clientMessage("ping", { nonce: "offline" })), false);
    assert.equal(socketConstructions, 0);
    assert.equal(fetchCalls, 0);
    client.destroy();
  } finally {
    if (originalWebSocket) Object.defineProperty(globalThis, "WebSocket", originalWebSocket);
    else delete globalThis.WebSocket;
    if (originalFetch) Object.defineProperty(globalThis, "fetch", originalFetch);
    else delete globalThis.fetch;
  }
}

// Privacy is a hard structural boundary, independent of later protocol checks.
{
  assert.equal(assertMultiplayerPrivacyBoundary({ action: { payload: { levelId: "starter-l" } } }), true);
  assert.throws(() => createMultiplayerClient({
    levelId: "starter-l",
    participantId: "premature-server",
    commandAuthority: MULTIPLAYER_COMMAND_AUTHORITIES.SERVER,
  }), /begin with local command authority/);
  for (const privatePayload of [
    { code: "await roll(0, 100, 1)" },
    { state: { userSettings: { showGrid: true } } },
    { nested: [{ attemptHistory: [] }] },
    { project: { blocks: {} } },
  ]) {
    assert.throws(() => assertMultiplayerPrivacyBoundary(privatePayload), /Private field/);
  }
}

// Two loopback clients share only normalized intents; commits are de-duped and
// sequence gaps trigger exactly one snapshot recovery request.
{
  const hub = new LoopbackHub({ now: fixedNow });
  const alphaRemote = [];
  const betaRemote = [];
  const alpha = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-alpha",
    displayName: "Alpha",
    transport: hub.createTransport(),
    onRemoteAction: (action, detail) => alphaRemote.push({ action, detail }),
    now: fixedNow,
  });
  const beta = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-beta",
    displayName: "Beta",
    transport: hub.createTransport(),
    onRemoteAction: (action, detail) => betaRemote.push({ action, detail }),
    now: fixedNow,
  });
  const betaOutbound = [];
  beta.subscribe((event) => {
    if (event.type === "outbound") betaOutbound.push(event.message);
  });

  assert.equal(alpha.connect(), true);
  assert.equal(alpha.shareAction(GAME_ACTION_KINDS.RUN), false, "connected clients do not send room actions before joining");
  assert.equal(beta.connect(), true);
  assert.equal(hub.connectionCount, 2);
  assert.equal(alpha.joinRoom("room-class", { levelId: "starter-l" }), true);
  assert.equal(beta.joinRoom("room-class", { levelId: "starter-l" }), true);
  assert.equal(alpha.session.mode, "room");
  assert.equal(beta.session.mode, "room");
  assert.deepEqual(Object.keys(alpha.session.participants).sort(), ["student-alpha", "student-beta"]);
  assert.deepEqual(Object.keys(beta.session.participants).sort(), ["student-alpha", "student-beta"]);
  assert.equal(alpha.connect(), true, "connect is idempotent while a transport is already open");
  assert.equal(alpha.session.mode, "room");

  assert.equal(alpha.shareAction(GAME_ACTION_KINDS.RUN, { source: "ui" }), true);
  assert.equal(alphaRemote.length, 0, "the sender must not execute its committed action twice");
  assert.equal(betaRemote.length, 1);
  assert.equal(betaRemote[0].action.kind, GAME_ACTION_KINDS.RUN);
  assert.equal(betaRemote[0].action.source, "remote");
  assert.equal(betaRemote[0].detail.participantId, "student-alpha");
  assert.equal(alpha.session.lastAction.kind, GAME_ACTION_KINDS.RUN);
  assert.equal(beta.session.lastAction.kind, GAME_ACTION_KINDS.RUN);
  assert.throws(() => alpha.shareAction(GAME_ACTION_KINDS.OPEN_SETTINGS), /device-local/);
  assert.throws(() => alpha.shareAction({ kind: GAME_ACTION_KINDS.RUN, attempts: [] }), /Private field/);
  assert.throws(() => alpha.shareAction({ kind: GAME_ACTION_KINDS.RUN, source: "remote" }), /cannot be echoed/);

  const betaConnection = hub.connections.get(beta.transport);
  const duplicateCommit = hub.sendServerMessage(beta.transport, "action.commit", {
    action: {
      id: "student-alpha:action:duplicate-check",
      kind: GAME_ACTION_KINDS.STOP,
      source: "ui",
      createdAt: fixedNow(),
      payload: {},
    },
    tick: 2,
  }, {
    roomId: "room-class",
    participantId: "student-alpha",
  });
  assert.equal(betaRemote.length, 2);
  beta.transport._deliver(duplicateCommit);
  assert.equal(betaRemote.length, 2, "the same server message id is applied once");

  const beforeStaleSnapshot = beta.session;
  const staleSequence = beforeStaleSnapshot.serverSequence - 1;
  beta.transport._deliver(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-class",
      levelId: "starter-l",
      authority: "local",
      participants: Object.values(beforeStaleSnapshot.participants),
      robots: Object.values(beforeStaleSnapshot.robots),
      tick: 0,
      serverSequence: staleSequence,
    },
  }, {
    roomId: "room-class",
    participantId: "loopback-server",
    sequence: staleSequence,
    messageId: "server:stale:snapshot",
  }));
  assert.equal(beta.session, beforeStaleSnapshot, "a new-id stale snapshot cannot roll session state backward");

  const syncBefore = betaOutbound.filter(({ type }) => type === "sync.request").length;
  const gapSequence = betaConnection.serverSequence + 2;
  hub.sendServerMessage(beta.transport, "action.commit", {
    action: {
      id: "student-alpha:action:gap",
      kind: GAME_ACTION_KINDS.RESET,
      source: "ui",
      createdAt: fixedNow(),
      payload: {},
    },
    tick: 3,
  }, {
    roomId: "room-class",
    participantId: "student-alpha",
    sequence: gapSequence,
  });
  assert.equal(beta.session.needsSync, false, "loopback snapshot recovers the gap synchronously");
  assert.equal(beta.session.serverSequence, gapSequence + 1);
  assert.equal(betaRemote.length, 2, "an out-of-sequence commit is not speculatively applied");
  assert.equal(
    betaOutbound.filter(({ type }) => type === "sync.request").length,
    syncBefore + 1,
    "one gap produces one sync request",
  );

  const outboundJson = betaOutbound.map((message) => JSON.stringify(message)).join("\n");
  assert.doesNotMatch(outboundJson, /pythonSource|attemptHistory|userSettings|\"code\"/);
  beta.disconnect();
  assert.equal(alpha.session.participants["student-beta"], undefined);
  assert.equal(beta.session.roomId, null);
  assert.equal(beta.session.mode, "offline");
  alpha.destroy();
  beta.destroy();
}

// Local command authority stays local even in a server-authority room; opting
// into server authority gives correlated result/error RPC without leaking args.
{
  let serverCommands = 0;
  const hub = new LoopbackHub({
    authority: "server",
    now: fixedNow,
    executeRobotCommand(method, args, context) {
      serverCommands += 1;
      assert.equal(context.roomId, "room-rpc");
      if (method === "get_heading") return 137;
      if (method === "get_speed") throw new Error("Remote motor is unavailable.");
      return args[0] ?? null;
    },
  });
  const localCalls = [];
  const client = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-rpc",
    transport: hub.createTransport(),
    executeLocalCommand(method, args, context) {
      localCalls.push({ method, args, context });
      return method === "get_heading" ? 42 : null;
    },
    now: fixedNow,
  });
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL, "local execution is the offline default");
  assert.equal(await client.executeRobotCommand({ method: "get_heading", args: [] }), 42);
  assert.equal(localCalls.length, 1);
  assert.equal(await client.executeRobotCommand({ method: "roll", args: [0, 1_000, 0.1] }), null);
  assert.deepEqual(localCalls.at(-1).args, [0, 1_000, 0.1], "offline commands stopped reaching the simulation's existing clamp semantics");
  assert.equal(serverCommands, 0);

  client.connect();
  client.joinRoom("room-rpc");
  assert.equal(client.session.authority, "server", "server capability is visible in the session");
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.SERVER, "a validated room snapshot selects server RPC");
  const resultPromise = client.executeRobotCommand({ method: "get_heading", args: [] });
  await hub.flush();
  assert.equal(await resultPromise, 137);
  assert.equal(serverCommands, 1);

  const errorPromise = client.executeRobotCommand({ method: "get_speed", args: [] });
  const rejection = assert.rejects(errorPromise, /Remote motor is unavailable/);
  await hub.flush();
  await rejection;
  assert.equal(serverCommands, 2);

  client.setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
  assert.equal(await client.executeRobotCommand({ method: "get_heading", args: [] }), 42);
  client.setCommandAuthority(MULTIPLAYER_COMMAND_AUTHORITIES.SERVER);

  const projected = client.projectLocalRobot({
    x: 10,
    z: -20,
    heading: 90,
    speed: 25,
    commandedSpeed: 40,
    collisions: 1,
  });
  assert.equal(projected.robots["robot-local"].x, 10);
  assert.equal(projected.robots["robot-local"].status, "running");
  client.disconnect();
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
  client.destroy();
}

// Leaving a room fails in-flight server commands closed, and the loopback
// server drops the late result instead of delivering it into a later session.
{
  let resolveServerCommand;
  let markServerCommandStarted;
  const serverCommandStarted = new Promise((resolve) => { markServerCommandStarted = resolve; });
  const hub = new LoopbackHub({
    authority: "server",
    now: fixedNow,
    executeRobotCommand() {
      markServerCommandStarted();
      return new Promise((resolve) => { resolveServerCommand = resolve; });
    },
  });
  const client = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-leaving",
    transport: hub.createTransport(),
    now: fixedNow,
  });
  client.connect();
  client.joinRoom("room-leaving");
  const command = client.executeRobotCommand({ method: "get_heading", args: [] });
  const rejected = assert.rejects(command, /Left the multiplayer room/);
  await serverCommandStarted;
  assert.equal(client.leaveRoom(), true);
  await rejected;
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
  assert.equal(client.session.roomId, null);
  resolveServerCommand(271);
  await hub.flush();
  assert.equal(client.session.roomId, null, "a late result cannot restore or mutate the room session");
  client.destroy();
}

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.listeners = new Map();
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  send(value) {
    if (this.readyState !== FakeWebSocket.OPEN) throw new Error("fake socket is not open");
    this.sent.push(value);
  }

  close(code = 1000, reason = "") {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close", { code, reason, wasClean: code === 1000 });
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.emit("open", {});
  }

  receive(data) {
    this.emit("message", { data });
  }

  lose(code = 1006, reason = "network lost") {
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close", { code, reason, wasClean: false });
  }

  emit(type, event) {
    for (const listener of [...(this.listeners.get(type) || [])]) listener(event);
  }
}

function fakeTimers() {
  let nextId = 1;
  const pending = new Map();
  return {
    setTimeoutFn(callback, delay) {
      const id = nextId++;
      pending.set(id, { callback, delay });
      return id;
    },
    clearTimeoutFn(id) { pending.delete(id); },
    get size() { return pending.size; },
    runNext() {
      const entry = pending.entries().next().value;
      assert.ok(entry, "expected a pending fake timer");
      const [id, task] = entry;
      pending.delete(id);
      task.callback();
      return task.delay;
    },
  };
}

// A detected sequence gap blocks both action intents and server-authority RPC
// until a validated snapshot restores synchronized room state.
{
  FakeWebSocket.instances = [];
  const transport = new WebSocketTransport({
    WebSocketImpl: FakeWebSocket,
    baseUrl: "https://maze.example/",
    maxReconnectAttempts: 0,
  });
  const client = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-sync-gate",
    transport,
    now: fixedNow,
  });
  client.connect("wss://maze.example/socket");
  const socket = FakeWebSocket.instances[0];
  socket.open();
  socket.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "sync-server-epoch",
    authority: "server",
  }), { direction: "server" }));
  client.joinRoom("room-sync-gate");
  socket.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-sync-gate",
      levelId: "starter-l",
      authority: "server",
      participants: [{ id: "student-sync-gate", displayName: "student-sync-gate", role: "student" }],
      robots: [],
      tick: 0,
      serverSequence: 2,
    },
  }, {
    roomId: "room-sync-gate",
    sequence: 2,
    messageId: "server-sync:snapshot:2",
  }), { direction: "server" }));
  const pendingBeforeGap = client.executeRobotCommand({ method: "get_heading", args: [] });
  const rejectedByGap = assert.rejects(pendingBeforeGap, /synchronization was lost/);
  socket.receive(encodeMultiplayerMessage(serverMessage("action.commit", {
    action: {
      id: "other-student:action:1",
      kind: GAME_ACTION_KINDS.RUN,
      source: "ui",
      createdAt: fixedNow(),
      payload: {},
    },
    tick: 1,
  }, {
    roomId: "room-sync-gate",
    participantId: "other-student",
    sequence: 4,
    messageId: "server-sync:gap:4",
  }), { direction: "server" }));
  await rejectedByGap;
  assert.equal(client.session.needsSync, true);
  const sentBeforeGatedInput = socket.sent.length;
  assert.equal(client.shareAction(GAME_ACTION_KINDS.STOP), false);
  await assert.rejects(
    client.executeRobotCommand({ method: "get_heading", args: [] }),
    /active, synchronized multiplayer room/,
  );
  assert.equal(socket.sent.length, sentBeforeGatedInput, "stale room state emits no action or robot command");

  socket.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-sync-gate",
      levelId: "starter-l",
      authority: "server",
      participants: [{ id: "student-sync-gate", displayName: "student-sync-gate", role: "student" }],
      robots: [],
      tick: 1,
      serverSequence: 5,
    },
  }, {
    roomId: "room-sync-gate",
    sequence: 5,
    messageId: "server-sync:recovered:5",
  }), { direction: "server" }));
  assert.equal(client.session.needsSync, false);
  const pendingBeforeDowngrade = client.executeRobotCommand({ method: "get_heading", args: [] });
  const rejectedByDowngrade = assert.rejects(pendingBeforeDowngrade, /authority ended/);
  socket.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-sync-gate",
      levelId: "starter-l",
      authority: "local",
      participants: [{ id: "student-sync-gate", displayName: "student-sync-gate", role: "student" }],
      robots: [],
      tick: 1,
      serverSequence: 6,
    },
  }, {
    roomId: "room-sync-gate",
    sequence: 6,
    messageId: "server-sync:downgrade:6",
  }), { direction: "server" }));
  await rejectedByDowngrade;
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
  client.destroy();
}

// WebSockets are constructed only by explicit connect, frames are strict text,
// reconnect is bounded, and dropped messages are never replayed.
{
  FakeWebSocket.instances = [];
  const timers = fakeTimers();
  const transport = new WebSocketTransport({
    WebSocketImpl: FakeWebSocket,
    baseUrl: "https://maze.example/",
    allowedOrigins: ["wss://other.example"],
    maxReconnectAttempts: 2,
    reconnectBaseDelayMs: 10,
    reconnectMaxDelayMs: 20,
    setTimeoutFn: timers.setTimeoutFn,
    clearTimeoutFn: timers.clearTimeoutFn,
  });
  assert.equal(FakeWebSocket.instances.length, 0, "transport construction is inert");
  assert.equal(transport.networkAttempts, 0);
  assert.throws(() => transport.connect("ws://maze.example/socket"), /requires wss/);
  assert.equal(FakeWebSocket.instances.length, 0, "invalid endpoints fail before socket construction");

  const client = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-websocket",
    transport,
    now: fixedNow,
  });
  assert.equal(client.connect("wss://maze.example/socket"), true);
  assert.equal(FakeWebSocket.instances.length, 1);
  const first = FakeWebSocket.instances[0];
  assert.equal(first.sent.length, 0, "hello waits for the actual open event");
  first.open();
  const firstHello = decodeMultiplayerMessage(first.sent[0], { direction: "client" });
  assert.equal(firstHello.type, "hello");
  assert.equal(firstHello.sequence, 1);
  first.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "server-epoch-a",
    authority: "server",
  }), { direction: "server" }));
  assert.equal(client.session.serverSequence, 1);
  assert.equal(client.joinRoom("room-reconnect"), true);
  assert.deepEqual(first.sent.map((text) => decodeMultiplayerMessage(text, { direction: "client" }).type), ["hello", "room.join"]);
  first.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-reconnect",
      levelId: "starter-l",
      authority: "server",
      participants: [
        { id: "student-websocket", displayName: "student-websocket", role: "student" },
        { id: "other-student", displayName: "Other student", role: "student" },
      ],
      robots: [],
      tick: 0,
      serverSequence: 2,
    },
  }, {
    roomId: "room-reconnect",
    sequence: 2,
    messageId: "server-a:snapshot:2",
  }), { direction: "server" }));
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.SERVER);

  const droppedPing = clientMessage("ping", { nonce: "do-not-replay" }, {
    participantId: "student-websocket",
    sequence: 99,
    messageId: "student-websocket:manual:99",
  });
  first.lose();
  assert.equal(transport.state, MULTIPLAYER_TRANSPORT_STATES.RECONNECTING);
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL, "a socket loss fails closed during reconnect");
  assert.equal(client.session.authority, "local");
  assert.equal(timers.size, 1);
  assert.equal(transport.send(droppedPing), false);
  assert.equal(timers.runNext(), 10);
  assert.equal(FakeWebSocket.instances.length, 2);
  const second = FakeWebSocket.instances[1];
  second.open();
  const secondHello = decodeMultiplayerMessage(second.sent[0], { direction: "client" });
  assert.equal(secondHello.type, "hello");
  assert.equal(secondHello.sequence, 1, "client envelope sequence resets for a new socket connection");
  assert.equal(secondHello.payload.lastServerEpoch, "server-epoch-a");
  assert.equal(secondHello.payload.lastServerSequence, 2);
  assert.notEqual(secondHello.messageId, firstHello.messageId, "message ids remain unique when per-connection sequences reset");
  assert.equal(transport.reconnectAttempts, 0, "a successful open resets the current outage budget");
  assert.deepEqual(second.sent.map((text) => decodeMultiplayerMessage(text, { direction: "client" }).type), ["hello"]);
  assert.doesNotMatch(second.sent.join("\n"), /do-not-replay/);
  second.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "server-epoch-a",
    authority: "server",
  }, {
    sequence: 3,
    messageId: "server-a:welcome:3",
  }), { direction: "server" }));
  assert.deepEqual(
    second.sent.map((text) => decodeMultiplayerMessage(text, { direction: "client" }).type),
    ["hello", "room.join"],
    "a welcomed reconnect restores room membership but does not replay user traffic",
  );
  assert.doesNotMatch(second.sent.join("\n"), /do-not-replay/);
  second.lose();
  assert.equal(timers.size, 1);
  const socketsBeforeInvalidReplacement = FakeWebSocket.instances.length;
  assert.throws(
    () => client.connect("wss://blocked.example/socket"),
    /origin is not allowed/,
    "an invalid explicit replacement fails closed",
  );
  assert.equal(timers.size, 0, "an invalid explicit replacement cancels the old endpoint reconnect");
  assert.equal(transport.state, MULTIPLAYER_TRANSPORT_STATES.CLOSED);
  assert.equal(FakeWebSocket.instances.length, socketsBeforeInvalidReplacement, "no replacement socket is constructed");
  assert.equal(client.connect("wss://other.example/socket"), true, "an explicit endpoint change supersedes automatic reconnect");
  assert.equal(timers.size, 0);
  assert.equal(client.session.roomId, null, "an explicit endpoint never retains the previous room");
  assert.equal(client.session.serverSequence, 0, "an explicit endpoint never retains the previous server sequence");
  assert.equal(client.session.authority, "local", "an explicit endpoint never retains server authority");
  assert.equal(client.commandAuthority, MULTIPLAYER_COMMAND_AUTHORITIES.LOCAL);
  assert.equal(client.serverEpoch, null);
  assert.equal(client.rejoinRoomId, null);
  assert.equal(client.rejoinAfterWelcome, null);
  assert.equal(client.syncRequestedAfter, null);
  assert.equal(client.seenServerMessageIds.size, 0);
  assert.deepEqual(Object.keys(client.session.participants), ["student-websocket"]);
  const explicitThird = FakeWebSocket.instances[2];
  explicitThird.open();
  const explicitHello = decodeMultiplayerMessage(explicitThird.sent[0], { direction: "client" });
  assert.equal(explicitHello.payload.lastServerEpoch, null);
  assert.equal(explicitHello.payload.lastServerSequence, null);
  explicitThird.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "server-epoch-b",
    authority: "local",
  }, {
    sequence: 1,
    messageId: "server-b:welcome:1",
  }), { direction: "server" }));
  assert.deepEqual(
    explicitThird.sent.map((text) => decodeMultiplayerMessage(text, { direction: "client" }).type),
    ["hello"],
    "an explicit connection to another endpoint never inherits the prior room",
  );
  client.destroy();
  assert.equal(timers.size, 0);
}

// A server restart establishes a new sequence epoch. Sequence one is accepted
// only after the changed epoch clears stale room state, then the intended room
// is rejoined from a new authoritative snapshot.
{
  FakeWebSocket.instances = [];
  const timers = fakeTimers();
  const errors = [];
  const transport = new WebSocketTransport({
    WebSocketImpl: FakeWebSocket,
    baseUrl: "https://maze.example/",
    maxReconnectAttempts: 1,
    reconnectBaseDelayMs: 1,
    reconnectMaxDelayMs: 1,
    setTimeoutFn: timers.setTimeoutFn,
    clearTimeoutFn: timers.clearTimeoutFn,
  });
  const client = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-restart",
    transport,
    now: fixedNow,
    onError: (error) => errors.push(error.message),
  });
  client.connect("wss://maze.example/socket");
  const beforeRestart = FakeWebSocket.instances[0];
  beforeRestart.open();
  beforeRestart.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "server-before-restart",
    authority: "local",
  }), { direction: "server" }));
  client.joinRoom("room-restart");
  beforeRestart.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-restart",
      levelId: "starter-l",
      authority: "local",
      participants: [{ id: "student-restart", displayName: "student-restart", role: "student" }],
      robots: [],
      tick: 0,
      serverSequence: 2,
    },
  }, {
    roomId: "room-restart",
    sequence: 2,
    messageId: "server-before:snapshot:2",
  }), { direction: "server" }));
  beforeRestart.lose();
  timers.runNext();
  const afterRestart = FakeWebSocket.instances[1];
  afterRestart.open();
  const resumeHello = decodeMultiplayerMessage(afterRestart.sent[0], { direction: "client" });
  assert.equal(resumeHello.payload.lastServerEpoch, "server-before-restart");
  assert.equal(resumeHello.payload.lastServerSequence, 2);
  afterRestart.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "server-after-restart",
    authority: "local",
  }, {
    sequence: 1,
    messageId: "server-1:message:1",
  }), { direction: "server" }));
  assert.equal(client.serverEpoch, "server-after-restart");
  assert.equal(client.session.serverSequence, 1);
  assert.equal(client.session.roomId, "room-restart", "the saved room is rejoined only after the new welcome");
  assert.deepEqual(
    afterRestart.sent.map((text) => decodeMultiplayerMessage(text, { direction: "client" }).type),
    ["hello", "room.join"],
  );
  afterRestart.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-restart",
      levelId: "starter-l",
      authority: "local",
      participants: [{ id: "student-restart", displayName: "student-restart", role: "student" }],
      robots: [],
      tick: 0,
      serverSequence: 2,
    },
  }, {
    roomId: "room-restart",
    sequence: 2,
    messageId: "server-after:snapshot:2",
  }), { direction: "server" }));
  assert.equal(client.session.mode, "room");
  assert.equal(client.session.needsSync, false);
  assert.deepEqual(errors, []);
  client.destroy();
}

// A sequence reset under the same epoch is a protocol violation, not a restart.
// It cannot inherit the room or remain connected waiting for ambiguous state.
{
  FakeWebSocket.instances = [];
  const timers = fakeTimers();
  const errors = [];
  const transport = new WebSocketTransport({
    WebSocketImpl: FakeWebSocket,
    baseUrl: "https://maze.example/",
    maxReconnectAttempts: 1,
    reconnectBaseDelayMs: 1,
    reconnectMaxDelayMs: 1,
    setTimeoutFn: timers.setTimeoutFn,
    clearTimeoutFn: timers.clearTimeoutFn,
  });
  const client = createMultiplayerClient({
    levelId: "starter-l",
    participantId: "student-bad-epoch",
    transport,
    now: fixedNow,
    onError: (error) => errors.push(error.message),
  });
  client.connect("wss://maze.example/socket");
  const first = FakeWebSocket.instances[0];
  first.open();
  first.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "stable-server-epoch",
    authority: "local",
  }), { direction: "server" }));
  client.joinRoom("room-bad-epoch");
  first.receive(encodeMultiplayerMessage(serverMessage("room.snapshot", {
    snapshot: {
      roomId: "room-bad-epoch",
      levelId: "starter-l",
      authority: "local",
      participants: [{ id: "student-bad-epoch", displayName: "student-bad-epoch", role: "student" }],
      robots: [],
      tick: 0,
      serverSequence: 2,
    },
  }, {
    roomId: "room-bad-epoch",
    sequence: 2,
    messageId: "stable-server:snapshot:2",
  }), { direction: "server" }));
  first.lose();
  timers.runNext();
  const second = FakeWebSocket.instances[1];
  second.open();
  second.receive(encodeMultiplayerMessage(serverMessage("welcome", {
    serverTime: fixedNow(),
    serverEpoch: "stable-server-epoch",
    authority: "local",
  }, {
    sequence: 1,
    messageId: "stable-server:bad-reset:1",
  }), { direction: "server" }));
  assert.equal(transport.state, MULTIPLAYER_TRANSPORT_STATES.CLOSED);
  assert.equal(client.session.mode, "offline");
  assert.equal(client.session.roomId, null);
  assert.equal(client.serverEpoch, null);
  assert.match(errors.at(-1), /same server epoch must continue/);
  assert.deepEqual(
    second.sent.map((text) => decodeMultiplayerMessage(text, { direction: "client" }).type),
    ["hello"],
    "the invalid welcome never triggers a room rejoin",
  );
  client.destroy();
}

// The retry cap applies to one uninterrupted outage; sockets that never open do
// not reset that budget.
{
  FakeWebSocket.instances = [];
  const timers = fakeTimers();
  const transport = new WebSocketTransport({
    WebSocketImpl: FakeWebSocket,
    baseUrl: "https://maze.example/",
    maxReconnectAttempts: 2,
    reconnectBaseDelayMs: 10,
    reconnectMaxDelayMs: 20,
    setTimeoutFn: timers.setTimeoutFn,
    clearTimeoutFn: timers.clearTimeoutFn,
  });
  transport.connect("wss://maze.example/socket");
  FakeWebSocket.instances[0].lose();
  assert.equal(timers.runNext(), 10);
  FakeWebSocket.instances[1].lose();
  assert.equal(timers.runNext(), 20);
  FakeWebSocket.instances[2].lose();
  assert.equal(transport.state, MULTIPLAYER_TRANSPORT_STATES.CLOSED);
  assert.equal(timers.size, 0);
  assert.equal(FakeWebSocket.instances.length, 3);
}

// Invalid/non-text inbound frames are fatal and do not enter a reconnect loop.
{
  FakeWebSocket.instances = [];
  const timers = fakeTimers();
  const errors = [];
  const transport = new WebSocketTransport({
    WebSocketImpl: FakeWebSocket,
    baseUrl: "https://maze.example/",
    maxReconnectAttempts: 3,
    reconnectBaseDelayMs: 1,
    reconnectMaxDelayMs: 4,
    setTimeoutFn: timers.setTimeoutFn,
    clearTimeoutFn: timers.clearTimeoutFn,
  });
  transport.subscribe((event) => {
    if (event.type === "error") errors.push(event);
  });
  transport.connect("wss://maze.example/socket");
  const socket = FakeWebSocket.instances[0];
  socket.open();
  socket.receive(new Uint8Array([1, 2, 3]));
  assert.equal(errors.length, 1);
  assert.equal(errors[0].fatal, true);
  assert.equal(transport.state, MULTIPLAYER_TRANSPORT_STATES.CLOSED);
  assert.equal(timers.size, 0);
}

console.log("PASS multiplayer protocol, offline/loopback/WebSocket transports, sequencing, privacy, and command authority");
