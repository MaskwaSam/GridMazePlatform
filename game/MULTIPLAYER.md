# Maskwa Maze Lab multiplayer contract

## Current release status

Maskwa Maze Lab is still an offline-first, single-student game. The production
container is static NGINX and does **not** expose `/ws`, create rooms, or send
student data to a server. The multiplayer modules in this release are a dormant,
tested client boundary for a later server implementation; they do not activate a
network connection by themselves.

This distinction is intentional. A classroom release must not quietly begin
transmitting student activity just because multiplayer-ready code is present.

## Client boundaries

- `js/game-actions.js` normalizes touch, mouse, keyboard, and controller workflow
  actions before the game handles them. Only placement, Run, Stop, Reset,
  Run-again, and maze-navigation actions are shareable. Settings, attempt-history
  views, and editor-mode changes remain device-local.
- `js/multiplayer-protocol.js` owns the version-1 wire envelope, strict message
  and payload validation, message-size limit, robot-command allowlist, and secure
  endpoint validation.
- `js/multiplayer-session.js` is the immutable room projection. It applies
  ordered server events, rejects duplicates, detects sequence gaps, and replaces
  state only from a validated room snapshot.
- `js/multiplayer-transport.js` provides an offline default, a deterministic
  loopback transport for two-client tests, and an explicitly activated WebSocket
  transport. The WebSocket class is not constructed and cannot reconnect until
  application code supplies a validated endpoint and calls `connect()`.
- `js/multiplayer-client.js` is the command-authority seam used by the Python
  runtime. Local simulation remains authoritative offline. A future room can
  opt into server command authority after the server confirms that authority.

The offline transport is the only production default. Reconnect never replays
robot commands because repeating a motion command after an uncertain disconnect
could produce a different maze result.

## Privacy contract

The future wire protocol may carry only normalized workflow intents, participant
display metadata, the selected level ID, bounded allowlisted robot commands,
and robot telemetry/state. It must never carry:

- Blockly workspace data or Python source;
- attempt-history code, notes, or outcomes;
- imported or exported project files;
- device settings, accessibility choices, or controller identity strings;
- browser-storage contents, filenames, or unrelated page data.

Those records remain local unless a later product decision introduces a clearly
labelled, separately consented classroom-storage feature.

## Version-1 message flow

Every envelope contains the fixed protocol name and version, a unique message ID,
participant ID, monotonic sequence, timestamp, optional room ID, and one strictly
validated payload. The maximum encoded message is 64 KiB. Server sequences are
scoped by a required opaque `serverEpoch`. A server must keep the epoch stable
while it can continue its sequence and must issue a new unpredictable epoch when
that sequence state resets, including after a non-persistent server restart.

1. The client opens a secure WebSocket and sends `hello`, including the paired
   `lastServerEpoch` and latest applied server sequence when reconnecting.
2. The first server frame must be `welcome`, which identifies the current
   `serverEpoch`. In the same epoch its sequence must continue exactly. A new
   epoch must start at sequence 1; the client first discards stale room state,
   deduplication IDs, synchronization state, and server authority. It then sends
   `room.join` for an explicitly chosen or reconnect-intended room and level.
3. The server returns a full `room.snapshot`. That snapshot establishes room
   membership, level, command authority, robots, tick, and server sequence.
4. Locally accepted shareable workflow input is sent as `action.intent`.
   Cancelled confirmations, failed preflight, and blocked controls emit nothing.
   Only the server can emit the ordered `action.commit` that other clients apply.
5. With server command authority, an allowlisted `robot.command` uses a unique
   request ID and resolves only from the matching `robot.result`. Robot state is
   published by the server as ordered `robot.state` messages.
6. Duplicate server sequences are ignored. A sequence gap causes `sync.request`;
   clients reject in-flight commands and wait for a fresh snapshot rather than
   guessing, sending more room input, or replaying commands.
7. `room.leave`, every socket close (including one being reconnected), an
   explicit endpoint replacement, and a server-to-local authority change return
   the client to local authority. Pending remote commands fail closed and are not
   replayed; late results from an old room membership are discarded. An explicit
   endpoint replacement also clears the prior room and server epoch before any
   new socket is constructed.

The server is authoritative for room membership, ordering, committed actions,
robot command execution, collision state, and goal state. Clients are renderers
and intent producers, not arbiters of another student's result.

## Future server and deployment requirements

The intended public endpoint is same-origin
`wss://mazelab.spatterson.ca/ws`. The client rejects every cross-origin endpoint
unless its exact WebSocket origin is supplied in an explicit allowlist. Local
development may use `ws://localhost` only from the matching localhost origin (or
an explicit development allowlist). It also rejects insecure non-localhost
WebSocket URLs and URLs containing embedded credentials or fragments.

The future server should be a separate least-privilege container on an internal
Compose network. NGINX can then proxy only `/ws` to that service with HTTP/1.1
upgrade headers and conservative timeouts. Keep the static app container
host-port-free. Do not overload the Cloudflare Tunnel route with a second public
hostname unless there is an explicit operational reason.

Before enabling `/ws`, the server and proxy release must prove all of the
following:

- HTTPS/WSS only in production, exact `Origin` allowlisting, no URL credentials,
  and short-lived unguessable room admission tokens;
- server-enforced student/teacher/observer roles and room membership on every
  message, with no trust in client-supplied authority;
- the same strict schema, command allowlist, 64 KiB message cap, participant cap,
  per-client and per-room rate limits, heartbeat timeout, and bounded queues;
- monotonic server sequences within a stable server epoch, a newly generated
  epoch whenever sequence state resets, idempotent message/request IDs,
  reconnect snapshot recovery, and no motion-command replay;
- no arbitrary Python execution on the server and no student code in application
  logs, metrics, traces, or crash reports;
- container health checks, resource limits, log limits, graceful drain, backup or
  explicit ephemeral-room policy, and a rollback that removes only `/ws` and its
  new service;
- two real Chromebook clients completing a room join, disconnect/reconnect,
  sequence-gap recovery, simultaneous action ordering, wall collision, and
  stopped-on-goal run without affecting offline play.

Until those gates pass, the public application remains single-student and the
offline transport remains the only enabled transport.
