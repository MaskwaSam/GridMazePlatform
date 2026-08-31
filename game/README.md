# Maskwa Maze Lab — standalone Chromebook MVP

Maskwa Maze Lab is a static, self-hosted Three.js game with seven progressively
longer printable-piece mazes. A student chooses a level, places the sphere robot
anywhere collision-safe on the highlighted starting piece, writes a program with
Blockly or Python, presses Run,
and watches the robot attempt the same deterministic maze every time. The
robot accelerates, rolls with momentum, actively brakes, and rebounds from maze
walls while continuing the student's command. Its white band and orange tracker
rotate with the physical shell so students can see its speed and rolling direction;
the upright arrow remains the separate facing indicator.

The game uses the printable models' millimetre scale. The sphere is 70 mm in
diameter (35 mm radius), exactly 35% of a 200 mm X1C plate width. Its rendered
mesh and physics collider use the same radius.

## Run it

From the repository root:

```bash
python3 -m http.server 8766 --directory game
```

Then open `http://127.0.0.1:8766/` in current Chrome or ChromeOS. Do not open
`index.html` with `file://`; browser modules, workers, WebAssembly, and offline
caching require HTTP(S). A production static host must serve `.wasm` as
`application/wasm`.

On a phone, portrait mode presents the maze and Coding Workspace as a compact
top-to-bottom workflow with a sticky level header and 44 px primary touch
targets. Narrow screens stack the maze title above its controls so labels stay
readable. Short landscape screens use a balanced side-by-side view and remove
nonessential maze overlays so placing the robot remains practical. Safe-area
insets are respected around notches and home indicators; rotate the device at
any time and the Three.js and Blockly surfaces resize without discarding student
work.

The first Python run loads about 11.7 MiB of local Pyodide files. After the
service worker finishes caching, the game can reload offline from the same
origin. There are no CDN or external runtime requests.

## Student workflow

1. Choose any of the seven unlocked mazes. The sequence progresses from a
   Straight Start, Starter L-Turn, Mirror Left, Double Turn, U-Turn Trail,
   Return Route, and Four-Turn Finish challenges.
2. Drag the robot from its tray anywhere onto the highlighted blue START piece.
   The exact release point becomes that attempt's starting position. **Place at
   start center** remains an explicit shortcut. Every classroom level starts
   facing north at world bearing `0°`. The `N` on the START AREA label means
   North and marks the robot’s initial forward direction. After the robot turns,
   its new facing becomes the reference for subsequent forward commands.
3. Complete the deliberately unfinished starter blocks, or switch to Python.
4. Press **Run**. **Stop** terminates the Python worker. **Reset** restores the
   exact position the student chose and clears the trail.
   When the maze and robot have been idle for 20 seconds, the camera begins a
   slow orbit for a clearer view. Any pointer, wheel, or keyboard interaction
   stops the orbit; reduced-motion preferences disable it.
   Click the maze to focus it, then press **Ctrl+R** to start that orbit
   immediately. The browser's normal reload shortcut remains available whenever
   focus is outside the maze view.
   Use the expand button in either panel header to focus the maze or Coding Workspace
   fullscreen. Press the same button or `Esc` to return to the two-panel view.
5. Bring the sphere to a complete stop on the green GOAL disc. Crossing the
   disc while still moving does not solve the maze. Wall impacts are counted in
   telemetry, but they bounce the robot back into the maze and do not terminate
   the program.
6. Select **Next maze** after a successful run, or use the maze picker at any
   time. Blocks and independent Python are saved separately for each level.
7. Use **Attempts** to compare the exact code, result, wall impacts, and changed
   line count from oldest to newest. Every Run is recorded automatically; **Save**
   adds a deliberate code-version checkpoint. The latest 20 entries are kept for
   each maze.

Use **Export** to download one `Maskwa-Maze-Lab-Work-YYYY-MM-DD.maskwamaze.json` file
containing every saved maze, its exact editor state, robot placement, and attempt
history. **Import** accepts that file on another Chromebook and continues to
accept earlier `.mazebot.json` project files. It validates the
entire project before changing local storage, replaces only the mazes included in
the file, and keeps the current local code for each replaced maze as a **Before
import** history entry. Imported code is displayed but never run automatically.
Mazes omitted from the file keep their local work, and the maze that was active
when the project was exported opens after import.

Python editing is limited to the same 20,000 characters accepted by the local
runtime. If an autosave fails because browser storage is blocked or full, the UI
keeps a visible warning, prevents a maze change that would hide the unsaved work,
and **Export** still attempts to download an in-memory recovery copy containing
the current maze. If the complete project has grown beyond the 3 MB portable-file
limit, Export downloads a clearly named current-maze-only recovery file instead.

Blocks generate Python one way. As soon as a student edits the Python buffer it
becomes independent; edits never alter or discard the saved blocks. The UI
labels this state and asks before replacing edited Python with freshly generated
block code. Blockly state, Python state, active editor, current level, and the
exact chosen starting position are saved to browser local storage. The v3 save
format keeps one program record plus a bounded attempt history per maze, and
imports the prior robot-relative v2 record without deleting it. The portable
project file identifies its schema and robot-relative heading rules so an
incompatible file is rejected before any work changes. Older absolute-heading v1
data remains as an untouched backup and is not silently executed under the newer
relative-heading rules.

Python accepts both `await set_main_led("#008cff")` and the RGB-number
`await set_main_led(0, 140, 255)` form.

Motion angles are robot-relative. `roll(0, ...)` always means forward from the
sphere's current facing; `roll(90, ...)` turns right before rolling, and
`roll(-90, ...)` turns left. `spin(90, ...)` turns right in place and makes that
new facing the reference for the next command, so a following `roll(0, ...)`
continues in the direction established by the spin. Telemetry reports the
resulting world bearing from the original north-facing start.

## Device settings

The header **Settings** menu stores presentation and convenience choices only on
the current browser device. It includes idle camera tour, reduced motion, a
fog-free clearer view, travel trail, impact markers, ground grid, and optional
reset confirmation. It also has an opt-in **Xbox controller** switch. Pair the
controller in ChromeOS Bluetooth first, return to the game, enable the switch,
and press any controller button. The status card identifies whether the browser
is waiting, connected, disconnected, or unsupported and shows the complete
button map. Controller support starts off and performs no polling while disabled.

The Xbox mapping is A for Place/Run, B for Stop, X for Reset, Y for
Blocks/Python, View for Attempts, Menu for Settings, and the bumpers or left/right
D-pad buttons for maze navigation. These buttons operate the game workflow only;
they never steer the sphere. Robot motion and turning still come exclusively
from the student's Blocks or Python program, with the same timing and physics.

Defaults keep the tour, trail, impact markers, and grid on;
the other options start off. Reduced motion changes camera and sphere
animation only, never timing, collision, bounce, heading, or goal physics.

Settings use their own versioned local-storage record. They are not included in
student autosaves, attempt history, Export files, or Import, so moving class work
between Chromebooks cannot silently change a device's accessibility preferences.
**Restore defaults** changes only these settings and leaves every program and
attempt untouched.

## Architecture and safety boundary

- `levels/*.json` describes each X1C route using the three existing STL models,
  including physical end-caps behind START and GOAL. Every file records visual
  transforms, start/goal poses, physics constants, a logical wall polygon, and a
  deterministic reference program.
- `js/levels.js` is the ordered classroom catalogue used by the picker and the
  Next maze action. `scripts/generate_game_levels.mjs` converts short 200 mm grid
  paths into correctly rotated printable pieces, collision outlines, and reference
  programs. Run it with `--write` after adding a path, or without an option to
  check that generated JSON is current.
- `js/simulation.js` displays the source STL meshes. Collision uses both the
  level boundary and wall segments generated from every printable tile's closed
  sides. A final containment check refuses to render any illegal position. This
  stays responsive on Chromebooks without relying on expensive triangle meshes.
- `js/level-logic.js` is the deterministic 60 Hz rolling-physics contract shared
  by the browser and validation script. Speed 160 targets 100 mm/s, acceleration
  and braking change velocity over time, and wall normals produce damped rebounds.
- `js/blocks.js` defines 13 custom blocks for sphere-robot commands: motion,
  LEDs, matrix pixels, and sensor reads, with Python generators.
- `js/python-worker.js` runs student Python inside a dedicated worker. It rejects
  imports, attribute access, classes, globals, and reserved names; only safe
  built-ins and the allowlisted robot RPC functions enter the student namespace.
- `js/python-runtime.js` enforces a 20,000-character program limit, a 25-second
  run limit, and hard termination for Stop. Termination/recreation avoids a
  SharedArrayBuffer or cross-origin-isolation requirement on Chromebooks.
- `js/storage.js` owns per-level autosave, the latest-20 code history, and the
  versioned portable JSON contract. Imports are size-limited, schema-checked,
  Blockly-validated, staged in memory, and committed with one local-storage
  write only after student confirmation.
- `js/game-actions.js` is the shared workflow boundary for on-screen and Xbox
  controller input. `js/gamepad.js` adapts the browser Gamepad API into rising-edge
  semantic actions without held-button repeats or direct robot steering.
- The multiplayer protocol, immutable session, transport, and client modules are
  dormant groundwork for a later authoritative WebSocket service. The current
  release remains offline by default and opens no socket. See
  [MULTIPLAYER.md](MULTIPLAYER.md) for the privacy, ordering, authority, and
  deployment contract.

This is an instructional sandbox, not a security boundary for hostile code.
The AST restrictions, isolated worker, program limit, and hard timeout reduce
accidental misuse; a school deployment should still use an origin containing no
sensitive data or authenticated application APIs.

## Validate

From the repository root:

```bash
node game/tests/validate.mjs
```

The validation checks local-only dependencies, JavaScript syntax, required UI
controls, the exact 13 custom blocks, worker restrictions, STL integrity, wall
bounce behavior, command semantics, catalogue/cache completeness, per-level save
isolation, attempt lifecycle, loss-resistant import/export behavior, and every
level's deterministic reference solution. A maze level is
not accepted unless its start and goal are legal, every printable opening connects
correctly, its polygon matches the printed corridor, and its saved student-command
route reaches the goal without an impact.
The three canonical X1C meshes are checksum-pinned, and the validator reads the
top-wall orientation directly from each STL. A rotated or changed printable wall
therefore cannot silently drift away from the logical collision profile.

## Current MVP limits

- The seven included routes are continuous corridors made from end, straight,
  and corner pieces. True branching mazes require adding the printable T and
  four-way pieces to the game geometry and collision profiles.
- There is no visual level builder yet; new continuous routes are currently
  defined as grid paths in the generator script.
- Physics is currently a deterministic 2-D rolling model. Ramps, falling, and
  vertical gravity are not simulated yet.
- Matrix commands preserve an 8×8 virtual state but do not yet render a matrix
  on the sphere shell.
- Python deliberately excludes imports and attribute access, so lessons use the
  provided robot functions and safe core language constructs.
- No physical-robot connection, accounts, live multiplayer server, or
  leaderboard. Multiplayer-ready client boundaries are present but remain
  offline until a separately reviewed server is explicitly configured.

See `THIRD_PARTY_NOTICES.md` for local runtime licenses.
