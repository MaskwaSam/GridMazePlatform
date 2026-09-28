#!/usr/bin/env python3
r"""Build a canonical five-piece maze starter set from the source Rhino model.

Run this file with Rhino 8's ``rhinocode`` command to create the CAD files::

    /Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
        /absolute/path/to/scripts/generate_maze_piece_variants.py

The source inspection and generated-file checks also run in ordinary Python::

    python3 scripts/generate_maze_piece_variants.py --check --require-outputs

The generator deliberately derives the base from the source straight-piece solid
and reuses the source's two separate wall solids.  It does not recreate their
profiles from guessed dimensions.
"""

from __future__ import print_function

import argparse
import hashlib
import math
import os
import struct
import sys


try:
    import Rhino
    import scriptcontext as sc
    import System
except ImportError:
    Rhino = None
    sc = None
    System = None


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
SOURCE_PATH = os.path.join(ROOT_DIR, "output", "grid_maze_platform_10mm_v1.3dm")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output", "variants")
OUTPUT_3DM = os.path.join(OUTPUT_DIR, "maze_piece_variants_v1.3dm")

TILE_SIZE = 200.0
BASE_HEIGHT = 10.0
EXPECTED_TOTAL_HEIGHT = 82.0
EXPECTED_SOURCE_SHA256 = "cfabf4f5b3e47eeca6cc3e57ad6e39aca4843b7bb2f74dcdc914cfcd3ae921fd"
MODEL_TOLERANCE = 0.01
BOUNDS_TOLERANCE = 0.15

SIDES = ("north", "east", "south", "west")
VARIANTS = (
    {
        "key": "straight",
        "label": "Straight",
        # The reviewed source's complete straight solid is transverse to the
        # separate reusable wall pair: its openings are on X, not Y.
        "open_sides": ("east", "west"),
        "closed_sides": ("north", "south"),
        "filename": "maze_piece_straight_v1.stl",
    },
    {
        "key": "corner",
        "label": "Corner",
        "open_sides": ("north", "east"),
        "closed_sides": ("south", "west"),
        "filename": "maze_piece_corner_v1.stl",
    },
    {
        "key": "t_junction",
        "label": "T Junction",
        "open_sides": ("north", "east", "south"),
        "closed_sides": ("west",),
        "filename": "maze_piece_t_junction_v1.stl",
    },
    {
        "key": "cross_junction",
        "label": "Cross Junction",
        "open_sides": ("north", "east", "south", "west"),
        "closed_sides": (),
        "filename": "maze_piece_cross_junction_v1.stl",
    },
    {
        "key": "end",
        "label": "End / Dead End",
        "open_sides": ("north",),
        "closed_sides": ("east", "south", "west"),
        "filename": "maze_piece_end_v1.stl",
    },
)


def _span(bounds, axis):
    return bounds[axis + 3] - bounds[axis]


def _center(bounds, axis):
    return (bounds[axis] + bounds[axis + 3]) / 2.0


def _bounds_tuple(bbox):
    return (
        float(bbox.Min.X),
        float(bbox.Min.Y),
        float(bbox.Min.Z),
        float(bbox.Max.X),
        float(bbox.Max.Y),
        float(bbox.Max.Z),
    )


def _record(index, geometry, name="", layer="", accurate=False):
    if accurate:
        bbox = geometry.GetBoundingBox(True)
    else:
        bbox = geometry.GetBoundingBox()
    bounds = _bounds_tuple(bbox)
    return {
        "index": int(index),
        "geometry": geometry,
        "name": name or "",
        "layer": layer or "",
        "is_brep": geometry.__class__.__name__ == "Brep",
        "is_solid": bool(getattr(geometry, "IsSolid", False)),
        "bounds": bounds,
        "x_span": _span(bounds, 0),
        "y_span": _span(bounds, 1),
        "z_span": _span(bounds, 2),
        "x_center": _center(bounds, 0),
        "y_center": _center(bounds, 1),
        "z_center": _center(bounds, 2),
        "bounds_kind": "accurate_trimmed" if accurate else "loose_control",
    }


def _dimension_similarity(first, second):
    terms = []
    for key in ("x_span", "y_span", "z_span"):
        scale = max(first[key], second[key], 1.0)
        terms.append(abs(first[key] - second[key]) / scale)
    return sum(terms)


def classify_source_records(records, tile_size=TILE_SIZE):
    """Identify the complete piece and parallel source walls by geometry only.

    Names, layers, and object ordering are retained for diagnostics but are not
    used for selection.  This keeps the generator stable if the Rhino document
    is reorganized.
    """

    solids = [record for record in records if record["is_brep"] and record["is_solid"]]
    full_candidates = []
    wall_candidates = []
    for record in solids:
        x_span = record["x_span"]
        y_span = record["y_span"]
        z_span = record["z_span"]
        short_xy = min(x_span, y_span)
        long_xy = max(x_span, y_span)
        if (
            0.88 * tile_size <= x_span <= 1.12 * tile_size
            and 0.88 * tile_size <= y_span <= 1.12 * tile_size
            and 0.25 * tile_size <= z_span <= 0.55 * tile_size
        ):
            full_candidates.append(record)
        if (
            short_xy <= 0.25 * tile_size
            and 0.88 * tile_size <= long_xy <= 1.12 * tile_size
            and 0.25 * tile_size <= z_span <= 0.55 * tile_size
        ):
            candidate = dict(record)
            candidate["long_axis"] = "y" if y_span >= x_span else "x"
            wall_candidates.append(candidate)

    if not full_candidates:
        raise ValueError("No closed, full-height 200 x 200 straight-piece solid was found")
    full_candidates.sort(
        key=lambda record: (
            abs(record["x_span"] - tile_size)
            + abs(record["y_span"] - tile_size)
            + abs(record["z_span"] - EXPECTED_TOTAL_HEIGHT),
            record["index"],
        )
    )
    full = full_candidates[0]

    pair_options = []
    for first_index, first in enumerate(wall_candidates):
        for second in wall_candidates[first_index + 1 :]:
            if first["long_axis"] != second["long_axis"]:
                continue
            cross_axis = 0 if first["long_axis"] == "y" else 1
            long_axis_index = 1 if first["long_axis"] == "y" else 0
            separation = abs(_center(first["bounds"], cross_axis) - _center(second["bounds"], cross_axis))
            if separation < 0.55 * tile_size:
                continue
            low_wall, high_wall = sorted(
                (first, second), key=lambda record: _center(record["bounds"], cross_axis)
            )
            # The pair must occupy opposing edges of the complete piece, span
            # nearly the full module in the other axis, and reach its top.
            edge_tolerance = 0.08 * tile_size
            if abs(low_wall["bounds"][cross_axis] - full["bounds"][cross_axis]) > edge_tolerance:
                continue
            if abs(high_wall["bounds"][cross_axis + 3] - full["bounds"][cross_axis + 3]) > edge_tolerance:
                continue
            if min(
                _span(first["bounds"], long_axis_index),
                _span(second["bounds"], long_axis_index),
            ) < 0.88 * tile_size:
                continue
            if max(
                abs(first["bounds"][5] - full["bounds"][5]),
                abs(second["bounds"][5] - full["bounds"][5]),
            ) > 0.03 * tile_size:
                continue
            full_center = _center(full["bounds"], cross_axis)
            midpoint = (
                _center(first["bounds"], cross_axis) + _center(second["bounds"], cross_axis)
            ) / 2.0
            score = (
                100.0 * _dimension_similarity(first, second)
                + abs(midpoint - full_center)
                + abs(separation - 0.90 * tile_size) / tile_size
            )
            pair_options.append((score, first, second))

    if not pair_options:
        raise ValueError("No matched, parallel pair of closed source wall solids was found")
    pair_options.sort(key=lambda option: (option[0], option[1]["index"], option[2]["index"]))
    if len(pair_options) > 1 and abs(pair_options[1][0] - pair_options[0][0]) < 0.01:
        raise ValueError("Source wall selection is ambiguous; two geometry pairs score equally")
    _score, first_wall, second_wall = pair_options[0]
    long_axis = first_wall["long_axis"]
    cross_center_key = "x_center" if long_axis == "y" else "y_center"
    walls = sorted((first_wall, second_wall), key=lambda record: record[cross_center_key])

    return {
        "full": full,
        "walls": tuple(walls),
        "wall_long_axis": long_axis,
        "solid_count": len(solids),
        "full_candidate_count": len(full_candidates),
        "wall_candidate_count": len(wall_candidates),
    }


def inspect_source_with_rhino3dm(path=SOURCE_PATH):
    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("The external --check requires the rhino3dm Python package") from exc
    model = rhino3dm.File3dm.Read(path)
    if model is None:
        raise RuntimeError("Could not read source Rhino file: %s" % path)
    if model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Source Rhino file must use millimeters")
    records = []
    for index, model_object in enumerate(model.Objects):
        geometry = model_object.Geometry
        attributes = model_object.Attributes
        layer_name = ""
        if 0 <= attributes.LayerIndex < len(model.Layers):
            layer_name = model.Layers[attributes.LayerIndex].FullPath
        records.append(_record(index, geometry, attributes.Name, layer_name, accurate=False))
    return classify_source_records(records)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _verify_source_fingerprint(path):
    actual = _sha256(path)
    if actual != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "Source 3dm fingerprint changed; review the geometry and update EXPECTED_SOURCE_SHA256 "
            "before regeneration (expected %s, got %s)" % (EXPECTED_SOURCE_SHA256, actual)
        )
    return actual


def _format_bounds(bounds):
    return "(%.2f, %.2f, %.2f) to (%.2f, %.2f, %.2f)" % bounds


def _print_source_summary(selection, source_path=SOURCE_PATH):
    full = selection["full"]
    walls = selection["walls"]
    print("SOURCE OK %s" % os.path.relpath(source_path, ROOT_DIR).replace(os.sep, "/"))
    print(
        "  complete solid: object %d, %s bounds %s"
        % (full["index"], full["bounds_kind"].replace("_", " "), _format_bounds(full["bounds"]))
    )
    print(
        "  source walls: objects %s, long axis %s, %s bounds %s and %s"
        % (
            ", ".join(str(wall["index"]) for wall in walls),
            selection["wall_long_axis"],
            walls[0]["bounds_kind"].replace("_", " "),
            _format_bounds(walls[0]["bounds"]),
            _format_bounds(walls[1]["bounds"]),
        )
    )


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _audit_triangle_topology(triangles, description="mesh", weld_tolerance=1.0e-5):
    """Prove a triangle soup is one closed, consistently oriented shell."""

    if not triangles:
        raise ValueError("%s contains no triangles" % description)
    parents = list(range(len(triangles)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first, second):
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    def quantize(vertex):
        return tuple(int(round(value / weld_tolerance)) for value in vertex)

    edge_counts = {}
    edge_first_triangle = {}
    edge_directions = {}
    seen_faces = set()
    signed_volume = 0.0
    for triangle_index, triangle in enumerate(triangles):
        first, second, third = triangle
        quantized = (quantize(first), quantize(second), quantize(third))
        if len(set(quantized)) != 3:
            raise ValueError("%s contains a degenerate triangle" % description)
        face_key = tuple(sorted(quantized))
        if face_key in seen_faces:
            raise ValueError("%s contains a duplicate triangle" % description)
        seen_faces.add(face_key)
        first_edge = tuple(second[axis] - first[axis] for axis in range(3))
        second_edge = tuple(third[axis] - first[axis] for axis in range(3))
        area_vector = _cross(first_edge, second_edge)
        if sum(value * value for value in area_vector) <= weld_tolerance ** 4:
            raise ValueError("%s contains a zero-area triangle" % description)
        signed_volume += sum(first[axis] * _cross(second, third)[axis] for axis in range(3)) / 6.0
        for start, end in (
            (quantized[0], quantized[1]),
            (quantized[1], quantized[2]),
            (quantized[2], quantized[0]),
        ):
            edge = tuple(sorted((start, end)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
            edge_directions.setdefault(edge, []).append((start, end))
            if edge in edge_first_triangle:
                union(triangle_index, edge_first_triangle[edge])
            else:
                edge_first_triangle[edge] = triangle_index

    bad_edges = [count for count in edge_counts.values() if count != 2]
    if bad_edges:
        boundary_count = sum(1 for count in bad_edges if count == 1)
        nonmanifold_count = sum(1 for count in bad_edges if count > 2)
        raise ValueError(
            "%s is not a closed manifold (boundary edges=%d, non-manifold edges=%d)"
            % (description, boundary_count, nonmanifold_count)
        )
    inconsistent_edges = 0
    for edge, directions in edge_directions.items():
        if len(directions) == 2 and directions[0] != (directions[1][1], directions[1][0]):
            inconsistent_edges += 1
    if inconsistent_edges:
        raise ValueError(
            "%s has %d inconsistently oriented shared edges" % (description, inconsistent_edges)
        )
    component_count = len({find(index) for index in range(len(triangles))})
    if component_count != 1:
        raise ValueError("%s contains %d disconnected closed shells" % (description, component_count))
    if not math.isfinite(signed_volume) or signed_volume <= 0.0:
        raise ValueError("%s has non-positive signed volume %.6f" % (description, signed_volume))
    return {
        "component_count": component_count,
        "edge_count": len(edge_counts),
        "signed_volume": signed_volume,
    }


def _read_binary_stl(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 84:
        raise ValueError("STL is shorter than its binary header: %s" % path)
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    if triangle_count <= 0 or len(data) != 84 + 50 * triangle_count:
        raise ValueError("STL binary length/triangle count mismatch: %s" % path)
    triangles = []
    for index in range(triangle_count):
        values = struct.unpack_from("<12fH", data, 84 + index * 50)
        coordinates = values[3:12]
        triangles.append(
            (
                tuple(coordinates[0:3]),
                tuple(coordinates[3:6]),
                tuple(coordinates[6:9]),
            )
        )
    coordinates = [value for triangle in triangles for vertex in triangle for value in vertex]
    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("STL contains a non-finite vertex: %s" % path)
    _audit_triangle_topology(triangles, os.path.basename(path))
    xs = coordinates[0::3]
    ys = coordinates[1::3]
    zs = coordinates[2::3]
    return triangle_count, (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def _assert_close(actual, expected, tolerance, description):
    if abs(actual - expected) > tolerance:
        raise ValueError("%s: expected %.3f, got %.3f" % (description, expected, actual))


def check_generated_outputs(output_dir=OUTPUT_DIR, require_outputs=False):
    expected_paths = [os.path.join(output_dir, variant["filename"]) for variant in VARIANTS]
    expected_paths.append(os.path.join(output_dir, os.path.basename(OUTPUT_3DM)))
    missing = [path for path in expected_paths if not os.path.isfile(path)]
    if missing:
        if require_outputs or len(missing) != len(expected_paths):
            raise ValueError(
                "Generated output set is incomplete; missing: %s"
                % ", ".join(os.path.basename(path) for path in missing)
            )
        print("OUTPUTS not generated yet; run this script through Rhino 8")
        return []

    summaries = []
    for variant in VARIANTS:
        path = os.path.join(output_dir, variant["filename"])
        triangle_count, bounds = _read_binary_stl(path)
        _assert_close(bounds[0], 0.0, BOUNDS_TOLERANCE, "%s minimum X" % variant["key"])
        _assert_close(bounds[1], 0.0, BOUNDS_TOLERANCE, "%s minimum Y" % variant["key"])
        _assert_close(bounds[2], 0.0, BOUNDS_TOLERANCE, "%s minimum Z" % variant["key"])
        _assert_close(bounds[3], TILE_SIZE, BOUNDS_TOLERANCE, "%s maximum X" % variant["key"])
        _assert_close(bounds[4], TILE_SIZE, BOUNDS_TOLERANCE, "%s maximum Y" % variant["key"])
        expected_z = BASE_HEIGHT if not variant["closed_sides"] else EXPECTED_TOTAL_HEIGHT
        _assert_close(bounds[5], expected_z, BOUNDS_TOLERANCE, "%s maximum Z" % variant["key"])
        summaries.append((variant["key"], triangle_count, bounds))

    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("Checking the combined 3dm requires the rhino3dm Python package") from exc
    combined_path = os.path.join(output_dir, os.path.basename(OUTPUT_3DM))
    model = rhino3dm.File3dm.Read(combined_path)
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Combined Rhino file is unreadable or is not in millimeters")
    solids = [obj for obj in model.Objects if bool(getattr(obj.Geometry, "IsSolid", False))]
    if len(solids) != len(VARIANTS):
        raise ValueError("Combined Rhino file must contain five closed variant solids")
    names = {obj.Attributes.Name for obj in solids}
    expected_names = {"maze_piece_%s_v1" % variant["key"] for variant in VARIANTS}
    if names != expected_names:
        raise ValueError("Combined Rhino object names do not match the canonical variant set")
    # rhino3dm exposes loose control-surface Brep bounds, which include trimmed
    # NURBS overrun and are not the printable extent.  Rhino generation records
    # the accurate RhinoCommon bounds after trimming and also reopens the file in
    # RhinoCommon to verify them.  Confirm that receipt here.
    solid_by_name = {obj.Attributes.Name: obj for obj in solids}
    positions = ((0.0, 0.0), (230.0, 0.0), (460.0, 0.0), (0.0, 230.0), (230.0, 230.0))
    for variant, position in zip(VARIANTS, positions):
        name = "maze_piece_%s_v1" % variant["key"]
        receipt = solid_by_name[name].Attributes.GetUserString("verified_trimmed_bounds_mm")
        if not receipt:
            raise ValueError("Combined Rhino object lacks accurate-bounds receipt: %s" % name)
        try:
            recorded = tuple(float(value) for value in receipt.split(","))
        except (TypeError, ValueError):
            raise ValueError("Combined Rhino accurate-bounds receipt is invalid: %s" % name)
        expected_z = BASE_HEIGHT if not variant["closed_sides"] else EXPECTED_TOTAL_HEIGHT
        expected = (
            position[0],
            position[1],
            0.0,
            position[0] + TILE_SIZE,
            position[1] + TILE_SIZE,
            expected_z,
        )
        if len(recorded) != len(expected):
            raise ValueError("Combined Rhino accurate-bounds receipt is incomplete: %s" % name)
        for index, (actual_value, expected_value) in enumerate(zip(recorded, expected)):
            _assert_close(
                actual_value,
                expected_value,
                BOUNDS_TOLERANCE,
                "%s recorded trimmed bound %d" % (name, index),
            )

    for key, triangle_count, bounds in summaries:
        print("OUTPUT OK %-14s triangles=%d bounds=%s" % (key, triangle_count, _format_bounds(bounds)))
    print("OUTPUT OK %s solids=%d" % (os.path.basename(combined_path), len(solids)))
    return summaries


def check_only(source_path=SOURCE_PATH, output_dir=OUTPUT_DIR, require_outputs=False):
    if not os.path.isfile(source_path):
        raise ValueError("Source Rhino file does not exist: %s" % source_path)
    source_hash = _verify_source_fingerprint(source_path)
    selection = inspect_source_with_rhino3dm(source_path)
    _print_source_summary(selection, source_path)
    print("  source sha256: %s (matches pinned source)" % source_hash)
    check_generated_outputs(output_dir, require_outputs=require_outputs)


def _require_rhino():
    if Rhino is None or sc is None or System is None:
        raise RuntimeError("CAD generation must be run through Rhino 8")


def _validate_brep(brep, name):
    if brep is None:
        raise RuntimeError("%s was not created" % name)
    if not brep.IsValid:
        raise RuntimeError("%s is not a valid Brep" % name)
    if not brep.IsSolid:
        raise RuntimeError("%s is not a closed solid" % name)
    if brep.SolidOrientation == Rhino.Geometry.BrepSolidOrientation.Inward:
        brep.Flip()
    return brep


def _box(min_x, min_y, min_z, max_x, max_y, max_z):
    bbox = Rhino.Geometry.BoundingBox(
        Rhino.Geometry.Point3d(min_x, min_y, min_z),
        Rhino.Geometry.Point3d(max_x, max_y, max_z),
    )
    return Rhino.Geometry.Brep.CreateFromBox(bbox)


def _single_valid_solid(parts, name):
    if parts is None or len(parts) == 0:
        raise RuntimeError("%s boolean produced no geometry" % name)
    valid = [part for part in parts if part is not None and part.IsValid and part.IsSolid]
    if len(valid) != 1 or len(parts) != 1:
        raise RuntimeError(
            "%s boolean must produce exactly one closed solid; got %d result(s), %d valid"
            % (name, len(parts), len(valid))
        )
    return _validate_brep(valid[0], name)


def _intersection(first, second, name, tolerance):
    parts = Rhino.Geometry.Brep.CreateBooleanIntersection(first, second, tolerance)
    return _single_valid_solid(parts, name)


def _union(parts, name, tolerance):
    for index, part in enumerate(parts):
        _validate_brep(part, "%s input %d" % (name, index + 1))
    result = Rhino.Geometry.Brep.CreateBooleanUnion(list(parts), tolerance)
    if result is None or len(result) != 1:
        count = 0 if result is None else len(result)
        raise RuntimeError("%s union should make one solid, got %d" % (name, count))
    return _validate_brep(result[0], name)


def _translated_copy(brep, x=0.0, y=0.0, z=0.0):
    duplicate = brep.DuplicateBrep()
    duplicate.Transform(Rhino.Geometry.Transform.Translation(x, y, z))
    return duplicate


def _rotated_copy(brep, angle_degrees, center):
    duplicate = brep.DuplicateBrep()
    transform = Rhino.Geometry.Transform.Rotation(
        math.radians(angle_degrees),
        Rhino.Geometry.Vector3d.ZAxis,
        center,
    )
    if not duplicate.Transform(transform):
        raise RuntimeError("Could not rotate source wall by %.1f degrees" % angle_degrees)
    return duplicate


def _rhino_source_records(model):
    records = []
    for index, model_object in enumerate(model.Objects):
        geometry = model_object.Geometry
        attributes = model_object.Attributes
        # File3dm layer indices can include deleted-table slots and are not
        # guaranteed to index the AllLayers enumerable.  Layer metadata is only
        # diagnostic, never a selector, so generation intentionally does not
        # depend on resolving it.
        records.append(_record(index, geometry, attributes.Name, "", accurate=True))
    return records


def _load_rhino_source(path):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None:
        raise RuntimeError("Could not read source Rhino file: %s" % path)
    if model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Source Rhino file must use millimeters")
    selection = classify_source_records(_rhino_source_records(model))
    return model, selection


def _normalized_source_geometry(selection, tolerance):
    full_record = selection["full"]
    wall_records = selection["walls"]
    full = full_record["geometry"].DuplicateBrep()
    walls = [record["geometry"].DuplicateBrep() for record in wall_records]
    _validate_brep(full, "source straight piece")
    for index, wall in enumerate(walls):
        _validate_brep(wall, "source wall %d" % (index + 1))

    full_bbox = full.GetBoundingBox(True)
    module_center_x = (full_bbox.Min.X + full_bbox.Max.X) / 2.0
    module_center_y = (full_bbox.Min.Y + full_bbox.Max.Y) / 2.0
    module_min_x = module_center_x - TILE_SIZE / 2.0
    module_min_y = module_center_y - TILE_SIZE / 2.0
    module_min_z = full_bbox.Min.Z

    normalize = Rhino.Geometry.Transform.Translation(-module_min_x, -module_min_y, -module_min_z)
    full.Transform(normalize)
    for wall in walls:
        wall.Transform(normalize)

    normalized_bbox = full.GetBoundingBox(True)
    if abs(normalized_bbox.Max.Z - EXPECTED_TOTAL_HEIGHT) > BOUNDS_TOLERANCE:
        raise RuntimeError(
            "Source straight-piece height is %.3f mm; expected %.3f mm"
            % (normalized_bbox.Max.Z, EXPECTED_TOTAL_HEIGHT)
        )
    for index, wall in enumerate(walls):
        wall_bbox = wall.GetBoundingBox(True)
        if abs(wall_bbox.Min.Z - BASE_HEIGHT) > BOUNDS_TOLERANCE:
            raise RuntimeError(
                "Source wall %d begins at %.3f mm instead of contacting the %.3f mm base top"
                % (index + 1, wall_bbox.Min.Z, BASE_HEIGHT)
            )

    envelope = _box(0.0, 0.0, -tolerance, TILE_SIZE, TILE_SIZE, EXPECTED_TOTAL_HEIGHT + tolerance)
    straight = _intersection(full, envelope, "canonical source straight", tolerance)
    base_envelope = _box(0.0, 0.0, -tolerance, TILE_SIZE, TILE_SIZE, BASE_HEIGHT)
    base = _intersection(full, base_envelope, "source-derived printable base", tolerance)

    wall_envelope = _box(0.0, 0.0, -tolerance, TILE_SIZE, TILE_SIZE, EXPECTED_TOTAL_HEIGHT + tolerance)
    clipped_walls = []
    for index, wall in enumerate(walls):
        clipped_walls.append(
            _intersection(wall, wall_envelope, "clipped source wall %d" % (index + 1), tolerance)
        )

    wall_axis = selection["wall_long_axis"]
    center = Rhino.Geometry.Point3d(TILE_SIZE / 2.0, TILE_SIZE / 2.0, 0.0)
    if wall_axis == "y":
        west_wall, east_wall = clipped_walls
        wall_by_side = {
            "west": west_wall,
            "east": east_wall,
            "south": _rotated_copy(west_wall, 90.0, center),
            "north": _rotated_copy(east_wall, 90.0, center),
        }
    else:
        south_wall, north_wall = clipped_walls
        wall_by_side = {
            "south": south_wall,
            "north": north_wall,
            "east": _rotated_copy(south_wall, 90.0, center),
            "west": _rotated_copy(north_wall, 90.0, center),
        }
    return straight, base, wall_by_side


def _validate_variant_bounds(brep, variant):
    _validate_brep(brep, variant["key"])
    bbox = brep.GetBoundingBox(True)
    bounds = _bounds_tuple(bbox)
    expected = (0.0, 0.0, 0.0, TILE_SIZE, TILE_SIZE)
    for index, value in enumerate(expected):
        actual = bounds[index]
        _assert_close(actual, value, BOUNDS_TOLERANCE, "%s bound %d" % (variant["key"], index))
    expected_z = BASE_HEIGHT if not variant["closed_sides"] else EXPECTED_TOTAL_HEIGHT
    _assert_close(bounds[5], expected_z, BOUNDS_TOLERANCE, "%s maximum Z" % variant["key"])
    volume = abs(brep.GetVolume())
    if not math.isfinite(volume) or volume <= 0.0:
        raise RuntimeError("%s has no valid enclosed volume" % variant["key"])
    return bounds, volume


def _build_variants(selection, tolerance):
    straight, base, wall_by_side = _normalized_source_geometry(selection, tolerance)
    result = {}
    for variant in VARIANTS:
        if variant["key"] == "straight":
            piece = straight.DuplicateBrep()
        elif not variant["closed_sides"]:
            piece = base.DuplicateBrep()
        else:
            parts = [base.DuplicateBrep()]
            parts.extend(wall_by_side[side].DuplicateBrep() for side in variant["closed_sides"])
            piece = _union(parts, variant["key"], tolerance)
        _validate_variant_bounds(piece, variant)
        result[variant["key"]] = piece
    return result


def _mesh_triangles(brep, name):
    parameters = Rhino.Geometry.MeshingParameters()
    parameters.JaggedSeams = False
    parameters.SimplePlanes = True
    parameters.RefineGrid = True
    parameters.Tolerance = 0.05
    parameters.MinimumEdgeLength = 0.05
    parameters.MaximumEdgeLength = 1.2
    meshes = Rhino.Geometry.Mesh.CreateFromBrep(brep, parameters)
    if meshes is None or len(meshes) == 0:
        raise RuntimeError("Could not mesh %s" % name)
    triangles = []
    for mesh in meshes:
        mesh.Faces.ConvertQuadsToTriangles()
        mesh.Normals.ComputeNormals()
        mesh.Compact()
        for face in mesh.Faces:
            if not face.IsTriangle:
                raise RuntimeError("A non-triangle face remained in %s" % name)
            triangles.append((mesh.Vertices[face.A], mesh.Vertices[face.B], mesh.Vertices[face.C]))
    if not triangles:
        raise RuntimeError("%s mesh contains no triangles" % name)
    return triangles


def _normal(first, second, third):
    ux, uy, uz = second.X - first.X, second.Y - first.Y, second.Z - first.Z
    vx, vy, vz = third.X - first.X, third.Y - first.Y, third.Z - first.Z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 0.0:
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def _write_binary_stl(path, title, triangles):
    header = title.encode("ascii", "ignore")[:80]
    header += b" " * (80 - len(header))
    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(struct.pack("<I", len(triangles)))
        for first, second, third in triangles:
            handle.write(struct.pack("<3f", *_normal(first, second, third)))
            for vertex in (first, second, third):
                handle.write(struct.pack("<3f", float(vertex.X), float(vertex.Y), float(vertex.Z)))
            handle.write(struct.pack("<H", 0))


def _color(red, green, blue):
    return System.Drawing.Color.FromArgb(int(red), int(green), int(blue))


def _add_layer(doc, parent_index, name, color):
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    layer.ParentLayerId = doc.Layers[parent_index].Id
    layer.Color = color
    index = doc.Layers.Add(layer)
    if index < 0:
        raise RuntimeError("Could not add Rhino layer: %s" % name)
    return index


def _add_variant_object(doc, brep, variant, layer_index, source_hash):
    object_id = doc.Objects.AddBrep(brep)
    rhino_object = doc.Objects.FindId(object_id)
    if rhino_object is None:
        raise RuntimeError("Could not add %s to combined Rhino file" % variant["key"])
    attributes = rhino_object.Attributes
    attributes.Name = "maze_piece_%s_v1" % variant["key"]
    attributes.LayerIndex = layer_index
    attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
    attributes.SetUserString("open_sides", ",".join(variant["open_sides"]))
    attributes.SetUserString("closed_wall_sides", ",".join(variant["closed_sides"]))
    attributes.SetUserString("source_sha256", source_hash)
    attributes.SetUserString("module_size_mm", "200 x 200")
    accurate_bounds = _bounds_tuple(brep.GetBoundingBox(True))
    attributes.SetUserString(
        "verified_trimmed_bounds_mm",
        ",".join("%.4f" % value for value in accurate_bounds),
    )
    if not doc.Objects.ModifyAttributes(object_id, attributes, True):
        raise RuntimeError("Could not set attributes for %s" % variant["key"])


def _validate_saved_combined_doc(path):
    """Reopen the written 3dm in RhinoCommon and verify trimmed geometry."""

    model = Rhino.FileIO.File3dm.Read(path)
    if model is None:
        raise RuntimeError("Could not reopen combined Rhino file: %s" % path)
    by_name = {}
    for model_object in model.Objects:
        name = model_object.Attributes.Name
        if name in by_name:
            raise RuntimeError("Duplicate object name in combined Rhino file: %s" % name)
        by_name[name] = model_object
    positions = ((0.0, 0.0), (230.0, 0.0), (460.0, 0.0), (0.0, 230.0), (230.0, 230.0))
    for variant, position in zip(VARIANTS, positions):
        name = "maze_piece_%s_v1" % variant["key"]
        if name not in by_name:
            raise RuntimeError("Combined Rhino file is missing object: %s" % name)
        geometry = by_name[name].Geometry
        _validate_brep(geometry, "saved %s" % name)
        actual = _bounds_tuple(geometry.GetBoundingBox(True))
        expected_z = BASE_HEIGHT if not variant["closed_sides"] else EXPECTED_TOTAL_HEIGHT
        expected = (
            position[0],
            position[1],
            0.0,
            position[0] + TILE_SIZE,
            position[1] + TILE_SIZE,
            expected_z,
        )
        for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
            _assert_close(
                actual_value,
                expected_value,
                BOUNDS_TOLERANCE,
                "saved %s bound %d" % (name, index),
            )
    if len(by_name) != len(VARIANTS):
        raise RuntimeError("Combined Rhino file contains unexpected extra objects")
    print("REOPENED %s: five closed solids with verified accurate trimmed bounds" % os.path.basename(path))


def _save_combined_doc(variants, path, source_hash):
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is None:
        raise RuntimeError("Could not create a headless Rhino output document")
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    doc.ModelAbsoluteTolerance = MODEL_TOLERANCE
    doc.ModelAngleToleranceRadians = math.radians(0.25)

    parent = Rhino.DocObjects.Layer()
    parent.Name = "MazePieceVariants"
    parent.Color = _color(95, 105, 120)
    parent_index = doc.Layers.Add(parent)
    if parent_index < 0:
        raise RuntimeError("Could not add parent layer")

    colors = (
        _color(68, 116, 188),
        _color(231, 142, 55),
        _color(76, 156, 109),
        _color(145, 99, 188),
        _color(196, 76, 90),
    )
    positions = ((0.0, 0.0), (230.0, 0.0), (460.0, 0.0), (0.0, 230.0), (230.0, 230.0))
    for variant, color, position in zip(VARIANTS, colors, positions):
        layer_index = _add_layer(doc, parent_index, variant["label"], color)
        preview = _translated_copy(variants[variant["key"]], position[0], position[1], 0.0)
        _add_variant_object(doc, preview, variant, layer_index, source_hash)

    doc.Strings.SetString("generator", "scripts/generate_maze_piece_variants.py")
    doc.Strings.SetString("source_file", os.path.relpath(SOURCE_PATH, ROOT_DIR).replace(os.sep, "/"))
    doc.Strings.SetString("source_sha256", source_hash)
    doc.Strings.SetString("canonical_orientation", "north is +Y; east is +X")
    options = Rhino.FileIO.FileWriteOptions()
    options.SuppressDialogBoxes = True
    options.WriteSelectedObjectsOnly = False
    options.WriteGeometryOnly = False
    if not doc.WriteFile(path, options):
        raise RuntimeError("Could not write combined Rhino file: %s" % path)
    doc.Dispose()
    _validate_saved_combined_doc(path)


def generate(source_path=SOURCE_PATH, output_dir=OUTPUT_DIR):
    _require_rhino()
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    source_hash = _verify_source_fingerprint(source_path)
    _source_model, selection = _load_rhino_source(source_path)
    _print_source_summary(selection, source_path)
    variants = _build_variants(selection, MODEL_TOLERANCE)

    for variant in VARIANTS:
        brep = variants[variant["key"]]
        bounds, volume = _validate_variant_bounds(brep, variant)
        triangles = _mesh_triangles(brep, variant["key"])
        topology_triangles = [
            tuple((float(vertex.X), float(vertex.Y), float(vertex.Z)) for vertex in triangle)
            for triangle in triangles
        ]
        _audit_triangle_topology(topology_triangles, variant["key"])
        path = os.path.join(output_dir, variant["filename"])
        _write_binary_stl(path, "Grid Maze %s v1" % variant["label"], triangles)
        print(
            "WROTE %-38s triangles=%d volume=%.1f mm3 bounds=%s"
            % (os.path.relpath(path, ROOT_DIR), len(triangles), volume, _format_bounds(bounds))
        )

    combined_path = os.path.join(output_dir, os.path.basename(OUTPUT_3DM))
    _save_combined_doc(variants, combined_path, source_hash)
    print("WROTE %s" % os.path.relpath(combined_path, ROOT_DIR))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate canonical maze-piece variants from the Rhino source geometry")
    parser.add_argument("--check", action="store_true", help="inspect source and outputs without Rhino")
    parser.add_argument("--require-outputs", action="store_true", help="make --check fail if outputs are missing")
    parser.add_argument("--source", default=SOURCE_PATH, help="source .3dm path")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="variant output folder")
    args = parser.parse_args(argv)
    if args.check:
        check_only(args.source, args.output_dir, require_outputs=args.require_outputs)
        return
    if Rhino is None:
        check_only(args.source, args.output_dir, require_outputs=False)
        print("Rhino is unavailable, so CAD generation was skipped.")
        return
    generate(args.source, args.output_dir)


if __name__ == "__main__":
    if Rhino is None:
        main()
    else:
        # RhinoCode sends stdout to Rhino's UI rather than its CLI caller.  Keep
        # a small temporary transcript so headless/remote invocations expose an
        # actionable traceback without adding diagnostic files to the project.
        import contextlib
        import traceback

        transcript_path = os.path.join(os.path.abspath(os.path.expanduser("/tmp")), "gridmaze_variant_generation.log")
        with open(transcript_path, "w") as transcript:
            try:
                with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
                    main()
                transcript.write("GENERATION OK\n")
            except Exception:
                traceback.print_exc(file=transcript)
                raise
