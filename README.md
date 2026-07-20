# Grid Maze Platform

Parametric Rhino 8 generator for a first-pass modular grid maze platform.

The current deliverable focuses on the platform system only:

- 200 mm x 200 mm tile footprint.
- 10 mm total tile height.
- Selectable underside connector pockets for `north`, `south`, `east`, and `west`.
- 8 mm pocket depth from the underside, leaving a 2 mm top skin.
- A removable underside bridge connector that lays flat in a matching recess.
- Flat double-dovetail connector footprint:
  50 mm dovetail length into each board, 22 mm neck width, 46 mm inner tail width,
  6 mm connector thickness, and 0.2 mm printable clearance per side.
- No quarter-turn prongs, ramps, undercuts, or overhanging lock features.

Walls are intentionally left out of this version. The platform keeps the top clean so
2 mm thick, 70 mm high walls can be added later as separate geometry.

## Files

- `params/maze_platform_v1.json` contains the default dimensions.
- `enabled_sides` controls which dovetail pockets are generated. Default: all four sides.
- `scripts/generate_grid_maze_platform.py` validates parameters and generates Rhino geometry.
- `scripts/optimize_for_3d_printing.py` ranks printable dovetail/clearance variants without requiring Rhino.
- `tests/test_platform_spec.py` performs fast CPython checks that do not require Rhino.
- `output/` is where generated `.3dm` and `.stl` files are written.

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
