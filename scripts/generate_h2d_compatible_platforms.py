#!/usr/bin/env python3
r"""Generate larger H2D platforms with the reviewed X1C connector interface.

Rhino 8 generation::

    /Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
        /absolute/path/to/scripts/generate_h2d_compatible_platforms.py

External receipt and artifact validation::

    python3 scripts/generate_h2d_compatible_platforms.py --check --require-outputs
"""

from __future__ import print_function

import argparse
import contextlib
import itertools
import math
import os
import struct
import traceback


try:
    import Rhino
    import System
except ImportError:
    Rhino = None
    System = None


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
if THIS_DIR not in os.sys.path:
    os.sys.path.insert(0, THIS_DIR)

from generate_grid_maze_platform import load_spec
from generate_maze_piece_variants import (
    BOUNDS_TOLERANCE,
    EXPECTED_SOURCE_SHA256,
    _assert_close,
    _audit_triangle_topology,
    _bounds_tuple,
    _color,
    _format_bounds,
    _mesh_triangles,
    _read_binary_stl,
    _sha256,
    _single_valid_solid,
    _validate_brep,
    _write_binary_stl,
)


PARAMS_PATH = os.path.join(ROOT_DIR, "params", "maze_platform_v1.json")
SOURCE_3DM_PATH = os.path.join(ROOT_DIR, "output", "grid_maze_platform_10mm_v1.3dm")
SOURCE_TILE_PATH = os.path.join(ROOT_DIR, "output", "grid_maze_platform_tile_v1.stl")
SOURCE_BRIDGE_PATH = os.path.join(ROOT_DIR, "output", "grid_maze_platform_bridge_v1.stl")
SOURCE_CUTTER_PATH = os.path.join(ROOT_DIR, "output", "grid_maze_platform_recess_cutter_v1.stl")
CURRENT_CONNECTOR_PATH = os.path.join(ROOT_DIR, "output", "Maze peice connector.stl")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output", "h2d-platforms")
OUTPUT_3DM = os.path.join(OUTPUT_DIR, "maze_platform_h2d_compatible_v1.3dm")

EXPECTED_PARAMS_SHA256 = "f5f13f3780e10ccf02fbb1ce70d4a684cc26f112d52c618694a43626a220c694"
EXPECTED_TILE_SHA256 = "61d37fd60107f74aa98518d37e0800aa6946ba1ef3251da5b97d21db6c2d56ac"
EXPECTED_BRIDGE_SHA256 = "52d17cc0890af25ba8724bcacbd075489a3366ff0ecc326e4900bd21772a61e2"
EXPECTED_CUTTER_SHA256 = "274939aa2ef328b596b87e013e0ebe54bfef176c33d88e9d67aa523e34471572"
EXPECTED_CURRENT_CONNECTOR_SHA256 = "32fa772ea3f649cf4373e49ca539dacc4d8acf83f69c51a663aafa8fd63b8eea"

MODEL_TOLERANCE = 0.01
SIDES = ("north", "east", "south", "west")

PLATFORMS = (
    {
        "key": "200x300",
        "label": "H2D 200 x 300 Adapter",
        "width": 200.0,
        "height": 300.0,
        "filename": "maze_platform_h2d_200x300_v1.stl",
        "position": (0.0, 0.0),
        "pockets": {
            "north": (100.0,),
            "east": (150.0,),
            "south": (100.0,),
            "west": (150.0,),
        },
    },
    {
        "key": "300x300",
        "label": "H2D 300 x 300 Adapter",
        "width": 300.0,
        "height": 300.0,
        "filename": "maze_platform_h2d_300x300_v1.stl",
        "position": (230.0, 0.0),
        "pockets": {
            "north": (150.0,),
            "east": (150.0,),
            "south": (150.0,),
            "west": (150.0,),
        },
    },
)


def _verify_file(path, expected_sha256, label):
    if not os.path.isfile(path):
        raise ValueError("Missing reviewed %s: %s" % (label, path))
    actual = _sha256(path)
    if actual != expected_sha256:
        raise ValueError(
            "%s fingerprint changed; review it before regeneration (expected %s, got %s)"
            % (label, expected_sha256, actual)
        )
    return actual


def verify_source_receipts():
    return {
        "params": _verify_file(PARAMS_PATH, EXPECTED_PARAMS_SHA256, "parameter file"),
        "source_3dm": _verify_file(SOURCE_3DM_PATH, EXPECTED_SOURCE_SHA256, "source Rhino model"),
        "source_tile": _verify_file(SOURCE_TILE_PATH, EXPECTED_TILE_SHA256, "source 200 x 200 tile"),
        "source_bridge": _verify_file(SOURCE_BRIDGE_PATH, EXPECTED_BRIDGE_SHA256, "source bridge"),
        "source_cutter": _verify_file(SOURCE_CUTTER_PATH, EXPECTED_CUTTER_SHA256, "source recess cutter"),
        "current_connector": _verify_file(
            CURRENT_CONNECTOR_PATH,
            EXPECTED_CURRENT_CONNECTOR_SHA256,
            "current rounded connector",
        ),
    }


def load_reviewed_spec():
    spec = load_spec(PARAMS_PATH)
    expected = {
        "tile_size": 200.0,
        "tile_height": 10.0,
        "pocket_depth": 8.0,
        "top_skin": 2.0,
        "dovetail_length": 50.0,
        "dovetail_neck_width": 22.0,
        "dovetail_tail_width": 46.0,
        "connector_thickness": 6.0,
        "pocket_clearance": 0.2,
    }
    for field, expected_value in expected.items():
        actual = float(getattr(spec, field))
        if abs(actual - expected_value) > 1.0e-9:
            raise ValueError(
                "Reviewed connector parameter %s changed: expected %.3f, got %.3f"
                % (field, expected_value, actual)
            )
    if abs(spec.pocket_depth + spec.top_skin - spec.tile_height) > 1.0e-9:
        raise ValueError("Pocket depth plus top skin must equal platform height")
    return spec


def _unique_points(geometry, places=7):
    result = set()
    for vertex in geometry.Vertices:
        point = vertex.Location
        result.add((round(float(point.X), places), round(float(point.Y), places), round(float(point.Z), places)))
    return tuple(sorted(result))


def _classify_cutter_geometry(index, geometry, name=""):
    if geometry.__class__.__name__ != "Brep" or not bool(getattr(geometry, "IsSolid", False)):
        return None
    points = _unique_points(geometry)
    z_values = sorted({point[2] for point in points})
    xy_values = sorted({(point[0], point[1]) for point in points})
    if len(z_values) != 2 or len(xy_values) != 4:
        return None
    depth = z_values[1] - z_values[0]
    if not (7.9 <= depth <= 8.1):
        return None
    x_values = sorted({point[0] for point in xy_values})
    y_values = sorted({point[1] for point in xy_values})
    record = {
        "index": int(index),
        "name": name or "",
        "geometry": geometry,
        "depth": depth,
        "z_min": z_values[0],
        "z_max": z_values[1],
    }
    if len(y_values) == 2:
        widths = {}
        for y in y_values:
            xs = [x for x, point_y in xy_values if point_y == y]
            if len(xs) != 2:
                return None
            widths[y] = max(xs) - min(xs)
        outer_coordinate = min(widths, key=widths.get)
        inner_coordinate = max(widths, key=widths.get)
        outer_width = widths[outer_coordinate]
        inner_width = widths[inner_coordinate]
        side = "south" if outer_coordinate == y_values[0] else "north"
        outer_points = [(x, y) for x, y in xy_values if y == outer_coordinate]
        outer_center = (sum(point[0] for point in outer_points) / 2.0, outer_coordinate)
        full_span = y_values[1] - y_values[0]
        record.update(
            {
                "side": side,
                "long_axis": "y",
                "outer_width": outer_width,
                "inner_width": inner_width,
                "full_span": full_span,
                "outer_center": outer_center,
            }
        )
    elif len(x_values) == 2:
        widths = {}
        for x in x_values:
            ys = [y for point_x, y in xy_values if point_x == x]
            if len(ys) != 2:
                return None
            widths[x] = max(ys) - min(ys)
        outer_coordinate = min(widths, key=widths.get)
        inner_coordinate = max(widths, key=widths.get)
        outer_width = widths[outer_coordinate]
        inner_width = widths[inner_coordinate]
        side = "west" if outer_coordinate == x_values[0] else "east"
        outer_points = [(x, y) for x, y in xy_values if x == outer_coordinate]
        outer_center = (outer_coordinate, sum(point[1] for point in outer_points) / 2.0)
        full_span = x_values[1] - x_values[0]
        record.update(
            {
                "side": side,
                "long_axis": "x",
                "outer_width": outer_width,
                "inner_width": inner_width,
                "full_span": full_span,
                "outer_center": outer_center,
            }
        )
    else:
        return None
    if not (
        20.0 <= record["outer_width"] <= 25.0
        and 44.0 <= record["inner_width"] <= 49.0
        and 48.0 <= record["full_span"] <= 52.0
        and record["outer_width"] < record["inner_width"]
    ):
        return None
    return record


def classify_source_cutters(model_objects):
    by_side = {}
    for index, model_object in enumerate(model_objects):
        record = _classify_cutter_geometry(
            index,
            model_object.Geometry,
            getattr(model_object.Attributes, "Name", ""),
        )
        if record is None:
            continue
        side = record["side"]
        if side in by_side:
            raise ValueError("Source cutter selection is ambiguous for %s" % side)
        by_side[side] = record
    if set(by_side) != set(SIDES):
        raise ValueError("Source Rhino model does not expose exactly one reusable cutter for every side")
    reference = by_side["south"]
    for side in SIDES:
        record = by_side[side]
        for field in ("outer_width", "inner_width", "full_span", "depth"):
            if abs(record[field] - reference[field]) > 1.0e-5:
                raise ValueError("Source %s cutter does not match the other cutter solids" % side)
    return by_side


def load_source_cutters_external(path=SOURCE_3DM_PATH):
    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("External source-cutter validation requires rhino3dm") from exc
    model = rhino3dm.File3dm.Read(path)
    if model is None:
        raise ValueError("Could not read source Rhino model: %s" % path)
    return classify_source_cutters(model.Objects)


def pocket_profile(spec, source_cutters=None):
    if source_cutters is not None:
        cutters = source_cutters
    elif Rhino is not None:
        _model, cutters = load_source_cutters_rhino()
    else:
        cutters = load_source_cutters_external()
    reference = cutters["south"]
    profile = {
        "full_span": reference["full_span"],
        "outer_overrun": spec.pocket_clearance,
        "inboard_depth": reference["full_span"] - spec.pocket_clearance,
        "opening_width": reference["outer_width"],
        "inner_width": reference["inner_width"],
        "depth": reference["depth"],
    }
    expected = {
        "full_span": spec.dovetail_length + 2.0 * spec.pocket_clearance,
        "inboard_depth": spec.dovetail_length + spec.pocket_clearance,
        "opening_width": spec.dovetail_neck_width + 2.0 * spec.pocket_clearance,
        "inner_width": spec.dovetail_tail_width + 2.0 * spec.pocket_clearance,
        "depth": spec.pocket_depth,
    }
    for field, expected_value in expected.items():
        if abs(profile[field] - expected_value) > 1.0e-5:
            raise ValueError(
                "Actual source cutter %s %.6f does not match reviewed receipt %.6f"
                % (field, profile[field], expected_value)
            )
    return profile


def edge_length(platform, side):
    return platform["width"] if side in ("north", "south") else platform["height"]


def tile_alignment_offsets(platform, side, spec):
    """Return centered placement offsets for a 200 mm tile along an edge."""

    return tuple(center - spec.tile_size / 2.0 for center in platform["pockets"][side])


def _pocket_footprint(platform, side, center, spec):
    profile = pocket_profile(spec)
    half_width = profile["inner_width"] / 2.0
    length = profile["inboard_depth"]
    width = platform["width"]
    height = platform["height"]
    if side == "south":
        return (center - half_width, 0.0, center + half_width, length)
    if side == "north":
        return (center - half_width, height - length, center + half_width, height)
    if side == "west":
        return (0.0, center - half_width, length, center + half_width)
    if side == "east":
        return (width - length, center - half_width, width, center + half_width)
    raise ValueError("Unknown side: %s" % side)


def _rectangles_overlap(first, second, tolerance=1.0e-9):
    overlap_x = min(first[2], second[2]) - max(first[0], second[0])
    overlap_y = min(first[3], second[3]) - max(first[1], second[1])
    return overlap_x > tolerance and overlap_y > tolerance


def validate_platform_layout(platform, spec):
    width = float(platform["width"])
    height = float(platform["height"])
    if width not in (200.0, 300.0) or height != 300.0:
        raise ValueError("H2D platform dimensions must be the reviewed 200/300 mm layouts")
    profile = pocket_profile(spec)
    footprints = []
    placements = {}
    for side in SIDES:
        centers = tuple(float(value) for value in platform["pockets"].get(side, ()))
        if not centers:
            raise ValueError("Every adapter edge must have at least one connector pocket")
        along_length = edge_length(platform, side)
        for center in centers:
            if center - profile["inner_width"] / 2.0 <= 0.0:
                raise ValueError("%s pocket at %.1f mm is too close to an edge corner" % (side, center))
            if center + profile["inner_width"] / 2.0 >= along_length:
                raise ValueError("%s pocket at %.1f mm is too close to an edge corner" % (side, center))
            footprints.append((side, center, _pocket_footprint(platform, side, center, spec)))

        offsets = tile_alignment_offsets(platform, side, spec)
        maximum_offset = along_length - spec.tile_size
        expected_offsets = (maximum_offset / 2.0,)
        if offsets != expected_offsets:
            raise ValueError(
                "%s %s-edge pockets do not align with centered 200 mm tile placements: %s"
                % (platform["key"], side, offsets)
            )
        placements[side] = offsets

    for first, second in itertools.combinations(footprints, 2):
        if _rectangles_overlap(first[2], second[2]):
            raise ValueError(
                "%s pockets overlap: %s %.1f and %s %.1f"
                % (platform["key"], first[0], first[1], second[0], second[1])
            )
    return {
        "pocket_count": len(footprints),
        "placements": placements,
    }


def validate_all_layouts(spec):
    results = {}
    for platform in PLATFORMS:
        results[platform["key"]] = validate_platform_layout(platform, spec)
    return results


def pocket_layout_receipt(platform):
    return ";".join(
        "%s:%s" % (side, ",".join("%.1f" % value for value in platform["pockets"][side]))
        for side in SIDES
    )


def expected_inner_corners(platform, spec):
    """Expected tail corners at the 8 mm pocket roof for STL read-back."""

    profile = pocket_profile(spec)
    half_width = profile["inner_width"] / 2.0
    length = profile["inboard_depth"]
    result = []
    for side in SIDES:
        for center in platform["pockets"][side]:
            if side == "south":
                result.extend(((center - half_width, length), (center + half_width, length)))
            elif side == "north":
                result.extend(
                    (
                        (center - half_width, platform["height"] - length),
                        (center + half_width, platform["height"] - length),
                    )
                )
            elif side == "west":
                result.extend(((length, center - half_width), (length, center + half_width)))
            elif side == "east":
                result.extend(
                    (
                        (platform["width"] - length, center - half_width),
                        (platform["width"] - length, center + half_width),
                    )
                )
    return tuple(result)


def _read_stl_vertices(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < 84:
        raise ValueError("STL is shorter than its header: %s" % path)
    count = struct.unpack_from("<I", data, 80)[0]
    if len(data) != 84 + 50 * count:
        raise ValueError("STL binary length mismatch: %s" % path)
    vertices = []
    for index in range(count):
        record = struct.unpack_from("<12fH", data, 84 + 50 * index)
        values = record[3:12]
        vertices.extend((tuple(values[0:3]), tuple(values[3:6]), tuple(values[6:9])))
    return vertices


def validate_connector_fit(path, label, spec, source_cutters=None):
    """Prove an X-oriented connector STL fits the actual source cutter envelope."""

    _triangle_count, bounds = _read_binary_stl(path)
    profile = pocket_profile(spec, source_cutters)
    length = bounds[3] - bounds[0]
    width = bounds[4] - bounds[1]
    height = bounds[5] - bounds[2]
    _assert_close(length, 2.0 * spec.dovetail_length, 0.01, "%s length" % label)
    _assert_close(height, spec.connector_thickness, 0.01, "%s thickness" % label)
    if width >= profile["inner_width"]:
        raise ValueError("%s is too wide for the actual source cutter" % label)
    center_x = (bounds[0] + bounds[3]) / 2.0
    center_y = (bounds[1] + bounds[4]) / 2.0
    minimum_planar_clearance = float("inf")
    for x, y, z in _read_stl_vertices(path):
        distance = abs(x - center_x)
        if distance > spec.dovetail_length + 0.01:
            raise ValueError("%s extends beyond the 50 mm half-pocket length" % label)
        fraction = (distance + profile["outer_overrun"]) / profile["full_span"]
        allowed_half_width = profile["opening_width"] / 2.0 + (
            profile["inner_width"] - profile["opening_width"]
        ) / 2.0 * fraction
        planar_clearance = allowed_half_width - abs(y - center_y)
        minimum_planar_clearance = min(minimum_planar_clearance, planar_clearance)
        if planar_clearance < -0.005:
            raise ValueError(
                "%s exceeds the source pocket envelope by %.4f mm" % (label, -planar_clearance)
            )
        if z < bounds[2] - 0.001 or z > bounds[2] + profile["depth"] + 0.001:
            raise ValueError("%s exceeds the 8 mm source pocket depth" % label)
    vertical_clearance = profile["depth"] - height
    if vertical_clearance < 0.0:
        raise ValueError("%s is thicker than the actual source pocket" % label)
    return {
        "length": length,
        "width": width,
        "height": height,
        "minimum_planar_clearance": minimum_planar_clearance,
        "vertical_clearance": vertical_clearance,
    }


def _has_vertex(vertices, expected, tolerance=0.002):
    return any(
        abs(vertex[0] - expected[0]) <= tolerance
        and abs(vertex[1] - expected[1]) <= tolerance
        and abs(vertex[2] - expected[2]) <= tolerance
        for vertex in vertices
    )


def _validate_stl_pocket_receipt(path, platform, spec):
    vertices = _read_stl_vertices(path)
    z_values = {round(vertex[2], 3) for vertex in vertices}
    if round(spec.pocket_depth, 3) not in z_values:
        raise ValueError("%s does not contain the required 8 mm pocket roof" % os.path.basename(path))
    if round(spec.tile_height, 3) not in z_values:
        raise ValueError("%s does not contain the required 10 mm platform top" % os.path.basename(path))
    for x, y in expected_inner_corners(platform, spec):
        if not _has_vertex(vertices, (x, y, spec.pocket_depth)):
            raise ValueError(
                "%s is missing expected pocket corner (%.3f, %.3f, %.3f)"
                % (os.path.basename(path), x, y, spec.pocket_depth)
            )


def check_generated_outputs(output_dir=OUTPUT_DIR, require_outputs=False):
    expected_paths = [os.path.join(output_dir, platform["filename"]) for platform in PLATFORMS]
    combined_path = os.path.join(output_dir, os.path.basename(OUTPUT_3DM))
    expected_paths.append(combined_path)
    missing = [path for path in expected_paths if not os.path.isfile(path)]
    if missing:
        if require_outputs or len(missing) != len(expected_paths):
            raise ValueError(
                "H2D output set is incomplete; missing: %s"
                % ", ".join(os.path.basename(path) for path in missing)
            )
        print("OUTPUTS not generated yet; run this script through Rhino 8")
        return []

    spec = load_reviewed_spec()
    summaries = []
    for platform in PLATFORMS:
        path = os.path.join(output_dir, platform["filename"])
        triangle_count, bounds = _read_binary_stl(path)
        expected = (0.0, 0.0, 0.0, platform["width"], platform["height"], spec.tile_height)
        for index, (actual, target) in enumerate(zip(bounds, expected)):
            _assert_close(actual, target, BOUNDS_TOLERANCE, "%s STL bound %d" % (platform["key"], index))
        _validate_stl_pocket_receipt(path, platform, spec)
        summaries.append((platform["key"], triangle_count, bounds))

    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("Checking the combined H2D 3dm requires rhino3dm") from exc
    model = rhino3dm.File3dm.Read(combined_path)
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Combined H2D Rhino file is unreadable or is not in millimeters")
    solids = [obj for obj in model.Objects if bool(getattr(obj.Geometry, "IsSolid", False))]
    if len(solids) != len(PLATFORMS):
        raise ValueError("Combined H2D Rhino file must contain exactly two closed solids")
    by_name = {obj.Attributes.Name: obj for obj in solids}
    for platform in PLATFORMS:
        name = "maze_platform_h2d_%s_v1" % platform["key"]
        if name not in by_name:
            raise ValueError("Combined H2D Rhino file is missing %s" % name)
        attributes = by_name[name].Attributes
        if attributes.GetUserString("pocket_centers_mm") != pocket_layout_receipt(platform):
            raise ValueError("Combined H2D Rhino pocket receipt is wrong for %s" % name)
        receipt = attributes.GetUserString("verified_trimmed_bounds_mm")
        if not receipt:
            raise ValueError("Combined H2D Rhino bounds receipt is missing for %s" % name)
        recorded = tuple(float(value) for value in receipt.split(","))
        position = platform["position"]
        expected = (
            position[0],
            position[1],
            0.0,
            position[0] + platform["width"],
            position[1] + platform["height"],
            spec.tile_height,
        )
        if len(recorded) != 6:
            raise ValueError("Combined H2D Rhino bounds receipt is incomplete for %s" % name)
        for index, (actual, target) in enumerate(zip(recorded, expected)):
            _assert_close(actual, target, BOUNDS_TOLERANCE, "%s recorded bound %d" % (name, index))
        if attributes.GetUserString("source_bridge_sha256") != EXPECTED_BRIDGE_SHA256:
            raise ValueError("Combined H2D Rhino bridge receipt is wrong for %s" % name)
        if attributes.GetUserString("current_connector_sha256") != EXPECTED_CURRENT_CONNECTOR_SHA256:
            raise ValueError("Combined H2D Rhino current-connector receipt is wrong for %s" % name)

    for key, triangle_count, bounds in summaries:
        print("OUTPUT OK %-7s triangles=%d bounds=%s" % (key, triangle_count, _format_bounds(bounds)))
    print("OUTPUT OK %s solids=%d" % (os.path.basename(combined_path), len(solids)))
    return summaries


def check_only(output_dir=OUTPUT_DIR, require_outputs=False):
    receipts = verify_source_receipts()
    spec = load_reviewed_spec()
    source_cutters = load_source_cutters_external()
    profile = pocket_profile(spec, source_cutters)
    tracked_fit = validate_connector_fit(SOURCE_BRIDGE_PATH, "tracked standard bridge", spec, source_cutters)
    current_fit = validate_connector_fit(CURRENT_CONNECTOR_PATH, "current rounded connector", spec, source_cutters)
    layouts = validate_all_layouts(spec)
    print(
        "SOURCE OK platform=%.1f mm pocket=%.1f mm skin=%.1f mm bridge=%.1fx%.1f/%.1f mm clearance=%.2f mm"
        % (
            spec.tile_height,
            spec.pocket_depth,
            spec.top_skin,
            spec.dovetail_length * 2.0,
            spec.dovetail_neck_width,
            spec.dovetail_tail_width,
            spec.pocket_clearance,
        )
    )
    for label in (
        "params",
        "source_3dm",
        "source_tile",
        "source_bridge",
        "source_cutter",
        "current_connector",
    ):
        print("  %-13s sha256=%s" % (label, receipts[label]))
    print(
        "INTERFACE OK actual-cutters span=%.1f mm inboard=%.1f mm opening=%.1f mm inner=%.1f mm depth=%.1f mm"
        % (
            profile["full_span"],
            profile["inboard_depth"],
            profile["opening_width"],
            profile["inner_width"],
            profile["depth"],
        )
    )
    print(
        "CONNECTOR OK tracked=%.3fx%.3fx%.3f mm current=%.3fx%.3fx%.3f mm vertical-clearance=%.3f mm"
        % (
            tracked_fit["length"],
            tracked_fit["width"],
            tracked_fit["height"],
            current_fit["length"],
            current_fit["width"],
            current_fit["height"],
            current_fit["vertical_clearance"],
        )
    )
    for platform in PLATFORMS:
        layout = layouts[platform["key"]]
        placement_text = "; ".join(
            "%s=%s" % (side, ",".join("%.0f" % value for value in layout["placements"][side]))
            for side in SIDES
        )
        print(
            "LAYOUT OK %s %.0fx%.0f pockets=%d centers=%s tile-offsets=%s"
            % (
                platform["key"],
                platform["width"],
                platform["height"],
                layout["pocket_count"],
                pocket_layout_receipt(platform),
                placement_text,
            )
        )
    check_generated_outputs(output_dir, require_outputs=require_outputs)


def _box(min_x, min_y, min_z, max_x, max_y, max_z):
    bbox = Rhino.Geometry.BoundingBox(
        Rhino.Geometry.Point3d(min_x, min_y, min_z),
        Rhino.Geometry.Point3d(max_x, max_y, max_z),
    )
    return Rhino.Geometry.Brep.CreateFromBox(bbox)


def load_source_cutters_rhino(path=SOURCE_3DM_PATH):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None:
        raise RuntimeError("Could not read source Rhino model: %s" % path)
    if model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Source Rhino model must use millimeters")
    cutters = classify_source_cutters(model.Objects)
    return model, cutters


def _placed_source_cutter(source_record, platform, side, center, spec):
    if source_record["side"] != side:
        raise RuntimeError("Source cutter orientation does not match requested side %s" % side)
    if side == "south":
        target_outer_center = (center, -spec.pocket_clearance)
    elif side == "north":
        target_outer_center = (center, platform["height"] + spec.pocket_clearance)
    elif side == "west":
        target_outer_center = (-spec.pocket_clearance, center)
    elif side == "east":
        target_outer_center = (platform["width"] + spec.pocket_clearance, center)
    else:
        raise ValueError("Unknown side: %s" % side)
    cutter = source_record["geometry"].DuplicateBrep()
    translation = Rhino.Geometry.Transform.Translation(
        target_outer_center[0] - source_record["outer_center"][0],
        target_outer_center[1] - source_record["outer_center"][1],
        -source_record["z_min"],
    )
    if not cutter.Transform(translation):
        raise RuntimeError("Could not position actual source cutter for %s %.1f" % (side, center))
    return _validate_brep(cutter, "%s %.1f actual source cutter" % (side, center))


def _build_platform(platform, spec, source_cutters):
    result = _box(0.0, 0.0, 0.0, platform["width"], platform["height"], spec.tile_height)
    tolerance = MODEL_TOLERANCE
    for side in SIDES:
        for center in platform["pockets"][side]:
            cutter = _placed_source_cutter(source_cutters[side], platform, side, center, spec)
            pieces = Rhino.Geometry.Brep.CreateBooleanDifference(result, cutter, tolerance)
            result = _single_valid_solid(
                pieces,
                "%s after %s %.1f pocket" % (platform["key"], side, center),
            )
    return _validate_platform_brep(result, platform, spec)


def _validate_platform_brep(brep, platform, spec):
    _validate_brep(brep, platform["key"])
    bounds = _bounds_tuple(brep.GetBoundingBox(True))
    expected = (0.0, 0.0, 0.0, platform["width"], platform["height"], spec.tile_height)
    for index, (actual, target) in enumerate(zip(bounds, expected)):
        _assert_close(actual, target, BOUNDS_TOLERANCE, "%s bound %d" % (platform["key"], index))
    volume = abs(brep.GetVolume())
    full_volume = platform["width"] * platform["height"] * spec.tile_height
    if not math.isfinite(volume) or not (0.70 * full_volume < volume < full_volume):
        raise RuntimeError("%s platform volume %.3f mm3 is implausible" % (platform["key"], volume))
    return brep


def _add_layer(doc, parent_index, name, color):
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    layer.ParentLayerId = doc.Layers[parent_index].Id
    layer.Color = color
    index = doc.Layers.Add(layer)
    if index < 0:
        raise RuntimeError("Could not add Rhino layer: %s" % name)
    return index


def _translated_copy(brep, x, y):
    duplicate = brep.DuplicateBrep()
    duplicate.Transform(Rhino.Geometry.Transform.Translation(x, y, 0.0))
    return duplicate


def _add_platform_object(doc, brep, platform, layer_index, receipts):
    object_id = doc.Objects.AddBrep(brep)
    rhino_object = doc.Objects.FindId(object_id)
    if rhino_object is None:
        raise RuntimeError("Could not add %s to combined Rhino file" % platform["key"])
    attributes = rhino_object.Attributes
    attributes.Name = "maze_platform_h2d_%s_v1" % platform["key"]
    attributes.LayerIndex = layer_index
    attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
    attributes.SetUserString("dimensions_mm", "%.1f x %.1f x 10.0" % (platform["width"], platform["height"]))
    attributes.SetUserString("pocket_centers_mm", pocket_layout_receipt(platform))
    attributes.SetUserString("source_params_sha256", receipts["params"])
    attributes.SetUserString("source_3dm_sha256", receipts["source_3dm"])
    attributes.SetUserString("source_tile_sha256", receipts["source_tile"])
    attributes.SetUserString("source_bridge_sha256", receipts["source_bridge"])
    attributes.SetUserString("source_cutter_sha256", receipts["source_cutter"])
    attributes.SetUserString("current_connector_sha256", receipts["current_connector"])
    bounds = _bounds_tuple(brep.GetBoundingBox(True))
    attributes.SetUserString("verified_trimmed_bounds_mm", ",".join("%.4f" % value for value in bounds))
    if not doc.Objects.ModifyAttributes(object_id, attributes, True):
        raise RuntimeError("Could not set attributes for %s" % platform["key"])


def _validate_saved_3dm(path, spec):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None:
        raise RuntimeError("Could not reopen combined H2D Rhino file")
    by_name = {obj.Attributes.Name: obj for obj in model.Objects}
    if len(by_name) != len(PLATFORMS):
        raise RuntimeError("Combined H2D Rhino file must contain exactly two objects")
    for platform in PLATFORMS:
        name = "maze_platform_h2d_%s_v1" % platform["key"]
        if name not in by_name:
            raise RuntimeError("Saved H2D Rhino file is missing %s" % name)
        geometry = _validate_brep(by_name[name].Geometry, "saved %s" % name)
        bounds = _bounds_tuple(geometry.GetBoundingBox(True))
        position = platform["position"]
        expected = (
            position[0],
            position[1],
            0.0,
            position[0] + platform["width"],
            position[1] + platform["height"],
            spec.tile_height,
        )
        for index, (actual, target) in enumerate(zip(bounds, expected)):
            _assert_close(actual, target, BOUNDS_TOLERANCE, "saved %s bound %d" % (name, index))
    print("REOPENED %s: two closed solids with verified accurate trimmed bounds" % os.path.basename(path))


def _save_combined(platform_breps, path, spec, receipts):
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is None:
        raise RuntimeError("Could not create a headless Rhino output document")
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    doc.ModelAbsoluteTolerance = MODEL_TOLERANCE
    doc.ModelAngleToleranceRadians = math.radians(0.25)
    parent = Rhino.DocObjects.Layer()
    parent.Name = "H2DCompatiblePlatforms"
    parent.Color = _color(90, 105, 125)
    parent_index = doc.Layers.Add(parent)
    colors = (_color(54, 119, 191), _color(231, 145, 57))
    for platform, color in zip(PLATFORMS, colors):
        layer_index = _add_layer(doc, parent_index, platform["label"], color)
        position = platform["position"]
        preview = _translated_copy(platform_breps[platform["key"]], position[0], position[1])
        _add_platform_object(doc, preview, platform, layer_index, receipts)
    doc.Strings.SetString("generator", "scripts/generate_h2d_compatible_platforms.py")
    doc.Strings.SetString("canonical_orientation", "X is width; Y is length; pockets open from underside")
    doc.Strings.SetString("source_params_sha256", receipts["params"])
    doc.Strings.SetString("source_bridge_sha256", receipts["source_bridge"])
    doc.Strings.SetString("current_connector_sha256", receipts["current_connector"])
    doc.Strings.SetString("pocket_depth_mm", "%.1f" % spec.pocket_depth)
    doc.Strings.SetString("top_skin_mm", "%.1f" % spec.top_skin)
    options = Rhino.FileIO.FileWriteOptions()
    options.SuppressDialogBoxes = True
    options.WriteSelectedObjectsOnly = False
    options.WriteGeometryOnly = False
    if not doc.WriteFile(path, options):
        raise RuntimeError("Could not write combined H2D Rhino file: %s" % path)
    doc.Dispose()
    _validate_saved_3dm(path, spec)


def generate(output_dir=OUTPUT_DIR):
    if Rhino is None or System is None:
        raise RuntimeError("CAD generation must be run through Rhino 8")
    receipts = verify_source_receipts()
    spec = load_reviewed_spec()
    _source_model, source_cutters = load_source_cutters_rhino()
    pocket_profile(spec, source_cutters)
    validate_connector_fit(SOURCE_BRIDGE_PATH, "tracked standard bridge", spec, source_cutters)
    validate_connector_fit(CURRENT_CONNECTOR_PATH, "current rounded connector", spec, source_cutters)
    validate_all_layouts(spec)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    platform_breps = {}
    for platform in PLATFORMS:
        brep = _build_platform(platform, spec, source_cutters)
        platform_breps[platform["key"]] = brep
        triangles = _mesh_triangles(brep, platform["key"])
        numeric_triangles = [
            tuple((float(vertex.X), float(vertex.Y), float(vertex.Z)) for vertex in triangle)
            for triangle in triangles
        ]
        topology = _audit_triangle_topology(numeric_triangles, platform["key"])
        path = os.path.join(output_dir, platform["filename"])
        _write_binary_stl(path, platform["label"], triangles)
        _validate_stl_pocket_receipt(path, platform, spec)
        print(
            "WROTE %-50s triangles=%d volume=%.1f mm3 bounds=%s"
            % (
                os.path.relpath(path, ROOT_DIR),
                len(triangles),
                topology["signed_volume"],
                _format_bounds(_bounds_tuple(brep.GetBoundingBox(True))),
            )
        )
    combined_path = os.path.join(output_dir, os.path.basename(OUTPUT_3DM))
    _save_combined(platform_breps, combined_path, spec, receipts)
    print("WROTE %s" % os.path.relpath(combined_path, ROOT_DIR))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate H2D platforms compatible with the X1C maze connector")
    parser.add_argument("--check", action="store_true", help="verify source receipts and outputs without Rhino")
    parser.add_argument("--require-outputs", action="store_true", help="make --check fail if outputs are missing")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="H2D output folder")
    args = parser.parse_args(argv)
    if args.check:
        check_only(args.output_dir, require_outputs=args.require_outputs)
        return
    if Rhino is None:
        check_only(args.output_dir, require_outputs=False)
        print("Rhino is unavailable, so CAD generation was skipped.")
        return
    generate(args.output_dir)


if __name__ == "__main__":
    if Rhino is None:
        main()
    else:
        transcript_path = "/tmp/gridmaze_h2d_platform_generation.log"
        with open(transcript_path, "w") as transcript:
            try:
                with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
                    main()
                transcript.write("GENERATION OK\n")
            except Exception:
                traceback.print_exc(file=transcript)
                raise
