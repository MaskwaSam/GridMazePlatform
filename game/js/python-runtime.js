const BOOT_TIMEOUT_MS = 45_000;
const PROGRAM_TIMEOUT_MS = 25_000;

export class PythonRuntime {
  constructor({ onRpc, onLog, onState }) {
    this.onRpc = onRpc;
    this.onLog = onLog;
    this.onState = onState;
    this.worker = null;
    this.readyPromise = null;
    this.bootReject = null;
    this.bootTimer = null;
    this.runPromise = null;
    this.runSequence = 0;
    this.programTimeoutMs = PROGRAM_TIMEOUT_MS;
  }

  async prepare() {
    if (this.readyPromise) return this.readyPromise;
    this.onState?.("loading");
    const worker = new Worker(new URL("./python-worker.js?v=36", import.meta.url));
    this.worker = worker;
    this.readyPromise = new Promise((resolve, reject) => {
      this.bootReject = reject;
      this.bootTimer = setTimeout(() => {
        this.terminate("Python took too long to load. Check that the game is served over HTTP.");
      }, BOOT_TIMEOUT_MS);
      worker.addEventListener("message", (event) => {
        const message = event.data || {};
        if (message.type === "ready") {
          clearTimeout(this.bootTimer);
          this.bootTimer = null;
          this.bootReject = null;
          this.onState?.("ready", message.pythonVersion);
          resolve(message.pythonVersion);
        } else if (message.type === "bootError") {
          this.terminate(message.message || "Python could not start.");
        }
      });
    });
    worker.addEventListener("message", (event) => void this.handleMessage(event.data || {}, worker));
    worker.addEventListener("error", (event) => {
      const error = new Error(event.message || "The Python worker stopped unexpectedly.");
      this.terminate(error.message);
    });
    worker.postMessage({ type: "init" });
    return this.readyPromise;
  }

  async run(source) {
    if (this.runPromise) throw new Error("A program is already running.");
    if (typeof source !== "string" || source.length > 20_000) {
      throw new Error("Programs must be 20,000 characters or shorter.");
    }
    await this.prepare();
    const runId = ++this.runSequence;
    this.onState?.("running");
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.terminate("Program stopped after the 25 second safety limit.");
      }, this.programTimeoutMs);
      this.runPromise = { runId, resolve, reject, timer };
      this.worker.postMessage({ type: "run", runId, source });
    });
  }

  async handleMessage(message, sourceWorker) {
    if (sourceWorker !== this.worker) return;
    if (message.type === "log") {
      this.onLog?.(message.text);
      return;
    }
    if (message.type === "rpc") {
      try {
        const value = await this.onRpc(message.method, Array.isArray(message.args) ? message.args : []);
        if (this.worker === sourceWorker) sourceWorker.postMessage({ type: "rpcResult", id: message.id, ok: true, value });
      } catch (error) {
        if (this.worker === sourceWorker) {
          sourceWorker.postMessage({ type: "rpcResult", id: message.id, ok: false, error: String(error?.message || error) });
        }
      }
      return;
    }
    if (message.runId !== this.runPromise?.runId) return;
    if (message.type === "complete") {
      const run = this.takeRun();
      this.onState?.("ready");
      run?.resolve();
    } else if (message.type === "programError") {
      const run = this.takeRun();
      this.onState?.("ready");
      run?.reject(new Error(message.message || "Python program failed."));
    }
  }

  takeRun() {
    const run = this.runPromise;
    if (run) clearTimeout(run.timer);
    this.runPromise = null;
    return run;
  }

  rejectRun(error) {
    const run = this.takeRun();
    run?.reject(error);
  }

  terminate(reason = "Program stopped.") {
    const run = this.takeRun();
    clearTimeout(this.bootTimer);
    this.bootTimer = null;
    const rejectBoot = this.bootReject;
    this.bootReject = null;
    this.worker?.terminate();
    this.worker = null;
    this.readyPromise = null;
    rejectBoot?.(new Error(reason));
    if (run) run.reject(new Error(reason));
    this.onState?.("stopped");
  }
}
