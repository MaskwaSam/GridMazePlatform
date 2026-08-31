import assert from "node:assert/strict";
import {
  applyDeadzone,
  createGamepadController,
  GamepadController,
  GAMEPAD_ACTIONS,
  GAMEPAD_STATUS,
  isGamepadSupported,
  selectGamepad,
  XBOX_ACTION_BINDINGS,
  XBOX_BUTTONS,
} from "../js/gamepad.js";

function button(pressed = false, value = pressed ? 1 : 0) {
  return { pressed, touched: pressed, value };
}

function makePad({ index = 0, id = `Xbox Controller ${index}`, mapping = "standard" } = {}) {
  return {
    index,
    id,
    mapping,
    connected: true,
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => button()),
  };
}

function makeEnvironment({ supported = true } = {}) {
  let pads = [];
  let nextFrameId = 1;
  const frames = new Map();
  const listeners = new Map();
  const cancelled = [];

  const navigator = supported ? { getGamepads: () => pads } : {};
  const window = {
    addEventListener(type, listener) {
      const entries = listeners.get(type) || new Set();
      entries.add(listener);
      listeners.set(type, entries);
    },
    removeEventListener(type, listener) {
      listeners.get(type)?.delete(listener);
    },
  };
  const requestAnimationFrame = (callback) => {
    const id = nextFrameId++;
    frames.set(id, callback);
    return id;
  };
  const cancelAnimationFrame = (id) => {
    cancelled.push(id);
    frames.delete(id);
  };

  return {
    navigator,
    window,
    requestAnimationFrame,
    cancelAnimationFrame,
    cancelled,
    setPads(nextPads) { pads = nextPads; },
    fire(type, gamepad) {
      for (const listener of [...(listeners.get(type) || [])]) listener({ gamepad });
    },
    frame() {
      const entry = frames.entries().next().value;
      assert.ok(entry, "expected a pending animation frame");
      const [id, callback] = entry;
      frames.delete(id);
      callback(performance.now());
    },
    pendingFrames() { return frames.size; },
    listenerCount(type) { return listeners.get(type)?.size || 0; },
  };
}

function createHarness(environment = makeEnvironment(), overrides = {}) {
  const actions = [];
  const statuses = [];
  const controller = createGamepadController({
    navigator: environment.navigator,
    window: environment.window,
    requestAnimationFrame: environment.requestAnimationFrame,
    cancelAnimationFrame: environment.cancelAnimationFrame,
    onAction: (action, detail) => actions.push({ action, detail }),
    onStatus: (status) => statuses.push(status),
    ...overrides,
  });
  return { controller, environment, actions, statuses };
}

// Public helpers and immutable mapping contract.
assert.equal(isGamepadSupported({ getGamepads() {} }), true);
assert.equal(isGamepadSupported({}), false);
assert.equal(isGamepadSupported(null), false);
assert.equal(XBOX_ACTION_BINDINGS.length, 10);
assert.equal(XBOX_ACTION_BINDINGS.find(({ button: index }) => index === XBOX_BUTTONS.A).action, GAMEPAD_ACTIONS.PRIMARY);
assert.equal(Object.isFrozen(XBOX_ACTION_BINDINGS), true);

const fallback = makePad({ index: 0, mapping: "" });
const standard = makePad({ index: 2, mapping: "standard" });
assert.equal(selectGamepad([fallback, null, standard]), standard, "standard mapping has priority");
assert.equal(selectGamepad([fallback]), fallback, "a connected non-standard controller is a fallback");
fallback.connected = false;
assert.equal(selectGamepad([fallback]), null);

assert.equal(applyDeadzone(0.1), 0);
assert.equal(applyDeadzone(-0.15), 0);
assert.equal(applyDeadzone(1), 1);
assert.equal(applyDeadzone(-1), -1);
assert.ok(Math.abs(applyDeadzone(0.575) - 0.5) < 1e-12);
assert.ok(Math.abs(applyDeadzone(-0.575) + 0.5) < 1e-12);
assert.equal(applyDeadzone(4), 1, "axis values are clamped");
assert.equal(applyDeadzone(Number.NaN), 0);
assert.equal(applyDeadzone(0.5, 2), 0, "deadzone values are clamped");

// Opt-in lifecycle: no listeners or frame before enable, then exactly one of each.
{
  const { controller, environment, statuses } = createHarness();
  assert.ok(controller instanceof GamepadController);
  assert.equal(controller.enabled, false);
  assert.equal(controller.status.state, GAMEPAD_STATUS.DISABLED);
  assert.equal(controller.status.supported, true);
  assert.equal(environment.pendingFrames(), 0);
  assert.equal(environment.listenerCount("gamepadconnected"), 0);

  assert.equal(controller.setEnabled(true), true);
  assert.equal(environment.pendingFrames(), 1);
  assert.equal(environment.listenerCount("gamepadconnected"), 1);
  assert.equal(environment.listenerCount("gamepaddisconnected"), 1);
  assert.equal(controller.status.state, GAMEPAD_STATUS.SEARCHING);
  controller.setEnabled(true);
  assert.equal(environment.pendingFrames(), 1, "idempotent enable does not duplicate polling");

  assert.equal(controller.setEnabled(false), false);
  assert.equal(environment.pendingFrames(), 0);
  assert.equal(environment.listenerCount("gamepadconnected"), 0);
  assert.equal(environment.listenerCount("gamepaddisconnected"), 0);
  assert.equal(controller.status.state, GAMEPAD_STATUS.DISABLED);
  assert.equal(statuses.at(-1).state, GAMEPAD_STATUS.DISABLED);
  assert.equal(environment.cancelled.length, 1);
}

// Unsupported environments report a useful state and never poll or listen.
{
  const environment = makeEnvironment({ supported: false });
  const { controller, statuses } = createHarness(environment);
  assert.equal(controller.status.state, GAMEPAD_STATUS.DISABLED);
  assert.equal(controller.status.supported, false);
  controller.setEnabled(true);
  assert.equal(controller.supported, false);
  assert.equal(controller.status.state, GAMEPAD_STATUS.UNSUPPORTED);
  assert.equal(controller.status.supported, false);
  assert.equal(environment.pendingFrames(), 0);
  assert.equal(environment.listenerCount("gamepadconnected"), 0);
  assert.deepEqual(statuses.map(({ state }) => state), [GAMEPAD_STATUS.DISABLED, GAMEPAD_STATUS.UNSUPPORTED]);
  controller.setEnabled(false);
  assert.equal(controller.status.state, GAMEPAD_STATUS.DISABLED);
  assert.equal(controller.status.supported, false);
}

// Rising edges fire once, a release rearms the button, and all mappings work.
{
  const environment = makeEnvironment();
  const pad = makePad({ id: "Xbox Wireless Controller" });
  environment.setPads([pad]);
  const { controller, actions } = createHarness(environment);
  controller.setEnabled(true);
  assert.equal(controller.status.state, GAMEPAD_STATUS.CONNECTED);
  assert.equal(controller.status.label, "Xbox Wireless Controller");

  const expectations = [
    [XBOX_BUTTONS.A, GAMEPAD_ACTIONS.PRIMARY],
    [XBOX_BUTTONS.B, GAMEPAD_ACTIONS.STOP],
    [XBOX_BUTTONS.X, GAMEPAD_ACTIONS.RESET],
    [XBOX_BUTTONS.Y, GAMEPAD_ACTIONS.TOGGLE_EDITOR],
    [XBOX_BUTTONS.VIEW, GAMEPAD_ACTIONS.ATTEMPTS],
    [XBOX_BUTTONS.MENU, GAMEPAD_ACTIONS.SETTINGS],
    [XBOX_BUTTONS.LEFT_BUMPER, GAMEPAD_ACTIONS.PREVIOUS_LEVEL],
    [XBOX_BUTTONS.RIGHT_BUMPER, GAMEPAD_ACTIONS.NEXT_LEVEL],
    [XBOX_BUTTONS.DPAD_LEFT, GAMEPAD_ACTIONS.PREVIOUS_LEVEL],
    [XBOX_BUTTONS.DPAD_RIGHT, GAMEPAD_ACTIONS.NEXT_LEVEL],
  ];
  for (const [buttonIndex, expectedAction] of expectations) {
    pad.buttons[buttonIndex] = button(true);
    environment.frame();
    assert.equal(actions.at(-1).action, expectedAction);
    const count = actions.length;
    environment.frame();
    assert.equal(actions.length, count, "a held button must not repeat");
    pad.buttons[buttonIndex] = button(false);
    environment.frame();
  }
  assert.equal(actions.length, expectations.length);

  pad.buttons[XBOX_BUTTONS.A] = button(false, 0.8);
  environment.frame();
  assert.equal(actions.at(-1).action, GAMEPAD_ACTIONS.PRIMARY, "analogue button values over 0.5 count as pressed");
  assert.deepEqual(actions.at(-1).detail.buttonIndices, [XBOX_BUTTONS.A]);
}

// Duplicate physical bindings collapse to one semantic action per frame.
{
  const environment = makeEnvironment();
  const pad = makePad();
  environment.setPads([pad]);
  const { controller, actions } = createHarness(environment);
  controller.setEnabled(true);
  pad.buttons[XBOX_BUTTONS.LEFT_BUMPER] = button(true);
  pad.buttons[XBOX_BUTTONS.DPAD_LEFT] = button(true);
  environment.frame();
  assert.equal(actions.length, 1);
  assert.equal(actions[0].action, GAMEPAD_ACTIONS.PREVIOUS_LEVEL);
  assert.deepEqual(actions[0].detail.buttonIndices, [XBOX_BUTTONS.LEFT_BUMPER, XBOX_BUTTONS.DPAD_LEFT]);
  environment.frame();
  assert.equal(actions.length, 1);

  pad.buttons[XBOX_BUTTONS.LEFT_BUMPER] = button(false);
  environment.frame();
  assert.equal(actions.length, 1, "an equivalent held binding keeps the logical action active");
  pad.buttons[XBOX_BUTTONS.DPAD_LEFT] = button(false);
  environment.frame();
  pad.buttons[XBOX_BUTTONS.LEFT_BUMPER] = button(true);
  environment.frame();
  assert.equal(actions.length, 2, "releasing every equivalent binding rearms the action");
  pad.buttons[XBOX_BUTTONS.DPAD_LEFT] = button(true);
  environment.frame();
  assert.equal(actions.length, 2, "staggered equivalent presses do not duplicate the action");

  pad.buttons[XBOX_BUTTONS.LEFT_BUMPER] = button(false);
  pad.buttons[XBOX_BUTTONS.DPAD_LEFT] = button(false);
  environment.frame();
  pad.buttons[XBOX_BUTTONS.RIGHT_BUMPER] = button(true);
  environment.frame();
  pad.buttons[XBOX_BUTTONS.DPAD_RIGHT] = button(true);
  environment.frame();
  assert.equal(actions.at(-1).action, GAMEPAD_ACTIONS.NEXT_LEVEL);
  assert.equal(actions.filter(({ action }) => action === GAMEPAD_ACTIONS.NEXT_LEVEL).length, 1);
}

// Input gates suppress an edge and do not replay it while the button stays held.
{
  const environment = makeEnvironment();
  const pad = makePad();
  environment.setPads([pad]);
  let allow = false;
  const gated = [];
  const { controller } = createHarness(environment, {
    shouldHandleInput: (action) => allow && action === GAMEPAD_ACTIONS.PRIMARY,
    onAction: (action) => gated.push(action),
  });
  controller.setEnabled(true);
  pad.buttons[XBOX_BUTTONS.A] = button(true);
  environment.frame();
  allow = true;
  environment.frame();
  assert.deepEqual(gated, [], "a blocked held press is consumed");
  pad.buttons[XBOX_BUTTONS.A] = button(false);
  environment.frame();
  pad.buttons[XBOX_BUTTONS.A] = button(true);
  environment.frame();
  assert.deepEqual(gated, [GAMEPAD_ACTIONS.PRIMARY]);
}

// Connect, disconnect, and reconnect update status and reset edge state.
{
  const environment = makeEnvironment();
  const pad = makePad({ index: 3, id: "  Classroom Xbox Pad  " });
  const { controller, actions, statuses } = createHarness(environment);
  controller.setEnabled(true);
  environment.setPads([null, null, null, pad]);
  environment.fire("gamepadconnected", pad);
  assert.equal(controller.status.state, GAMEPAD_STATUS.CONNECTED);
  assert.equal(controller.status.label, "Classroom Xbox Pad");
  assert.equal(controller.status.gamepadIndex, 3);

  pad.buttons[XBOX_BUTTONS.A] = button(true);
  environment.frame();
  assert.equal(actions.length, 1);
  pad.connected = false;
  environment.setPads([]);
  environment.fire("gamepaddisconnected", pad);
  assert.equal(controller.status.state, GAMEPAD_STATUS.DISCONNECTED);
  assert.equal(controller.status.label, "Classroom Xbox Pad");
  environment.frame();
  assert.equal(controller.status.state, GAMEPAD_STATUS.SEARCHING);

  const replacement = makePad({ index: 1, id: "Replacement", mapping: "" });
  replacement.buttons[XBOX_BUTTONS.A] = button(true);
  environment.setPads([null, replacement]);
  environment.fire("gamepadconnected", replacement);
  assert.equal(controller.status.state, GAMEPAD_STATUS.CONNECTED);
  assert.equal(controller.status.label, "Replacement");
  assert.equal(actions.length, 2, "the replacement controller starts with fresh edge state");
  assert.ok(statuses.some(({ state }) => state === GAMEPAD_STATUS.DISCONNECTED));
}

// Disable and destroy suppress input, detach listeners, and cancel pending work.
{
  const environment = makeEnvironment();
  const pad = makePad();
  environment.setPads([pad]);
  const { controller, actions } = createHarness(environment);
  controller.setEnabled(true);
  controller.setEnabled(false);
  pad.buttons[XBOX_BUTTONS.A] = button(true);
  environment.fire("gamepadconnected", pad);
  assert.equal(actions.length, 0);

  controller.setEnabled(true);
  assert.equal(environment.pendingFrames(), 1);
  controller.destroy();
  assert.equal(controller.enabled, false);
  assert.equal(environment.pendingFrames(), 0);
  assert.equal(environment.listenerCount("gamepadconnected"), 0);
  assert.equal(environment.listenerCount("gamepaddisconnected"), 0);
  assert.equal(controller.setEnabled(true), false, "a destroyed adapter cannot restart");
  controller.destroy();
}

// Consumer callback failures do not stop polling or future actions.
{
  const environment = makeEnvironment();
  const pad = makePad();
  environment.setPads([pad]);
  const controller = createGamepadController({
    navigator: environment.navigator,
    window: environment.window,
    requestAnimationFrame: environment.requestAnimationFrame,
    cancelAnimationFrame: environment.cancelAnimationFrame,
    onStatus() { throw new Error("render failed"); },
    onAction() { throw new Error("handler failed"); },
  });
  controller.setEnabled(true);
  pad.buttons[XBOX_BUTTONS.A] = button(true);
  environment.frame();
  assert.equal(environment.pendingFrames(), 1);
}

console.log("PASS gamepad adapter lifecycle, mappings, edge handling, gating, reconnect, and deadzone");
