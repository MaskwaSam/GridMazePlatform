import assert from "node:assert/strict";
import { PythonRuntime } from "../js/python-runtime.js";

class FakeWorker {
  static current = null;
  static autoReady = false;

  constructor() {
    this.listeners = new Map();
    this.messages = [];
    this.terminated = false;
    FakeWorker.current = this;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  postMessage(message) {
    this.messages.push(message);
    if (message.type === "init" && FakeWorker.autoReady) {
      queueMicrotask(() => this.emitMessage({ type: "ready", pythonVersion: "test" }));
    }
  }

  terminate() {
    this.terminated = true;
  }

  emitMessage(data) {
    for (const listener of this.listeners.get("message") || []) listener({ data });
  }

  emitError(message) {
    for (const listener of this.listeners.get("error") || []) listener({ message });
  }
}

globalThis.Worker = FakeWorker;

function createRuntime() {
  return new PythonRuntime({
    onRpc: async () => null,
    onLog: () => {},
    onState: () => {},
  });
}

async function rejectsQuickly(promise, pattern, timeoutMs = 250) {
  let timer;
  try {
    await Promise.race([
      assert.rejects(promise, pattern),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("Runtime promise did not reject promptly.")), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

FakeWorker.autoReady = false;
const bootRuntime = createRuntime();
const bootPromise = bootRuntime.prepare();
FakeWorker.current.emitError("Python worker script failed to load.");
await rejectsQuickly(bootPromise, /Python worker script failed to load/);
assert.equal(FakeWorker.current.terminated, true);
assert.equal(bootRuntime.worker, null);
assert.equal(bootRuntime.readyPromise, null);

FakeWorker.autoReady = true;
const timeoutRuntime = createRuntime();
timeoutRuntime.programTimeoutMs = 5;
await rejectsQuickly(
  timeoutRuntime.run("await wait(30)"),
  /Program stopped after the 25 second safety limit/,
);
assert.equal(FakeWorker.current.terminated, true);
assert.equal(timeoutRuntime.worker, null);
assert.equal(timeoutRuntime.runPromise, null);

FakeWorker.autoReady = true;
const crashRuntime = createRuntime();
const crashPromise = crashRuntime.run("await wait(1)");
while (!FakeWorker.current.messages.some((message) => message.type === "run")) await new Promise((resolve) => setTimeout(resolve, 0));
FakeWorker.current.emitError("Python worker crashed while running.");
await rejectsQuickly(crashPromise, /Python worker crashed while running/);
assert.equal(FakeWorker.current.terminated, true);
assert.equal(crashRuntime.worker, null);

console.log("PASS Python runtime rejects boot, timeout, and worker crashes promptly");
