#!/usr/bin/env python3
r"""Generate the standalone 30-degree X1C maze ramp.

Rhino 8 generation::

    /Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
        /absolute/path/to/scripts/generate_30deg_ramp.py

External source/artifact validation::

    python3 scripts/generate_30deg_ramp.py --check --require-outputs
"""

from __future__ import print_function

import argparse
import contextlib
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

from generate_h2d_compatible_platforms import (
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    _build_platform,
    _placed_source_cutter,
    _validate_stl_pocket_receipt,
    load_reviewed_spec,
    load_source_cutters_external,
    load_source_cutters_rhino,
    pocket_layout_receipt,
    pocket_profile,
    validate_connector_fit,
    verify_source_receipts,
)
from generate_h2d_maze_variants import (
    inspect_source_walls_external,
    load_source_walls_rhino,
)
from generate_maze_piece_variants import (
    EXPECTED_SOURCE_SHA256,
    _assert_close,
    _audit_triangle_topology,
    _bounds_tuple,
    _color,
    _format_bounds,
    _read_binary_stl,
    _union,
    _validate_brep,
    _write_binary_stl,
)


OUTPUT_DIR = os.path.join(ROOT_DIR, "output", "ramp")
STL_FILENAME = "maze_piece_x1c_200x200_30deg_ramp_v1.stl"
THREEDM_FILENAME = "maze_piece_x1c_30deg_ramp_v1.3dm"
OUTPUT_STL = os.path.join(OUTPUT_DIR, STL_FILENAME)
OUTPUT_3DM = os.path.join(OUTPUT_DIR, THREEDM_FILENAME)
OBJECT_NAME = "maze_piece_x1c_200x200_30deg_ramp_v1"

MODEL_TOLERANCE = 0.01
GEOMETRY_TOLERANCE = 0.002
ANGLE_DEGREES = 30.0
BASE_TOP_Z = 10.0
WALL_TOP_Z = 82.0
HIGH_SURFACE_Z = 84.0
RAMP_RISE = 74.0
RAMP_RUN = 128.1717597600969
RAMP_TOE_Y = 71.8282402399031
RAMP_SLOPE_LENGTH = 148.0
RAMP_X_MIN = 19.2
RAMP_X_MAX = 180.8
RAMP_WIDTH = 161.6
RAMP_UNDERLAP = 0.05
MAX_ALLOWED_UNDERLAP = 0.10
POCKET_VOID_TOP_Z = 8.0
POCKET_VOID_VERTICAL_CLEARANCE = 1.95

STL_MESH_TOLERANCE = 0.04
STL_MESH_MINIMUM_EDGE = 0.05
STL_MESH_MAXIMUM_EDGE = 8.0
STL_VOLUME_RELATIVE_TOLERANCE = 5.0e-4
STL_TRIANGLE_LIMIT = 50000
STL_MESH_RECEIPT = (
    "Rhino Brep mesher tolerance=0.040 mm; relative tolerance=0; minimum edge=0.050 mm; "
    "maximum edge=8.000 mm; SimplePlanes=1; RefineGrid=1; "
    "closed-manifold single-shell consistent-orientation audit; "
    "volume relative error<=0.000500"
)

RAMP_PLATFORM = {
    "key": "x1c_200x200_30deg_ramp",
    "label": "X1C 200 x 200 30 Degree Ramp",
    "width": 200.0,
    "height": 200.0,
    "filename": STL_FILENAME,
    "position": (0.0, 0.0),
    "pockets": {
        "north": (100.0,),
        "east": (100.0,),
        "south": (100.0,),
        "west": (100.0,),
    },
}

SOURCE_WALL_BOUNDS = {
    "west": (0.0, 0.0, 10.0, 19.2, 200.0, 82.0),
    "east": (180.8, 0.0, 10.0, 200.0, 200.0, 82.0),
}
SOURCE_WALL_OBJECTS = (13, 14)
RAMP_METHOD = (
    "exact pocketed reviewed X1C base plus literal source wall Breps 13/14; "
    "exact triangular YZ ramp profile extruded 161.6 mm in X and split at sharp profile kinks; "
    "0.05 mm hidden base underlap for Boolean fusion; no scaling"
)
EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT = (
    "north=0.000000000;east=0.000000000;south=0.000000000;west=0.000000000"
)


def ramp_surface_z(y):
    """Return the exact ramp-plane height at longitudinal coordinate *y*."""

    return BASE_TOP_Z + math.tan(math.radians(ANGLE_DEGREES)) * (float(y) - RAMP_TOE_Y)


def exposed_ramp_volume():
    return RAMP_WIDTH * RAMP_RUN * RAMP_RISE / 2.0


def ramp_contract_receipt():
    return {
        "angle_degrees": "%.9f" % ANGLE_DEGREES,
        "rise_mm": "%.9f" % RAMP_RISE,
        "horizontal_run_mm": "%.13f" % RAMP_RUN,
        "slope_length_mm": "%.9f" % RAMP_SLOPE_LENGTH,
        "toe_y_mm": "%.13f" % RAMP_TOE_Y,
        "low_edge_mm": "x=19.2..180.8;y=%.13f;z=10" % RAMP_TOE_Y,
        "high_edge_mm": "x=19.2..180.8;y=200;z=84",
        "ramp_width_mm": "%.9f" % RAMP_WIDTH,
        "ramp_x_extent_mm": "19.2..180.8",
        "base_underlap_mm": "%.9f" % RAMP_UNDERLAP,
        "pocket_void_z_mm": "0.000000000..8.000000000",
        "ramp_underlap_z_mm": "9.950000000..10.000000000",
        "pocket_void_vertical_clearance_mm": "%.9f" % POCKET_VOID_VERTICAL_CLEARANCE,
    }


def validate_static_contract():
    """Validate the numeric ramp contract without requiring RhinoCommon."""

    _assert_close(RAMP_RUN, 74.0 / math.tan(math.radians(30.0)), 1.0e-12, "ramp run")
    _assert_close(RAMP_TOE_Y, 200.0 - RAMP_RUN, 1.0e-12, "ramp toe")
    _assert_close(RAMP_SLOPE_LENGTH, math.hypot(RAMP_RUN, RAMP_RISE), 1.0e-12, "slope length")
    _assert_close(ramp_surface_z(RAMP_TOE_Y), BASE_TOP_Z, 1.0e-12, "toe height")
    _assert_close(ramp_surface_z(200.0), HIGH_SURFACE_Z, 1.0e-12, "high-edge height")
    actual_angle = math.degrees(math.atan2(RAMP_RISE, RAMP_RUN))
    _assert_close(actual_angle, ANGLE_DEGREES, 1.0e-12, "ramp angle")
    _assert_close(RAMP_X_MAX - RAMP_X_MIN, RAMP_WIDTH, 1.0e-12, "ramp width")
    if not (0.0 < RAMP_UNDERLAP <= MAX_ALLOWED_UNDERLAP):
        raise ValueError("Ramp underlap must be positive and no more than 0.10 mm")
    _assert_close(
        BASE_TOP_Z - RAMP_UNDERLAP - POCKET_VOID_TOP_Z,
        POCKET_VOID_VERTICAL_CLEARANCE,
        1.0e-12,
        "ramp-to-pocket vertical clearance",
    )
    expected_layout = {
        "north": (100.0,),
        "east": (100.0,),
        "south": (100.0,),
        "west": (100.0,),
    }
    if RAMP_PLATFORM["pockets"] != expected_layout:
        raise ValueError("Ramp platform must have exactly one centered pocket per side")
    if RAMP_PLATFORM["width"] != 200.0 or RAMP_PLATFORM["height"] != 200.0:
        raise ValueError("Ramp platform must remain exactly 200 x 200 mm")
    return ramp_contract_receipt()


def validate_source_wall_receipts():
    records = inspect_source_walls_external()
    if tuple(record["index"] for record in records) != SOURCE_WALL_OBJECTS:
        raise ValueError("Reviewed source walls are no longer objects 13/14")
    for label, record in zip(("west", "east"), records):
        for index, (actual, expected) in enumerate(zip(record["bounds"], SOURCE_WALL_BOUNDS[label])):
            _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s source wall bound %d" % (label, index))
        if record["faces"] != 10 or record["vertices"] != 15:
            raise ValueError("%s source wall topology no longer matches the reviewed Brep" % label)
    return records


def _read_stl_triangles(path):
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
                tuple(float(value) for value in coordinates[0:3]),
                tuple(float(value) for value in coordinates[3:6]),
                tuple(float(value) for value in coordinates[6:9]),
            )
        )
    return triangles


def _triangle_area(triangle):
    first, second, third = triangle
    first_edge = tuple(second[index] - first[index] for index in range(3))
    second_edge = tuple(third[index] - first[index] for index in range(3))
    cross = (
        first_edge[1] * second_edge[2] - first_edge[2] * second_edge[1],
        first_edge[2] * second_edge[0] - first_edge[0] * second_edge[2],
        first_edge[0] * second_edge[1] - first_edge[1] * second_edge[0],
    )
    return 0.5 * math.sqrt(sum(value * value for value in cross))


def _vertex_matches(vertex, expected, tolerance=GEOMETRY_TOLERANCE):
    return all(abs(vertex[index] - expected[index]) <= tolerance for index in range(3))


def validate_ramp_surface_triangles(triangles):
    """Prove the serialized STL retains the entire exact 30-degree top plane."""

    slope_triangles = []
    plane_tolerance = 0.003
    for triangle in triangles:
        if all(
            RAMP_X_MIN - plane_tolerance <= vertex[0] <= RAMP_X_MAX + plane_tolerance
            and RAMP_TOE_Y - plane_tolerance <= vertex[1] <= 200.0 + plane_tolerance
            and abs(vertex[2] - ramp_surface_z(vertex[1])) <= plane_tolerance
            for vertex in triangle
        ):
            slope_triangles.append(triangle)
    if not slope_triangles:
        raise ValueError("STL contains no triangles on the exact ramp surface")
    slope_area = sum(_triangle_area(triangle) for triangle in slope_triangles)
    expected_area = RAMP_WIDTH * RAMP_SLOPE_LENGTH
    _assert_close(slope_area, expected_area, 0.10, "serialized ramp surface area")
    slope_vertices = [vertex for triangle in slope_triangles for vertex in triangle]
    required = (
        (RAMP_X_MIN, RAMP_TOE_Y, BASE_TOP_Z),
        (RAMP_X_MAX, RAMP_TOE_Y, BASE_TOP_Z),
        (RAMP_X_MIN, 200.0, HIGH_SURFACE_Z),
        (RAMP_X_MAX, 200.0, HIGH_SURFACE_Z),
    )
    for expected in required:
        if not any(_vertex_matches(vertex, expected) for vertex in slope_vertices):
            raise ValueError("STL ramp surface is missing endpoint %s" % (expected,))
    return {
        "triangle_count": len(slope_triangles),
        "area": slope_area,
    }


def _parse_float(receipts, key):
    try:
        return float(receipts[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Ramp receipt %s is missing or invalid" % key)


def validate_ramp_receipts(receipts):
    expected = ramp_contract_receipt()
    for key, expected_value in expected.items():
        if receipts.get(key) != expected_value:
            raise ValueError("Ramp receipt %s is wrong" % key)
    if receipts.get("ramp_method") != RAMP_METHOD:
        raise ValueError("Ramp construction-method receipt is wrong")
    if receipts.get("pocket_centers_mm") != pocket_layout_receipt(RAMP_PLATFORM):
        raise ValueError("Ramp pocket-layout receipt is wrong")
    if receipts.get("source_3dm_sha256") != EXPECTED_SOURCE_SHA256:
        raise ValueError("Ramp source-model receipt is wrong")
    if receipts.get("source_params_sha256") != EXPECTED_PARAMS_SHA256:
        raise ValueError("Ramp parameter receipt is wrong")
    if receipts.get("source_bridge_sha256") != EXPECTED_BRIDGE_SHA256:
        raise ValueError("Ramp bridge receipt is wrong")
    if receipts.get("current_connector_sha256") != EXPECTED_CURRENT_CONNECTOR_SHA256:
        raise ValueError("Ramp current-connector receipt is wrong")
    if receipts.get("source_wall_objects") != "13,14":
        raise ValueError("Ramp source-wall object receipt is wrong")
    if receipts.get("source_wall_bounds_mm") != (
        "west=0,0,10,19.2,200,82;east=180.8,0,10,200,200,82"
    ):
        raise ValueError("Ramp source-wall bounds receipt is wrong")
    if receipts.get("stl_mesh_receipt") != STL_MESH_RECEIPT:
        raise ValueError("Ramp STL mesh receipt is wrong")
    if receipts.get("pocket_void_boolean_receipt") != EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT:
        raise ValueError("Ramp pocket-void Boolean receipt is wrong")
    return {
        "brep_volume": _parse_float(receipts, "brep_volume_mm3"),
        "stl_volume": _parse_float(receipts, "stl_signed_volume_mm3"),
    }


def check_generated_outputs(output_dir=OUTPUT_DIR, require_outputs=False):
    expected_names = {STL_FILENAME, THREEDM_FILENAME}
    actual_names = set()
    if os.path.isdir(output_dir):
        actual_names = {name for name in os.listdir(output_dir) if not name.startswith(".")}
    missing = expected_names - actual_names
    unexpected = actual_names - expected_names
    if missing:
        if require_outputs or actual_names:
            raise ValueError("Ramp output set is incomplete; missing: %s" % ", ".join(sorted(missing)))
        print("OUTPUTS not generated yet; run this script through Rhino 8")
        return None
    if unexpected:
        raise ValueError("Ramp output folder has unexpected files: %s" % ", ".join(sorted(unexpected)))

    spec = load_reviewed_spec()
    stl_path = os.path.join(output_dir, STL_FILENAME)
    triangle_count, bounds = _read_binary_stl(stl_path)
    if triangle_count > STL_TRIANGLE_LIMIT:
        raise ValueError("Ramp STL has avoidable mesh density: %d triangles" % triangle_count)
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 200.0, HIGH_SURFACE_Z)
    for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "ramp STL bound %d" % index)
    _validate_stl_pocket_receipt(stl_path, RAMP_PLATFORM, spec)
    triangles = _read_stl_triangles(stl_path)
    topology = _audit_triangle_topology(triangles, STL_FILENAME)
    slope = validate_ramp_surface_triangles(triangles)

    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("Checking the ramp 3dm requires rhino3dm") from exc
    model_path = os.path.join(output_dir, THREEDM_FILENAME)
    model = rhino3dm.File3dm.Read(model_path)
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Ramp 3dm is unreadable or not in millimeters")
    model_objects = list(model.Objects)
    if len(model_objects) != 1:
        raise ValueError("Ramp 3dm must contain exactly one object")
    model_object = model_objects[0]
    if model_object.Attributes.Name != OBJECT_NAME:
        raise ValueError("Ramp 3dm object name is wrong")
    if not bool(getattr(model_object.Geometry, "IsSolid", False)):
        raise ValueError("Ramp 3dm object is not a closed solid")
    object_receipts = {
        key: model_object.Attributes.GetUserString(key)
        for key in (
            tuple(ramp_contract_receipt().keys())
            + (
                "ramp_method",
                "pocket_centers_mm",
                "source_3dm_sha256",
                "source_params_sha256",
                "source_bridge_sha256",
                "current_connector_sha256",
                "source_wall_objects",
                "source_wall_bounds_mm",
                "stl_mesh_receipt",
                "pocket_void_boolean_receipt",
                "brep_volume_mm3",
                "stl_signed_volume_mm3",
                "mesh_volume_relative_error",
                "verified_trimmed_bounds_mm",
            )
        )
    }
    volume_receipts = validate_ramp_receipts(object_receipts)
    recorded_bounds = tuple(float(value) for value in object_receipts["verified_trimmed_bounds_mm"].split(","))
    if len(recorded_bounds) != 6:
        raise ValueError("Ramp 3dm bounds receipt is incomplete")
    for index, (actual, expected) in enumerate(zip(recorded_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "ramp 3dm recorded bound %d" % index)
    relative_volume_error = abs(topology["signed_volume"] - volume_receipts["brep_volume"]) / volume_receipts["brep_volume"]
    if relative_volume_error > STL_VOLUME_RELATIVE_TOLERANCE:
        raise ValueError("Serialized STL volume differs from Brep receipt by %.8f" % relative_volume_error)
    _assert_close(topology["signed_volume"], volume_receipts["stl_volume"], 0.10, "STL signed-volume receipt")
    recorded_error = _parse_float(object_receipts, "mesh_volume_relative_error")
    _assert_close(recorded_error, relative_volume_error, 1.0e-8, "mesh-volume error receipt")

    document_receipts = dict(model.Strings)
    if document_receipts.get("generator") != "scripts/generate_30deg_ramp.py":
        raise ValueError("Ramp 3dm generator receipt is wrong")
    validate_ramp_receipts(document_receipts)
    print(
        "OUTPUT OK %s triangles=%d shells=%d volume=%.3f slope_area=%.3f bounds=%s"
        % (
            STL_FILENAME,
            triangle_count,
            topology["component_count"],
            topology["signed_volume"],
            slope["area"],
            _format_bounds(bounds),
        )
    )
    print("OUTPUT OK %s objects=1 closed_solid=1" % THREEDM_FILENAME)
    return {
        "triangle_count": triangle_count,
        "bounds": bounds,
        "topology": topology,
        "slope": slope,
        "relative_volume_error": relative_volume_error,
    }


def check_only(output_dir=OUTPUT_DIR, require_outputs=False):
    validate_static_contract()
    receipts = verify_source_receipts()
    source_cutters = load_source_cutters_external()
    spec = load_reviewed_spec()
    profile = pocket_profile(spec, source_cutters)
    walls = validate_source_wall_receipts()
    tracked_fit = validate_connector_fit(
        os.path.join(ROOT_DIR, "output", "grid_maze_platform_bridge_v1.stl"),
        "tracked standard bridge",
        spec,
        source_cutters,
    )
    current_fit = validate_connector_fit(
        os.path.join(ROOT_DIR, "output", "Maze peice connector.stl"),
        "current rounded connector",
        spec,
        source_cutters,
    )
    print(
        "SOURCE OK sha256=%s wall_objects=%s bounds=%s/%s"
        % (
            receipts["source_3dm"],
            ",".join(str(record["index"]) for record in walls),
            _format_bounds(walls[0]["bounds"]),
            _format_bounds(walls[1]["bounds"]),
        )
    )
    print(
        "INTERFACE OK pockets=%s cutter_span=%.6f depth=%.1f bridges_clearance=%.3f/%.3f"
        % (
            pocket_layout_receipt(RAMP_PLATFORM),
            profile["full_span"],
            profile["depth"],
            tracked_fit["minimum_planar_clearance"],
            current_fit["minimum_planar_clearance"],
        )
    )
    print(
        "RAMP OK angle=%.1f rise=%.1f run=%.13f slope=%.1f toe=%.13f x=%.1f..%.1f high_z=%.1f underlap=%.2f"
        % (
            ANGLE_DEGREES,
            RAMP_RISE,
            RAMP_RUN,
            RAMP_SLOPE_LENGTH,
            RAMP_TOE_Y,
            RAMP_X_MIN,
            RAMP_X_MAX,
            HIGH_SURFACE_Z,
            RAMP_UNDERLAP,
        )
    )
    check_generated_outputs(output_dir, require_outputs=require_outputs)


def _create_ramp_wedge():
    profile_points = (
        Rhino.Geometry.Point3d(RAMP_X_MIN, RAMP_TOE_Y, BASE_TOP_Z - RAMP_UNDERLAP),
        Rhino.Geometry.Point3d(RAMP_X_MIN, 200.0, BASE_TOP_Z - RAMP_UNDERLAP),
        Rhino.Geometry.Point3d(RAMP_X_MIN, 200.0, HIGH_SURFACE_Z),
        Rhino.Geometry.Point3d(RAMP_X_MIN, RAMP_TOE_Y, BASE_TOP_Z),
        Rhino.Geometry.Point3d(RAMP_X_MIN, RAMP_TOE_Y, BASE_TOP_Z - RAMP_UNDERLAP),
    )
    profile = Rhino.Geometry.Polyline(profile_points).ToNurbsCurve()
    if not profile.IsClosed or not profile.IsPlanar(MODEL_TOLERANCE):
        raise RuntimeError("Ramp YZ profile is not a closed planar curve")
    surface = Rhino.Geometry.Surface.CreateExtrusion(
        profile,
        Rhino.Geometry.Vector3d(RAMP_WIDTH, 0.0, 0.0),
    )
    if surface is None:
        raise RuntimeError("Could not extrude the exact ramp profile")
    wedge = surface.ToBrep().CapPlanarHoles(MODEL_TOLERANCE)
    # Surface.CreateExtrusion keeps the closed polyline as one kinked lateral
    # face. Split those kinks so the 30-degree slope and the north vertical face
    # mesh as separate exact planes instead of a tessellated diagonal shortcut.
    wedge.Faces.SplitKinkyFaces(math.radians(0.25), True)
    wedge = _validate_brep(wedge, "exact 30-degree ramp wedge")
    expected_bounds = (
        RAMP_X_MIN,
        RAMP_TOE_Y,
        BASE_TOP_Z - RAMP_UNDERLAP,
        RAMP_X_MAX,
        200.0,
        HIGH_SURFACE_Z,
    )
    actual_bounds = _bounds_tuple(wedge.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "ramp wedge bound %d" % index)
    return wedge


def _validate_final_brep(piece):
    piece = _validate_brep(piece, OBJECT_NAME)
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 200.0, HIGH_SURFACE_Z)
    bounds = _bounds_tuple(piece.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "final ramp bound %d" % index)
    volume = abs(piece.GetVolume())
    if not math.isfinite(volume) or volume <= exposed_ramp_volume():
        raise RuntimeError("Final ramp Brep volume is implausible")
    return piece, bounds, volume


def _validate_final_pocket_voids(piece, spec, source_cutters):
    """Prove the finished solid does not refill any literal source cutter."""

    intersection_volumes = {}
    for side in ("north", "east", "south", "west"):
        centers = RAMP_PLATFORM["pockets"][side]
        if centers != (100.0,):
            raise RuntimeError("Ramp pocket layout changed before cutter-clearance validation")
        cutter = _placed_source_cutter(source_cutters[side], RAMP_PLATFORM, side, 100.0, spec)
        intersections = Rhino.Geometry.Brep.CreateBooleanIntersection(
            piece,
            cutter,
            MODEL_TOLERANCE,
        )
        volume = 0.0
        if intersections:
            for intersection in intersections:
                if intersection is None or not intersection.IsValid:
                    raise RuntimeError("%s pocket intersection returned invalid geometry" % side)
                if intersection.IsSolid:
                    volume += abs(intersection.GetVolume())
        if not math.isfinite(volume) or volume > 1.0e-6:
            raise RuntimeError(
                "%s source pocket was refilled by %.9f mm3 in the finished ramp"
                % (side, volume)
            )
        intersection_volumes[side] = volume
    return intersection_volumes


def pocket_void_boolean_receipt(intersection_volumes):
    return ";".join(
        "%s=%.9f" % (side, intersection_volumes[side])
        for side in ("north", "east", "south", "west")
    )


def _validate_brep_ramp_surface(piece):
    expected_bounds = (
        RAMP_X_MIN,
        RAMP_TOE_Y,
        BASE_TOP_Z,
        RAMP_X_MAX,
        200.0,
        HIGH_SURFACE_Z,
    )
    candidates = []
    diagnostics = []
    for index, face in enumerate(piece.Faces):
        bounds = _bounds_tuple(face.GetBoundingBox(True))
        if bounds[3] - bounds[0] > 150.0 and bounds[4] > 190.0 and bounds[5] > 80.0:
            properties = Rhino.Geometry.AreaMassProperties.Compute(face)
            diagnostics.append((index, None if properties is None else float(properties.Area), bounds))
        if all(abs(actual - expected) <= GEOMETRY_TOLERANCE for actual, expected in zip(bounds, expected_bounds)):
            properties = Rhino.Geometry.AreaMassProperties.Compute(face)
            if properties is None:
                raise RuntimeError("Could not measure exact ramp Brep face")
            candidates.append((index, float(properties.Area), bounds))
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected one exact ramp Brep face, found %d: %s; nearby faces: %s"
            % (len(candidates), candidates, diagnostics)
        )
    expected_area = RAMP_WIDTH * RAMP_SLOPE_LENGTH
    _assert_close(candidates[0][1], expected_area, 1.0e-5, "exact Brep ramp surface area")
    return {"face_index": candidates[0][0], "area": candidates[0][1]}


def build_ramp_piece():
    receipts = verify_source_receipts()
    spec = load_reviewed_spec()
    _source_cutter_model, source_cutters = load_source_cutters_rhino()
    pocket_profile(spec, source_cutters)
    _wall_model, source_walls = load_source_walls_rhino()
    base = _build_platform(RAMP_PLATFORM, spec, source_cutters)
    wedge = _create_ramp_wedge()
    base_with_ramp = _union(
        [base, wedge],
        "ramp base plus exact wedge",
        MODEL_TOLERANCE,
    )
    piece = _union(
        [base_with_ramp, source_walls["west"], source_walls["east"]],
        "ramp final fusion with literal source walls",
        MODEL_TOLERANCE,
    )
    piece, bounds, volume = _validate_final_brep(piece)
    pocket_void_proof = _validate_final_pocket_voids(piece, spec, source_cutters)
    if pocket_void_boolean_receipt(pocket_void_proof) != EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT:
        raise RuntimeError("Final pocket-void Boolean receipt is not exact zero")
    return piece, spec, receipts, bounds, volume, pocket_void_proof


def _mesh_stl_triangles(brep):
    parameters = Rhino.Geometry.MeshingParameters()
    parameters.JaggedSeams = False
    parameters.SimplePlanes = True
    parameters.RefineGrid = True
    parameters.Tolerance = STL_MESH_TOLERANCE
    parameters.RelativeTolerance = 0.0
    parameters.MinimumEdgeLength = STL_MESH_MINIMUM_EDGE
    parameters.MaximumEdgeLength = STL_MESH_MAXIMUM_EDGE
    meshes = Rhino.Geometry.Mesh.CreateFromBrep(brep, parameters)
    if meshes is None or len(meshes) == 0:
        raise RuntimeError("Could not mesh %s" % OBJECT_NAME)
    triangles = []
    for mesh in meshes:
        if mesh is None or not mesh.IsValid:
            raise RuntimeError("Rhino returned an invalid face mesh for the ramp")
        mesh.Faces.ConvertQuadsToTriangles()
        mesh.Normals.ComputeNormals()
        mesh.Compact()
        for face in mesh.Faces:
            if not face.IsTriangle:
                raise RuntimeError("A non-triangle face remained in the ramp mesh")
            triangles.append((mesh.Vertices[face.A], mesh.Vertices[face.B], mesh.Vertices[face.C]))
    if not triangles:
        raise RuntimeError("Ramp mesh contains no triangles")
    return triangles


def _set_receipts(
    attributes,
    source_receipts,
    bounds,
    brep_volume,
    stl_volume,
    relative_error,
    pocket_void_proof,
):
    attributes.SetUserString("dimensions_mm", "200.0 x 200.0 x 84.0")
    for key, value in ramp_contract_receipt().items():
        attributes.SetUserString(key, value)
    attributes.SetUserString("ramp_method", RAMP_METHOD)
    attributes.SetUserString("pocket_centers_mm", pocket_layout_receipt(RAMP_PLATFORM))
    attributes.SetUserString("source_3dm_sha256", source_receipts["source_3dm"])
    attributes.SetUserString("source_params_sha256", source_receipts["params"])
    attributes.SetUserString("source_bridge_sha256", source_receipts["source_bridge"])
    attributes.SetUserString("current_connector_sha256", source_receipts["current_connector"])
    attributes.SetUserString("source_wall_objects", "13,14")
    attributes.SetUserString(
        "source_wall_bounds_mm",
        "west=0,0,10,19.2,200,82;east=180.8,0,10,200,200,82",
    )
    attributes.SetUserString("stl_mesh_receipt", STL_MESH_RECEIPT)
    attributes.SetUserString(
        "pocket_void_boolean_receipt",
        pocket_void_boolean_receipt(pocket_void_proof),
    )
    attributes.SetUserString("brep_volume_mm3", "%.9f" % brep_volume)
    attributes.SetUserString("stl_signed_volume_mm3", "%.9f" % stl_volume)
    attributes.SetUserString("mesh_volume_relative_error", "%.12f" % relative_error)
    attributes.SetUserString("verified_trimmed_bounds_mm", ",".join("%.9f" % value for value in bounds))


def _validate_saved_3dm(path):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None or model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Could not reopen millimeter ramp 3dm")
    model_objects = list(model.Objects)
    if len(model_objects) != 1:
        raise RuntimeError("Reopened ramp 3dm must contain exactly one object")
    model_object = model_objects[0]
    if model_object.Attributes.Name != OBJECT_NAME:
        raise RuntimeError("Reopened ramp object name is wrong")
    geometry = _validate_brep(model_object.Geometry, "reopened ramp 3dm object")
    actual_bounds = _bounds_tuple(geometry.GetBoundingBox(True))
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 200.0, HIGH_SURFACE_Z)
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "reopened ramp bound %d" % index)
    object_receipts = {
        key: model_object.Attributes.GetUserString(key)
        for key in (
            tuple(ramp_contract_receipt().keys())
            + (
                "ramp_method",
                "pocket_centers_mm",
                "source_3dm_sha256",
                "source_params_sha256",
                "source_bridge_sha256",
                "current_connector_sha256",
                "source_wall_objects",
                "source_wall_bounds_mm",
                "stl_mesh_receipt",
                "pocket_void_boolean_receipt",
                "brep_volume_mm3",
                "stl_signed_volume_mm3",
            )
        )
    }
    validate_ramp_receipts(object_receipts)
    print("REOPENED %s: one closed solid with accurate trimmed bounds" % os.path.basename(path))


def _save_3dm(
    piece,
    path,
    source_receipts,
    bounds,
    brep_volume,
    stl_volume,
    relative_error,
    pocket_void_proof,
):
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is None:
        raise RuntimeError("Could not create headless ramp output document")
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    doc.ModelAbsoluteTolerance = MODEL_TOLERANCE
    doc.ModelAngleToleranceRadians = math.radians(0.25)
    layer = Rhino.DocObjects.Layer()
    layer.Name = "X1C30DegreeRamp"
    layer.Color = _color(206, 126, 47)
    layer_index = doc.Layers.Add(layer)
    object_id = doc.Objects.AddBrep(piece)
    rhino_object = doc.Objects.FindId(object_id)
    if rhino_object is None:
        raise RuntimeError("Could not add ramp Brep to output document")
    attributes = rhino_object.Attributes
    attributes.Name = OBJECT_NAME
    attributes.LayerIndex = layer_index
    attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
    _set_receipts(
        attributes,
        source_receipts,
        bounds,
        brep_volume,
        stl_volume,
        relative_error,
        pocket_void_proof,
    )
    if not doc.Objects.ModifyAttributes(object_id, attributes, True):
        raise RuntimeError("Could not store ramp object receipts")

    doc.Strings.SetString("generator", "scripts/generate_30deg_ramp.py")
    document_attributes = Rhino.DocObjects.ObjectAttributes()
    _set_receipts(
        document_attributes,
        source_receipts,
        bounds,
        brep_volume,
        stl_volume,
        relative_error,
        pocket_void_proof,
    )
    for key in document_attributes.GetUserStrings().AllKeys:
        doc.Strings.SetString(key, document_attributes.GetUserString(key))
    options = Rhino.FileIO.FileWriteOptions()
    options.SuppressDialogBoxes = True
    options.WriteSelectedObjectsOnly = False
    options.WriteGeometryOnly = False
    if not doc.WriteFile(path, options):
        raise RuntimeError("Could not write ramp 3dm: %s" % path)
    doc.Dispose()
    _validate_saved_3dm(path)


def generate(output_dir=OUTPUT_DIR):
    if Rhino is None or System is None:
        raise RuntimeError("CAD generation must be run through Rhino 8")
    validate_static_contract()
    piece, spec, source_receipts, bounds, brep_volume, pocket_void_proof = build_ramp_piece()
    brep_slope = _validate_brep_ramp_surface(piece)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    triangles = _mesh_stl_triangles(piece)
    numeric = [
        tuple((float(vertex.X), float(vertex.Y), float(vertex.Z)) for vertex in triangle)
        for triangle in triangles
    ]
    topology = _audit_triangle_topology(numeric, OBJECT_NAME)
    if len(triangles) > STL_TRIANGLE_LIMIT:
        raise RuntimeError("Ramp meshing produced %d triangles, exceeding %d" % (len(triangles), STL_TRIANGLE_LIMIT))
    relative_error = abs(topology["signed_volume"] - brep_volume) / brep_volume
    if relative_error > STL_VOLUME_RELATIVE_TOLERANCE:
        raise RuntimeError("Ramp mesh volume differs from exact Brep by %.8f relative" % relative_error)
    validate_ramp_surface_triangles(numeric)
    stl_path = os.path.join(output_dir, STL_FILENAME)
    _write_binary_stl(stl_path, OBJECT_NAME, triangles)
    _validate_stl_pocket_receipt(stl_path, RAMP_PLATFORM, spec)
    model_path = os.path.join(output_dir, THREEDM_FILENAME)
    _save_3dm(
        piece,
        model_path,
        source_receipts,
        bounds,
        brep_volume,
        topology["signed_volume"],
        relative_error,
        pocket_void_proof,
    )
    print(
        "WROTE %s triangles=%d volume=%.3f mm3 volume_error=%.8f brep_slope_area=%.3f "
        "pocket_intersection=0 bounds=%s"
        % (
            os.path.relpath(stl_path, ROOT_DIR),
            len(triangles),
            topology["signed_volume"],
            relative_error,
            brep_slope["area"],
            _format_bounds(bounds),
        )
    )
    print("WROTE %s" % os.path.relpath(model_path, ROOT_DIR))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the standalone 30-degree X1C maze ramp")
    parser.add_argument("--check", action="store_true", help="verify source receipts and outputs without Rhino")
    parser.add_argument("--require-outputs", action="store_true", help="make --check fail if outputs are missing")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="ramp output folder")
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
        transcript_path = "/tmp/gridmaze_30deg_ramp_generation.log"
        with open(transcript_path, "w") as transcript:
            try:
                with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
                    main()
                transcript.write("GENERATION OK\n")
            except Exception:
                traceback.print_exc(file=transcript)
                raise
