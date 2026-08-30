/* global loadPyodide */
"use strict";

// Student Python runs only in this dedicated worker. The main page exposes no
// objects to it; every simulator operation travels through this allowlisted RPC.
const ALLOWED_RPC = new Set([
  "roll", "spin", "wait", "set_heading", "set_speed", "stop_roll",
  "set_main_led", "set_matrix_pixel", "clear_matrix",
  "get_heading", "get_speed", "get_location_x", "get_location_y",
]);

let pyodide = null;
let initialization = null;
let nextRpcId = 1;
const pendingRpc = new Map();

function sendRobotRpc(method, ...args) {
  if (!ALLOWED_RPC.has(method)) {
    return Promise.reject(new Error(`Robot command not allowed: ${method}`));
  }
  const id = nextRpcId++;
  return new Promise((resolve, reject) => {
    pendingRpc.set(id, { resolve, reject });
    self.postMessage({ type: "rpc", id, method, args });
  });
}

function emitLog(...values) {
  self.postMessage({
    type: "log",
    text: values.map((value) => String(value)).join(" ").slice(0, 2000),
  });
}

async function initialize() {
  if (pyodide) return pyodide;
  if (initialization) return initialization;
  initialization = (async () => {
    const pyodideRoot = new URL("../vendor/pyodide/", self.location.href).href;
    importScripts(`${pyodideRoot}pyodide.js`);
    pyodide = await loadPyodide({ indexURL: pyodideRoot });
    // Pyodide's `js` module reflects the worker global scope. Keep the bridge
    // private by rejecting student imports and attribute access below.
    self.__robot_rpc_js = sendRobotRpc;
    self.__emit_log_js = emitLog;
    await pyodide.runPythonAsync(`
import ast as __ast
import inspect as __inspect
from js import __robot_rpc_js, __emit_log_js

_FORBIDDEN_NODES = (
    __ast.Import, __ast.ImportFrom, __ast.Attribute, __ast.ClassDef,
    __ast.Global, __ast.Nonlocal, __ast.With, __ast.AsyncWith,
    __ast.Delete,
)

class __StudentGuard(__ast.NodeVisitor):
    def generic_visit(self, node):
        if isinstance(node, _FORBIDDEN_NODES):
            raise SyntaxError(f"{type(node).__name__} is not available in student programs")
        return super().generic_visit(node)

    def visit_Name(self, node):
        if node.id.startswith("_"):
            raise SyntaxError("Names beginning with an underscore are reserved")
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, (bytes, complex)):
            raise SyntaxError("That literal type is not available")
        return self.generic_visit(node)

async def __rpc(method, *args):
    return await __robot_rpc_js(method, *args)

async def roll(heading, speed, seconds):
    return await __rpc("roll", heading, speed, seconds)

async def spin(degrees, seconds=0.5):
    return await __rpc("spin", degrees, seconds)

async def wait(seconds):
    return await __rpc("wait", seconds)

async def set_heading(heading):
    return await __rpc("set_heading", heading)

async def set_speed(speed):
    return await __rpc("set_speed", speed)

async def stop_roll():
    return await __rpc("stop_roll")

async def set_main_led(*colour):
    return await __rpc("set_main_led", *colour)

async def set_matrix_pixel(x, y, colour):
    return await __rpc("set_matrix_pixel", x, y, colour)

async def clear_matrix():
    return await __rpc("clear_matrix")

async def get_heading():
    return await __rpc("get_heading")

async def get_speed():
    return await __rpc("get_speed")

async def get_location_x():
    return await __rpc("get_location_x")

async def get_location_y():
    return await __rpc("get_location_y")

def __safe_print(*values, sep=" ", end="\\n"):
    text = sep.join(str(value) for value in values) + end
    __emit_log_js(text.rstrip("\\n"))

__PUBLIC_API = {
    "roll": roll,
    "spin": spin,
    "wait": wait,
    "set_heading": set_heading,
    "set_speed": set_speed,
    "stop_roll": stop_roll,
    "set_main_led": set_main_led,
    "set_matrix_pixel": set_matrix_pixel,
    "clear_matrix": clear_matrix,
    "get_heading": get_heading,
    "get_speed": get_speed,
    "get_location_x": get_location_x,
    "get_location_y": get_location_y,
}

__SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool,
    "enumerate": enumerate, "float": float, "int": int, "len": len,
    "list": list, "max": max, "min": min, "print": __safe_print,
    "range": range, "round": round, "str": str, "sum": sum,
    "tuple": tuple, "zip": zip,
    "Exception": Exception, "ValueError": ValueError,
}

async def __run_student(source):
    if len(source) > 20000:
        raise ValueError("Program is longer than the 20,000 character limit")
    tree = __ast.parse(source, filename="student_program.py", mode="exec")
    __StudentGuard().visit(tree)
    env = {"__builtins__": __SAFE_BUILTINS, "__name__": "student_program"}
    env.update(__PUBLIC_API)
    code = compile(
        tree,
        "student_program.py",
        "exec",
        flags=__ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        dont_inherit=True,
    )
    result = eval(code, env, env)
    if __inspect.isawaitable(result):
        await result
`);
    self.postMessage({ type: "ready", pythonVersion: pyodide.runPython("__import__('sys').version.split()[0]") });
    return pyodide;
  })();
  return initialization;
}

async function runProgram(message) {
  try {
    await initialize();
    pyodide.globals.set("__student_source", String(message.source || ""));
    await pyodide.runPythonAsync("await __run_student(__student_source)");
    pyodide.globals.delete("__student_source");
    self.postMessage({ type: "complete", runId: message.runId });
  } catch (error) {
    try { pyodide?.globals.delete("__student_source"); } catch { /* worker is about to report */ }
    self.postMessage({
      type: "programError",
      runId: message.runId,
      message: String(error?.message || error).replace(/^PythonError:\s*/, "").slice(0, 4000),
    });
  }
}

self.onmessage = (event) => {
  const message = event.data || {};
  if (message.type === "rpcResult") {
    const pending = pendingRpc.get(message.id);
    if (!pending) return;
    pendingRpc.delete(message.id);
    if (message.ok) pending.resolve(message.value);
    else pending.reject(new Error(message.error || "Robot command failed"));
    return;
  }
  if (message.type === "init") {
    initialize().catch((error) => {
      self.postMessage({ type: "bootError", message: String(error?.message || error).slice(0, 4000) });
    });
    return;
  }
  if (message.type === "run") void runProgram(message);
};
