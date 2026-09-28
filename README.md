# Grid Maze Platform

Parametric Rhino 8 generator for a first-pass modular grid maze platform.

The shared platform system uses:

- 200 mm x 200 mm tile footprint.
- 10 mm total tile height.
- Selectable underside connector pockets for `north`, `south`, `east`, and `west`.
- 8 mm pocket depth from the underside, leaving a 2 mm top skin.
- A removable underside bridge connector that lays flat in a matching recess.
- Flat double-dovetail connector footprint:
  50 mm dovetail length into each board, 22 mm neck width, 46 mm inner tail width,
  6 mm connector thickness, and 0.2 mm printable clearance per side.
- No quarter-turn prongs, ramps, undercuts, or overhanging lock features.

The baseline platform generator intentionally leaves walls out. The working Rhino
model contains the user-authored straight maze-piece geometry with its platform and
tall walls; the wall-variant generators use that modeled geometry as their source
instead of rebuilding its profile from guessed dimensions.

## Files

- `params/maze_platform_v1.json` contains the default dimensions.
- `enabled_sides` controls which dovetail pockets are generated. Default: all four sides.
- `scripts/generate_grid_maze_platform.py` validates parameters and generates Rhino geometry.
- `scripts/generate_maze_piece_variants.py` derives the five-piece 200 mm starter set from the working Rhino geometry.
- `scripts/generate_h2d_compatible_platforms.py` creates 200 x 300 mm and 300 x 300 mm H2D adapter platforms with the exact reviewed X1C pocket geometry.
- `scripts/generate_h2d_maze_variants.py` adds the Rhino-authored walls to five maze layouts at each H2D platform size and two 45-degree special pieces.
- `scripts/generate_30deg_ramp.py` creates the X1C-compatible straight-corridor ramp that rises 2 mm above the wall top.
- `scripts/generate_30deg_up_down_ramp.py` creates the symmetric 200 x 300 challenge ramp with a centred ridge.
- `scripts/generate_challenge_ramp_variants.py` creates the twelve-piece 200 x 300 H2D challenge collection.
- `scripts/optimize_for_3d_printing.py` ranks printable dovetail/clearance variants without requiring Rhino.
- `scripts/render_piece_catalog.py` renders the generated STL files for the offline visual catalog.
- `tests/test_platform_spec.py` performs fast CPython checks that do not require Rhino.
- `reference/photos/` contains photos of printed prototypes; these are visual references, not dimensional source files.
- [`docs/index.html`](docs/index.html) is the human-readable catalog with geometry renders and connection diagrams.
- [`game/`](game/) is the self-hosted Chromebook game for programming a Three.js sphere robot with Blocks or Python.
- `output/` is where generated `.3dm` and `.stl` files are written.

The Rhino model at `output/grid_maze_platform_10mm_v1.3dm` is the authoritative
geometry for new maze-piece variants. Prototype photos should be used to understand
the intended assembly and appearance, while dimensions should be taken from the
Rhino geometry and parameter files.

## Project Handoff — 2026-08-29

The current visual catalog contains 33 generated pieces across six families:

- 5 original 200 x 200 mm X1C wall pieces;
- 2 blank H2D adapter platforms;
- 12 H2D wall and 45-degree adapter pieces;
- 1 X1C 30-degree rising ramp;
- 1 H2D 200 x 300 mm up-and-down ramp; and
- 12 H2D 200 x 300 mm challenge-ramp variations.

Open [`docs/index.html`](docs/index.html) directly in a browser to review the
renders and download the printable files. Its controls combine free-text search
with mutually exclusive platform and piece-type filters. Select **H2D only** to
hide the original X1C/200-only pieces. Press Escape to clear the search field;
use **Reset filters** to restore the complete catalog. All content remains visible
if JavaScript is unavailable.

Every new H2D platform keeps the reviewed X1C connector geometry unchanged and
uses one connector pocket centred on each side. The generated files in `output/`
remain the printable/editable deliverables; the catalog images are previews only.

Closeout verification: `python3 -B -m unittest discover -s tests -p 'test_*.py'`
passes all 88 tests, including generated-solid checks, the standalone game
contract, and catalog metadata, local-link, accessibility-state, and no-JavaScript
fallback checks. The catalog's inline JavaScript also passed syntax and filter-logic
validation; Maskwa Maze Lab additionally passed live Chromium interaction testing at
the 1366 x 768 Chromebook viewport.

Before a production print, slice the 300 x 300 mm platform with the intended H2D
nozzle/profile and confirm the usable-bed boundary, excluded zones, skirt, and brim.
Print a small connector test first when changing filament, nozzle, or clearance;
the CAD compatibility does not replace a physical fit check.

## Maskwa Maze Lab — Standalone Chromebook Game

[`game/index.html`](game/index.html) is the playable vertical slice. It uses the
generated straight, corner, and end-piece STLs to provide seven progressively
longer courses: Straight Start, Starter L-Turn, Mirror Left, Double Turn, U-Turn
Trail, Return Route, and Four-Turn Finish. Students choose a maze, drag the sphere robot from its tray
anywhere onto the highlighted starting piece, finish an intentionally incomplete program in
Blockly or Python, and press Run. The deterministic 60 Hz simulation reports
collisions and succeeds only when the robot enters the goal. Run and Reset preserve
the student's exact collision-safe drop position rather than snapping to the tile center.
The rendered sphere and physics collider are both 70 mm in diameter (35 mm
radius), exactly 35% of one 200 mm X1C plate width.

Every Run keeps the exact executed code, result, ending pose, and wall-impact
count in a per-maze history; students can also create explicit Save checkpoints
and compare changed lines. The latest 20 entries per maze remain in browser-local
storage. Export writes all maze work and history to one portable Maskwa Maze Lab JSON file.
Import validates the complete file, preserves replaced local code in history, and
never runs imported student code automatically. It also restores the exported
active maze. Failed autosaves remain visibly flagged, block a lossy maze switch,
and Export can produce an in-memory recovery copy when browser storage is
unavailable. If the complete project exceeds the portable-file limit, Export
falls back to a clearly named current-maze-only recovery file.

The app is self-hosted: Three.js, Blockly, the Python generator, and the minimal
Pyodide runtime are stored under `game/vendor/`, with their license notices. It
does not require a CDN. Serve it over HTTP rather than opening it with `file://`:

```bash
python3 -m http.server 8766 --directory game
```

Then open `http://127.0.0.1:8766/` in Chrome or ChromeOS. Validate the standalone
bundle and its deterministic reference solution with:

```bash
node game/tests/validate.mjs
```

The MVP has seven flat continuous-corridor levels with a picker, per-level program
saves, and a Next maze action. Ramp physics, branching T/cross-piece levels, the
rendered 8 x 8 shell matrix, and physical BOLT+ connectivity remain later additions. See
[`game/README.md`](game/README.md) for the student workflow, architecture, safety
boundary, offline behavior, and current limitations.

### Production acceptance — 2026-08-30

Maskwa Maze Lab is live at <https://mazelab.spatterson.ca>. The accepted release
is commit `3b51f351a5083f8f7886f102165514c8ed166bf9`, immutable image
`mazelab:3b51f351a508-3adc281d9e56`, and runtime digest
`3adc281d9e564466a6f78de723d326c1807c5490816514c1626e8390e960a3f2`.
Public HTTP, the version 40 offline cache, all seven Beginning levels, Blocks,
local Python, the 390 x 844 mobile layout, and the no-external-request boundary
passed acceptance. The operator completed visual acceptance and reported being
very happy with the result.

The Cloudflare connector and running neighboring services were preserved during
the update. The prior image `mazelab:a484fc7c9452-463b9b81691d` remains retained
for rollback. Maze Lab remains a static, local-first application: student work
stays in each browser, and the dormant multiplayer modules do not expose a
WebSocket or `/ws` service. This production acceptance applies only to the
committed game and deployment surface; the separate CAD/catalogue work remains
outside the deployed artifact.

## Maze Piece Starter Set

The canonical set keeps the existing 200 mm square module and includes straight,
corner, T-junction, cross-junction, and end/dead-end pieces. Other orientations are
made by rotating these five pieces.

Generate the Rhino and STL files with Rhino 8's `rhinocode` command:

```bash
/Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
  "$(pwd)/scripts/generate_maze_piece_variants.py"
```

Then validate the exported artifacts and refresh the catalog images:

```bash
python3 -B scripts/generate_maze_piece_variants.py --check --require-outputs
python3 -B scripts/render_piece_catalog.py
```

Generated variants are written to `output/variants/`.

The variant generator pins the reviewed source model's SHA-256 fingerprint so it
cannot silently select different geometry after the Rhino file changes. After an
intentional source edit, review the new geometry before updating
`EXPECTED_SOURCE_SHA256` in the generator.

## H2D-Compatible Adapter Platforms

The H2D set expands the printable area while retaining the current X1C maze
connector at its original size and clearance:

- `200 x 300 mm`: one connector bay centred on each of its four edges.
- `300 x 300 mm`: one connector bay centred on each of its four edges.
- Both platforms remain 10 mm high, with 8 mm-deep underside pockets and a
  2 mm top skin.

On a 300 mm edge, an ordinary 200 x 200 mm X1C platform attaches in the centre,
leaving a 50 mm shoulder at each end of the larger edge. The connector itself is
not scaled or altered.

Generate the H2D adapters through Rhino 8, then validate their saved geometry:

```bash
/Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
  "$(pwd)/scripts/generate_h2d_compatible_platforms.py"
python3 -B scripts/generate_h2d_compatible_platforms.py --check --require-outputs
python3 -B scripts/render_piece_catalog.py --collection h2d
```

Generated files are written to `output/h2d-platforms/`. For H2D dual-nozzle
printing, orient the 200 x 300 mm adapter with its 300 mm dimension along the
320 mm bed axis. The 300 x 300 mm adapter uses the dual-nozzle width exactly, so
the single-nozzle build envelope is the more forgiving choice. Confirm the
sliced footprint, skirt or brim, and excluded zones before printing either part.

## H2D Wall Variants

The larger wall set contains straight, corner, T-junction, cross-junction, and
end/dead-end pieces at both 200 x 300 mm and 300 x 300 mm. Every piece retains one
centred X1C connector pocket per side. A wall-bearing transition connects a centred
200 mm X1C edge to a centred 300 mm H2D edge. A four-way 300 x 300 mm hub provides
centred 200 mm X1C openings and connectors on all four sides.

The walls come from the separate closed wall solids in the working Rhino file.
For a 300 mm edge, the generator preserves both designed wall ends and inserts
100 mm through a verified uniform middle section. It does not scale the wall
thickness, height, or end transitions.

The transition occupies a 300 x 200 mm envelope. Its side walls run straight for
75 mm, widen by 50 mm over a 50 mm run at exactly 45 degrees, and then run straight
for another 75 mm. It has one centred connector pocket on each open end and no
connector pockets on its angled sides. A continuous sharp-miter sweep carries the
verified Rhino wall profile through both bends without overlap ribs.

The four-way hub uses four exact 45-degree walls. Each wall is the source-derived
1.2 mm vertical panel from Z10 to Z82; the authored 19.2 mm sloped reinforcement
foot is intentionally omitted from this piece. This removes the triangular foot
corners while retaining the wall height, four centred openings, and connector scale.

Generate, validate, and render the twelve-piece set with:

```bash
/Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
  "$(pwd)/scripts/generate_h2d_maze_variants.py"
python3 -B scripts/generate_h2d_maze_variants.py --check --require-outputs
python3 -B scripts/render_piece_catalog.py --collection h2d-walls
```

The STL files and combined editable Rhino model are written to
`output/h2d-wall-variants/`.

## 30 Degree Ramp

The ramp is a 200 x 200 mm X1C-compatible straight-corridor tile with one centred
connector pocket on every side and the two authored side walls. Its floor remains
flat at Z10 for a 71.828 mm south approach, then rises at exactly 30 degrees to
Z84 at the north edge. That is 2 mm above the Z82 wall top. The 74 mm rise fixes
the horizontal run at 128.172 mm and the sloped surface length at exactly 148 mm.

The closed ramp wedge is 161.6 mm wide, centred between X19.2 and X180.8 so it
stays within the exact floor-level corridor between the authored wall feet. Rotate
the finished tile to place the high edge in another direction. The high-side pocket
remains mechanically compatible, but its Z84 ramp surface is intentionally not a
level continuation of a normal Z10 tile.

Generate, validate, and render the ramp with:

```bash
/Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
  "$(pwd)/scripts/generate_30deg_ramp.py"
python3 -B scripts/generate_30deg_ramp.py --check --require-outputs
python3 -B scripts/render_piece_catalog.py --collection ramp
```

The printable STL and editable one-piece Rhino model are written to `output/ramp/`.

### 200 x 300 Up-and-Down Challenge Ramp

The challenge piece keeps both entries at the normal Z10 floor level. After a
21.828 mm flat approach, it climbs at exactly 30 degrees to a centred Z84 ridge,
then descends symmetrically at 30 degrees to a matching 21.828 mm exit approach.
Each side of the ridge has a 74 mm rise, 128.172 mm horizontal run, and 148 mm
sloped length. The peak is 2 mm above the Z82 wall top.

Its 200 x 300 mm H2D platform retains one centred X1C pocket on every side and
uses the reviewed 300 mm extensions of the two authored straight walls. The ramp
remains 161.6 mm wide between the wall feet. Generate and verify it with:

```bash
/Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
  "$(pwd)/scripts/generate_30deg_up_down_ramp.py"
python3 -B scripts/generate_30deg_up_down_ramp.py --check --require-outputs
python3 -B scripts/render_piece_catalog.py --collection challenge-ramp
```

Its STL and editable Rhino model are written to `output/challenge-ramp/`.

### 200 x 300 Challenge Ramp Collection

The extended challenge collection reuses the same H2D platform, exact centred
X1C connector pocket on every side, 161.6 mm ramp width, and source-derived wall
geometry. It contains twelve printable profiles:

- a Z84 hill with a 30 mm flat top;
- two 30 mm-rise humps;
- the Z84 ridge with twelve shallow traction ribs;
- centred 20, 40, and 60 mm-rise hills;
- an asymmetric ridge offset to Y100;
- a Z84 crest rounded to a 15 mm radius;
- a Z60 stopping platform that is 80 mm long;
- one-wall and wall-free versions of the Z84 ridge; and
- a directional challenge with a smooth 30-degree climb and ten steps down.

Generate, validate, and render the collection with:

```bash
/Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
  "$(pwd)/scripts/generate_challenge_ramp_variants.py"
python3 -B scripts/generate_challenge_ramp_variants.py --check --require-outputs
python3 -B scripts/render_piece_catalog.py --collection challenge-ramp-variants
```

The twelve STLs and their combined editable Rhino model are written to
`output/challenge-ramp-variants/`.

## Generate

From Rhino 8, with model units in millimeters:

```text
-_RunPythonScript "<repo-path>/scripts/generate_grid_maze_platform.py"
```

Replace `<repo-path>` with the folder where you cloned this repository.

The script also supports Rhino headless execution and writes status files to:

```text
output/grid_maze_platform_status.txt
<Rhino system temp>/grid_maze_platform_status.txt
```

Expected output files:

- `output/grid_maze_platform_10mm_v1.3dm`
- `output/grid_maze_platform_tile_v1.stl`
- `output/grid_maze_platform_bridge_v1.stl`
- `output/grid_maze_platform_recess_cutter_v1.stl` contains the full board-layout dovetail cutter for all four underside connector beds.

Rhino may include a local macOS render-cache username in otherwise portable
`.3dm` metadata. The checked-in model is sanitized with the length-preserving
`scripts/sanitize_3dm_metadata.py` helper; generated geometry is unchanged.

## Fast Checks

These checks only validate the parameter math and can run outside Rhino:

```bash
python3 -B -m unittest discover -s tests
python3 -B scripts/generate_grid_maze_platform.py --check
python3 -B scripts/generate_grid_maze_platform.py --check --sides north,east
python3 -B scripts/optimize_for_3d_printing.py
```

To generate only selected sides from Rhino, edit `enabled_sides` in
`params/maze_platform_v1.json` before running the Rhino script. From CPython checks
and non-Rhino runs, `--sides north,east` can be used as a quick override.

## 3D Print Optimization

The optimizer reads the current platform parameters and scores small dovetail
variants for FDM printing. It does not change the main parameter file unless you
ask it to write a separate optimized JSON.

```bash
python3 -B scripts/optimize_for_3d_printing.py --profile tight
python3 -B scripts/optimize_for_3d_printing.py --profile balanced --write-report
python3 -B scripts/optimize_for_3d_printing.py --profile balanced --write-params
```

Profiles:

- `tight` keeps the requested 0.20 mm clearance as the target.
- `balanced` targets 0.25 mm clearance for a more forgiving first FDM prototype.
- `durable` favors a slightly thicker connector and lower vertical slack.

Generated optional files:

- `output/print_optimization_report.md`
- `params/maze_platform_print_optimized.json`

## Current Assumptions

- This is tabletop-maze hardware, not a child/adult load-bearing floor system.
- The underside bridge is a flat printed dovetail part that sits inside the 8 mm underside recess.
- The platform-side pocket is a simple subtractive dovetail bed for the connector footprint.
- The exported recess cutter includes the board layout, not just the loose connector footprint.
- The current flat connector is shape-fit only; screw/nut retention can be added next.
