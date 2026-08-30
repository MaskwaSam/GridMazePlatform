import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const deployDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(deployDir, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

const checks = [];
function check(name, callback) {
  try {
    callback();
    checks.push({ name, ok: true });
  } catch (error) {
    checks.push({ name, ok: false, error });
  }
}

function runtimeFiles() {
  const explicit = [
    "index.html", "styles.css", "icon.svg", "manifest.webmanifest",
    "service-worker.js", "THIRD_PARTY_NOTICES.md",
  ];
  const directories = ["js", "levels", "assets/stl", "vendor"];
  const files = [...explicit];
  for (const directory of directories) {
    const visit = (current) => {
      for (const entry of fs.readdirSync(path.join(root, "game", current), { withFileTypes: true })) {
        const relative = path.posix.join(current, entry.name);
        if (entry.isSymbolicLink()) throw new Error(`runtime symlink is not allowed: ${relative}`);
        if (entry.isDirectory()) visit(relative);
        else if (entry.isFile()) files.push(relative);
      }
    };
    visit(directory);
  }
  return files.sort();
}

function runtimeDigest() {
  const inventory = runtimeFiles().map((relative) => {
    const digest = createHash("sha256").update(fs.readFileSync(path.join(root, "game", relative))).digest("hex");
    return `${digest}  ${relative}\n`;
  }).join("");
  return createHash("sha256").update(inventory).digest("hex");
}

check("runtime payload is explicit, complete, and symlink-free", () => {
  const files = runtimeFiles();
  const actualFiles = [];
  const visit = (current = "") => {
    for (const entry of fs.readdirSync(path.join(root, "game", current), { withFileTypes: true })) {
      const relative = path.posix.join(current, entry.name);
      if (relative === "README.md" || relative === "tests") continue;
      if (entry.isSymbolicLink()) throw new Error(`runtime symlink is not allowed: ${relative}`);
      if (entry.isDirectory()) visit(relative);
      else if (entry.isFile()) actualFiles.push(relative);
    }
  };
  visit();
  assert.deepEqual(actualFiles.sort(), files, "undeclared game files would escape the runtime digest");
  for (const required of [
    "index.html", "service-worker.js", "manifest.webmanifest",
    "js/main.js", "levels/grand-tour.json",
    "assets/stl/maze_piece_straight_v1.stl",
    "vendor/pyodide/pyodide.asm.wasm",
    "vendor/licenses/Pyodide-MPL-2.0.txt",
  ]) assert.ok(files.includes(required), `missing ${required}`);
  assert.ok(!files.some((file) => file.startsWith("tests/")));
  assert.ok(!files.includes("README.md"));
});

check("Docker build is pinned, identity-bound, non-root, and excludes development files", () => {
  const dockerfile = read("deploy/Dockerfile");
  assert.match(dockerfile, /^FROM nginx:stable-alpine@sha256:[0-9a-f]{64}$/m);
  assert.match(dockerfile, /ARG MAZELAB_GIT_COMMIT/);
  assert.match(dockerfile, /ARG MAZELAB_RUNTIME_SHA256/);
  assert.match(dockerfile, /ARG MAZELAB_SOURCE_ARCHIVE_SHA256/);
  assert.match(dockerfile, /compute-mazelab-runtime-sha256/);
  assert.doesNotMatch(dockerfile, /^COPY game \/tmp\/mazelab-game$/m);
  assert.match(dockerfile, /^COPY game\/js\/ \/tmp\/mazelab-game\/js\/$/m);
  assert.match(dockerfile, /test ! -e \/tmp\/mazelab-game\/tests/);
  assert.match(dockerfile, /USER 101:101/);
  const dockerignore = read(".dockerignore");
  assert.match(dockerignore, /^\*$/m);
  assert.match(dockerignore, /^game\/tests\/$/m);
  assert.match(dockerignore, /^game\/README\.md$/m);
});

check("Compose exposes only the isolated Docker service and network", () => {
  const compose = read("deploy/compose.yaml");
  assert.match(compose, /^name: mazelab$/m);
  assert.match(compose, /^  mazelab:$/m);
  assert.match(compose, /read_only: true/);
  assert.match(compose, /cap_drop:\n      - ALL/);
  assert.match(compose, /no-new-privileges:true/);
  assert.match(compose, /expose:\n      - "8080"/);
  assert.doesNotMatch(compose, /^\s+ports:/m);
  assert.match(compose, /name: mazelab_edge/);
  assert.match(compose, /external: true/);
  assert.match(compose, /aliases:\n          - mazelab/);
  assert.match(compose, /Host: mazelab\.spatterson\.ca/);
});

check("NGINX serves only the Maze Lab host with PWA and WebAssembly types", () => {
  const nginx = read("deploy/nginx.conf");
  assert.match(nginx, /listen 8080 default_server/);
  assert.match(nginx, /server_name _;[\s\S]*?return 444;/);
  assert.match(nginx, /server_name mazelab\.spatterson\.ca/);
  assert.match(nginx, /location = \/service-worker\.js/);
  assert.match(nginx, /Service-Worker-Allowed "\/"/);
  assert.match(nginx, /location = \/manifest\.webmanifest/);
  assert.match(nginx, /application\/manifest\+json/);
  assert.match(nginx, /try_files \$uri =404/);
  assert.doesNotMatch(nginx, /try_files \$uri \/index\.html/);
});

check("security policy permits the local Python worker but blocks external origins", () => {
  const headers = read("deploy/security-headers.conf");
  const workerHeaders = read("deploy/worker-security-headers.conf");
  assert.match(headers, /default-src 'self'/);
  assert.doesNotMatch(headers, /'unsafe-eval'/);
  assert.doesNotMatch(headers, /'wasm-unsafe-eval'/);
  assert.match(headers, /worker-src 'self'/);
  assert.match(headers, /connect-src 'self'/);
  assert.match(headers, /frame-ancestors 'none'/);
  assert.match(headers, /X-Content-Type-Options "nosniff"/);
  assert.match(headers, /X-Maskwa-Maze-Lab-Production "1"/);
  assert.match(workerHeaders, /script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'/);
  assert.match(read("deploy/nginx.conf"), /location = \/js\/python-worker\.js[\s\S]*mazelab-worker-security\.conf/);
});

const failed = checks.filter((entry) => !entry.ok);
for (const entry of checks) {
  if (entry.ok) console.log(`✓ ${entry.name}`);
  else console.error(`✗ ${entry.name}: ${entry.error.message}`);
}
console.log(`Runtime SHA-256: ${runtimeDigest()}`);
console.log(`${checks.length - failed.length}/${checks.length} deployment checks passed`);
if (failed.length) process.exitCode = 1;
