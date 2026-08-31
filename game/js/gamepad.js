export const GAMEPAD_STATUS = Object.freeze({
  DISABLED: "disabled",
  UNSUPPORTED: "unsupported",
  SEARCHING: "searching",
  CONNECTED: "connected",
  DISCONNECTED: "disconnected",
});

export const GAMEPAD_ACTIONS = Object.freeze({
  PRIMARY: "primary",
  STOP: "stop",
  RESET: "reset",
  TOGGLE_EDITOR: "toggle-editor",
  ATTEMPTS: "attempts",
  SETTINGS: "settings",
  PREVIOUS_LEVEL: "previous-level",
  NEXT_LEVEL: "next-level",
});

export const XBOX_BUTTONS = Object.freeze({
  A: 0,
  B: 1,
  X: 2,
  Y: 3,
  LEFT_BUMPER: 4,
  RIGHT_BUMPER: 5,
  VIEW: 8,
  MENU: 9,
  DPAD_LEFT: 14,
  DPAD_RIGHT: 15,
});

export const XBOX_ACTION_BINDINGS = Object.freeze([
  Object.freeze({ button: XBOX_BUTTONS.A, action: GAMEPAD_ACTIONS.PRIMARY }),
  Object.freeze({ button: XBOX_BUTTONS.B, action: GAMEPAD_ACTIONS.STOP }),
  Object.freeze({ button: XBOX_BUTTONS.X, action: GAMEPAD_ACTIONS.RESET }),
  Object.freeze({ button: XBOX_BUTTONS.Y, action: GAMEPAD_ACTIONS.TOGGLE_EDITOR }),
  Object.freeze({ button: XBOX_BUTTONS.VIEW, action: GAMEPAD_ACTIONS.ATTEMPTS }),
  Object.freeze({ button: XBOX_BUTTONS.MENU, action: GAMEPAD_ACTIONS.SETTINGS }),
  Object.freeze({ button: XBOX_BUTTONS.LEFT_BUMPER, action: GAMEPAD_ACTIONS.PREVIOUS_LEVEL }),
  Object.freeze({ button: XBOX_BUTTONS.DPAD_LEFT, action: GAMEPAD_ACTIONS.PREVIOUS_LEVEL }),
  Object.freeze({ button: XBOX_BUTTONS.RIGHT_BUMPER, action: GAMEPAD_ACTIONS.NEXT_LEVEL }),
  Object.freeze({ button: XBOX_BUTTONS.DPAD_RIGHT, action: GAMEPAD_ACTIONS.NEXT_LEVEL }),
]);

const BUTTON_VALUE_THRESHOLD = 0.5;

function noop() {}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

/**
 * Applies a scalar deadzone and rescales the remaining range back to 0..1.
 * This is exported for future camera/analogue-stick controls; movement is not
 * driven by analogue input in the current coding game.
 */
export function applyDeadzone(value, deadzone = 0.15) {
  const numericValue = Number.isFinite(value) ? clamp(value, -1, 1) : 0;
  const numericDeadzone = Number.isFinite(deadzone) ? clamp(deadzone, 0, 0.99) : 0.15;
  const magnitude = Math.abs(numericValue);
  if (magnitude <= numericDeadzone) return 0;
  return Math.sign(numericValue) * ((magnitude - numericDeadzone) / (1 - numericDeadzone));
}

export function isGamepadSupported(navigatorLike = globalThis.navigator) {
  return Boolean(navigatorLike && typeof navigatorLike.getGamepads === "function");
}

function isConnected(gamepad) {
  return Boolean(gamepad) && gamepad.connected !== false;
}

/** Selects the first standard-mapped controller, or the first connected fallback. */
export function selectGamepad(gamepads) {
  const connected = Array.from(gamepads || []).filter(isConnected);
  return connected.find((gamepad) => gamepad.mapping === "standard") || connected[0] || null;
}

function isButtonPressed(button) {
  if (typeof button === "number") return button > BUTTON_VALUE_THRESHOLD;
  return Boolean(button && (button.pressed || Number(button.value) > BUTTON_VALUE_THRESHOLD));
}

function gamepadLabel(gamepad) {
  const id = typeof gamepad?.id === "string" ? gamepad.id.trim() : "";
  return id || `Gamepad ${Number(gamepad?.index ?? 0) + 1}`;
}

function makeStatus(state, supported, gamepad = null) {
  return Object.freeze({
    state,
    enabled: state !== GAMEPAD_STATUS.DISABLED,
    supported: Boolean(supported),
    label: gamepad ? gamepadLabel(gamepad) : null,
    gamepadIndex: Number.isInteger(gamepad?.index) ? gamepad.index : null,
    mapping: typeof gamepad?.mapping === "string" && gamepad.mapping ? gamepad.mapping : null,
  });
}

function statusesMatch(left, right) {
  return Boolean(left && right)
    && left.state === right.state
    && left.enabled === right.enabled
    && left.supported === right.supported
    && left.label === right.label
    && left.gamepadIndex === right.gamepadIndex
    && left.mapping === right.mapping;
}

/**
 * Dependency-injected Gamepad API adapter. It emits semantic actions only and
 * deliberately has no knowledge of DOM elements, physics, storage, or network.
 */
export class GamepadController {
  constructor({
    navigator: navigatorLike = globalThis.navigator,
    window: windowLike = globalThis.window,
    requestAnimationFrame = windowLike?.requestAnimationFrame?.bind(windowLike),
    cancelAnimationFrame = windowLike?.cancelAnimationFrame?.bind(windowLike),
    onAction = noop,
    onStatus = noop,
    shouldHandleInput = () => true,
  } = {}) {
    this.navigator = navigatorLike;
    this.window = windowLike;
    this.requestAnimationFrame = requestAnimationFrame;
    this.cancelAnimationFrame = cancelAnimationFrame || noop;
    this.onAction = typeof onAction === "function" ? onAction : noop;
    this.onStatus = typeof onStatus === "function" ? onStatus : noop;
    this.shouldHandleInput = typeof shouldHandleInput === "function" ? shouldHandleInput : () => true;

    this.enabled = false;
    this.destroyed = false;
    this.frameId = null;
    this.activeGamepad = null;
    this.pressedButtons = new Set();
    this.activeActions = new Set();
    this.listenersAttached = false;
    this.lastStatus = null;

    this.handleConnected = this.handleConnected.bind(this);
    this.handleDisconnected = this.handleDisconnected.bind(this);
    this.tick = this.tick.bind(this);

    this.emitStatus(GAMEPAD_STATUS.DISABLED);
  }

  get supported() {
    return isGamepadSupported(this.navigator)
      && typeof this.requestAnimationFrame === "function";
  }

  get status() {
    return this.lastStatus;
  }

  setEnabled(nextEnabled) {
    if (this.destroyed) return false;
    const enabled = Boolean(nextEnabled);
    if (enabled === this.enabled) return this.enabled;

    this.enabled = enabled;
    this.pressedButtons.clear();
    this.activeActions.clear();

    if (!enabled) {
      this.stopPolling();
      this.detachListeners();
      this.activeGamepad = null;
      this.emitStatus(GAMEPAD_STATUS.DISABLED);
      return false;
    }

    if (!this.supported) {
      this.emitStatus(GAMEPAD_STATUS.UNSUPPORTED);
      return true;
    }

    this.attachListeners();
    this.emitStatus(GAMEPAD_STATUS.SEARCHING);
    this.poll();
    this.schedulePoll();
    return true;
  }

  destroy() {
    if (this.destroyed) return;
    this.enabled = false;
    this.destroyed = true;
    this.stopPolling();
    this.detachListeners();
    this.activeGamepad = null;
    this.pressedButtons.clear();
    this.activeActions.clear();
    this.emitStatus(GAMEPAD_STATUS.DISABLED);
  }

  attachListeners() {
    if (this.listenersAttached || typeof this.window?.addEventListener !== "function") return;
    this.window.addEventListener("gamepadconnected", this.handleConnected);
    this.window.addEventListener("gamepaddisconnected", this.handleDisconnected);
    this.listenersAttached = true;
  }

  detachListeners() {
    if (!this.listenersAttached) return;
    if (typeof this.window?.removeEventListener === "function") {
      this.window.removeEventListener("gamepadconnected", this.handleConnected);
      this.window.removeEventListener("gamepaddisconnected", this.handleDisconnected);
    }
    this.listenersAttached = false;
  }

  handleConnected() {
    if (!this.enabled || this.destroyed) return;
    this.poll();
  }

  handleDisconnected(event) {
    if (!this.enabled || this.destroyed) return;
    const disconnected = event?.gamepad || null;
    if (!this.activeGamepad || disconnected?.index !== this.activeGamepad.index) return;
    const previous = this.activeGamepad;
    this.activeGamepad = null;
    this.pressedButtons.clear();
    this.activeActions.clear();
    this.emitStatus(GAMEPAD_STATUS.DISCONNECTED, disconnected || previous);
  }

  tick() {
    this.frameId = null;
    if (!this.enabled || this.destroyed) return;
    this.poll();
    this.schedulePoll();
  }

  schedulePoll() {
    if (!this.enabled || this.destroyed || this.frameId !== null) return;
    this.frameId = this.requestAnimationFrame(this.tick);
  }

  stopPolling() {
    if (this.frameId === null) return;
    this.cancelAnimationFrame(this.frameId);
    this.frameId = null;
  }

  readGamepads() {
    try {
      return this.navigator.getGamepads() || [];
    } catch {
      return [];
    }
  }

  poll() {
    if (!this.enabled || this.destroyed || !this.supported) return;
    const gamepad = selectGamepad(this.readGamepads());
    if (!gamepad) {
      this.activeGamepad = null;
      this.pressedButtons.clear();
      this.activeActions.clear();
      this.emitStatus(GAMEPAD_STATUS.SEARCHING);
      return;
    }

    const changedController = !this.activeGamepad || this.activeGamepad.index !== gamepad.index;
    this.activeGamepad = gamepad;
    if (changedController) {
      this.pressedButtons.clear();
      this.activeActions.clear();
    }
    this.emitStatus(GAMEPAD_STATUS.CONNECTED, gamepad);
    this.processButtons(gamepad);
  }

  processButtons(gamepad) {
    const nextPressed = new Set();
    const pressedByAction = new Map();

    for (const binding of XBOX_ACTION_BINDINGS) {
      if (!isButtonPressed(gamepad.buttons?.[binding.button])) continue;
      nextPressed.add(binding.button);
      const indices = pressedByAction.get(binding.action) || [];
      indices.push(binding.button);
      pressedByAction.set(binding.action, indices);
    }

    // Update before callbacks so a callback-triggered poll cannot repeat an edge.
    this.pressedButtons = nextPressed;
    const nextActiveActions = new Set(pressedByAction.keys());
    const risingByAction = [...pressedByAction]
      .filter(([action]) => !this.activeActions.has(action));
    this.activeActions = nextActiveActions;

    for (const [action, buttonIndices] of risingByAction) {
      const detail = Object.freeze({
        action,
        buttonIndices: Object.freeze([...buttonIndices]),
        gamepad: Object.freeze({
          id: gamepadLabel(gamepad),
          index: Number.isInteger(gamepad.index) ? gamepad.index : 0,
          mapping: typeof gamepad.mapping === "string" ? gamepad.mapping : "",
        }),
      });
      if (!this.safeShouldHandle(action, detail)) continue;
      this.safeNotifyAction(action, detail);
    }
  }

  safeShouldHandle(action, detail) {
    try {
      return Boolean(this.shouldHandleInput(action, detail));
    } catch {
      return false;
    }
  }

  safeNotifyAction(action, detail) {
    try {
      this.onAction(action, detail);
    } catch {
      // Consumer errors must not stop controller polling.
    }
  }

  emitStatus(state, gamepad = null) {
    const status = makeStatus(state, this.supported, gamepad);
    if (statusesMatch(status, this.lastStatus)) return;
    this.lastStatus = status;
    try {
      this.onStatus(status);
    } catch {
      // Status UI errors must not break the adapter lifecycle.
    }
  }
}

export function createGamepadController(options) {
  return new GamepadController(options);
}
