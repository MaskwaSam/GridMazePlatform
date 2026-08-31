import assert from "node:assert/strict";
import {
  GAME_ACTION_KINDS,
  GameActionRouter,
  isShareableGameAction,
  normalizeGameAction,
} from "../js/game-actions.js";

const fixed = {
  now: () => 1234,
  idFactory: () => "action-test-1",
};

const normalized = normalizeGameAction(GAME_ACTION_KINDS.RUN, { source: "gamepad", ...fixed });
assert.deepEqual(normalized, {
  id: "action-test-1",
  kind: "run",
  source: "gamepad",
  createdAt: 1234,
  payload: {},
});
assert.ok(Object.isFrozen(normalized));
assert.ok(Object.isFrozen(normalized.payload));

const select = normalizeGameAction({
  kind: GAME_ACTION_KINDS.SELECT_LEVEL,
  payload: { levelId: "mirror-left" },
}, fixed);
assert.equal(select.payload.levelId, "mirror-left");

for (const invalid of [
  null,
  { kind: "unknown" },
  { kind: GAME_ACTION_KINDS.RUN, payload: { extra: true } },
  { kind: GAME_ACTION_KINDS.SELECT_LEVEL, payload: {} },
  { kind: GAME_ACTION_KINDS.SELECT_LEVEL, payload: { levelId: "../bad" } },
  { kind: GAME_ACTION_KINDS.RUN, source: "network" },
  { kind: GAME_ACTION_KINDS.RUN, id: "bad id" },
]) {
  assert.throws(() => normalizeGameAction(invalid, fixed));
}

assert.equal(isShareableGameAction(GAME_ACTION_KINDS.RUN), true);
assert.equal(isShareableGameAction(GAME_ACTION_KINDS.OPEN_SETTINGS), false);

const observed = [];
const handled = [];
const failures = [];
const router = new GameActionRouter({ onError: (error, action) => failures.push([error.message, action.kind]) });
router.subscribe((action) => observed.push(action.kind));
router.register(GAME_ACTION_KINDS.RUN, async (action) => {
  handled.push(action.source);
  return "started";
});
assert.equal(await router.dispatch(GAME_ACTION_KINDS.RUN, { source: "ui", ...fixed }), "started");
assert.deepEqual(observed, ["run"]);
assert.deepEqual(handled, ["ui"]);

router.subscribe(() => { throw new Error("listener failed"); });
router.register(GAME_ACTION_KINDS.STOP, () => { throw new Error("handler failed"); });
await assert.rejects(router.dispatch(GAME_ACTION_KINDS.STOP, fixed), /handler failed/);
assert.deepEqual(observed, ["run"], "failed handlers are not published to listeners");
assert.deepEqual(failures, [
  ["handler failed", "stop"],
]);

router.register(GAME_ACTION_KINDS.RESET, () => false);
assert.equal(await router.dispatch(GAME_ACTION_KINDS.RESET, fixed), false);
assert.deepEqual(observed, ["run"], "rejected actions are not published to listeners");

router.register(GAME_ACTION_KINDS.RESET, () => true);
assert.equal(await router.dispatch(GAME_ACTION_KINDS.RESET, fixed), true);
assert.deepEqual(failures, [
  ["handler failed", "stop"],
  ["listener failed", "reset"],
]);

await assert.rejects(router.dispatch(GAME_ACTION_KINDS.TOGGLE_EDITOR, fixed), /No handler is registered/);
console.log("PASS game actions normalize, route, isolate UI-only actions, and surface failures");
