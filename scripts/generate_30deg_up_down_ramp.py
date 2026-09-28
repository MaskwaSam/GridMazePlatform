#!/usr/bin/env python3
r"""Generate the symmetric 30-degree H2D up-and-down challenge ramp.

Rhino 8 generation::

    /Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
        /absolute/path/to/scripts/generate_30deg_up_down_ramp.py

External source/artifact validation::

    python3 scripts/generate_30deg_up_down_ramp.py --check --require-outputs
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
    CURRENT_CONNECTOR_PATH,
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    PLATFORMS,
    SOURCE_BRIDGE_PATH,
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
    EXTENSION_METHOD,
    SECTION_STATIONS,
    extend_wall_central_section,
    inspect_source_walls_external,
    load_source_walls_rhino,
    uniformity_receipt,
    verify_uniform_central_section,
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


OUTPUT_DIR = os.path.join(ROOT_DIR, "output", "challenge-ramp")
OUTPUT_STEM = "maze_piece_h2d_200x300_30deg_up_down_ramp_v1"
STL_FILENAME = OUTPUT_STEM + ".stl"
THREEDM_FILENAME = OUTPUT_STEM + ".3dm"
OUTPUT_STL = os.path.join(OUTPUT_DIR, STL_FILENAME)
OUTPUT_3DM = os.path.join(OUTPUT_DIR, THREEDM_FILENAME)
OBJECT_NAME = OUTPUT_STEM

MODEL_TOLERANCE = 0.01
GEOMETRY_TOLERANCE = 0.002
ANGLE_DEGREES = 30.0
BASE_TOP_Z = 10.0
WALL_TOP_Z = 82.0
RIDGE_Z = 84.0
RIDGE_Y = 150.0
RAMP_RISE = 74.0
RAMP_RUN = 128.1717597600969
RAMP_SLOPE_LENGTH = 148.0
SOUTH_TOE_Y = 21.8282402399031
NORTH_TOE_Y = 278.1717597600969
FLAT_APPROACH_LENGTH = 21.8282402399031
RAMP_X_MIN = 19.2
RAMP_X_MAX = 180.8
RAMP_WIDTH = 161.6
RAMP_UNDERLAP = 0.05
MAX_ALLOWED_UNDERLAP = 0.05
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

CHALLENGE_PLATFORM = {
    "key": "h2d_200x300_30deg_up_down_ramp",
    "label": "H2D 200 x 300 30 Degree Up and Down Challenge Ramp",
    "width": 200.0,
    "height": 300.0,
    "filename": STL_FILENAME,
    "position": (0.0, 0.0),
    "pockets": {
        "north": (100.0,),
        "east": (150.0,),
        "south": (100.0,),
        "west": (150.0,),
    },
}

SOURCE_WALL_BOUNDS = {
    "west": (0.0, 0.0, 10.0, 19.2, 200.0, 82.0),
    "east": (180.8, 0.0, 10.0, 200.0, 200.0, 82.0),
}
EXTENDED_WALL_BOUNDS = {
    "west": (0.0, 0.0, 10.0, 19.2, 300.0, 82.0),
    "east": (180.8, 0.0, 10.0, 200.0, 300.0, 82.0),
}
SOURCE_WALL_OBJECTS = (13, 14)
RAMP_METHOD = (
    "exact reviewed H2D 200x300 pocketed base; literal source wall Breps 13/14 extended by the "
    "reviewed uniform central-section insertion; symmetric closed YZ ramp profile extruded "
    "161.6 mm in X and split at every sharp profile kink; 0.05 mm hidden top-skin underlap; no scaling"
)
EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT = (
    "north=0.000000000;east=0.000000000;south=0.000000000;west=0.000000000"
)


def south_surface_z(y):
    return BASE_TOP_Z + math.tan(math.radians(ANGLE_DEGREES)) * (float(y) - SOUTH_TOE_Y)


def north_surface_z(y):
    return BASE_TOP_Z + math.tan(math.radians(ANGLE_DEGREES)) * (NORTH_TOE_Y - float(y))


def exposed_ramp_volume():
    return 2.0 * RAMP_WIDTH * RAMP_RUN * RAMP_RISE / 2.0


def ramp_contract_receipt():
    return {
        "south_angle_degrees": "%.9f" % ANGLE_DEGREES,
        "north_angle_degrees": "%.9f" % ANGLE_DEGREES,
        "rise_each_mm": "%.9f" % RAMP_RISE,
        "horizontal_run_each_mm": "%.13f" % RAMP_RUN,
        "slope_length_each_mm": "%.9f" % RAMP_SLOPE_LENGTH,
        "south_toe_y_mm": "%.13f" % SOUTH_TOE_Y,
        "north_toe_y_mm": "%.13f" % NORTH_TOE_Y,
        "flat_approaches_mm": "south=%.13f;north=%.13f"
        % (FLAT_APPROACH_LENGTH, FLAT_APPROACH_LENGTH),
        "ridge_line_mm": "x=19.2..180.8;y=150;z=84",
        "south_toe_line_mm": "x=19.2..180.8;y=%.13f;z=10" % SOUTH_TOE_Y,
        "north_toe_line_mm": "x=19.2..180.8;y=%.13f;z=10" % NORTH_TOE_Y,
        "ramp_width_mm": "%.9f" % RAMP_WIDTH,
        "ramp_x_extent_mm": "19.2..180.8",
        "base_underlap_mm": "%.9f" % RAMP_UNDERLAP,
        "pocket_void_z_mm": "0.000000000..8.000000000",
        "ramp_underlap_z_mm": "9.950000000..10.000000000",
        "pocket_void_vertical_clearance_mm": "%.9f" % POCKET_VOID_VERTICAL_CLEARANCE,
    }


def validate_static_contract():
    _assert_close(RAMP_RUN, RAMP_RISE / math.tan(math.radians(ANGLE_DEGREES)), 1.0e-12, "ramp run")
    _assert_close(SOUTH_TOE_Y, RIDGE_Y - RAMP_RUN, 1.0e-12, "south toe")
    _assert_close(NORTH_TOE_Y, RIDGE_Y + RAMP_RUN, 1.0e-12, "north toe")
    _assert_close(FLAT_APPROACH_LENGTH, SOUTH_TOE_Y, 1.0e-12, "south flat approach")
    _assert_close(FLAT_APPROACH_LENGTH, 300.0 - NORTH_TOE_Y, 1.0e-12, "north flat approach")
    _assert_close(RAMP_SLOPE_LENGTH, math.hypot(RAMP_RUN, RAMP_RISE), 1.0e-12, "slope length")
    _assert_close(south_surface_z(SOUTH_TOE_Y), BASE_TOP_Z, 1.0e-12, "south toe height")
    _assert_close(south_surface_z(RIDGE_Y), RIDGE_Z, 1.0e-12, "south ridge height")
    _assert_close(north_surface_z(RIDGE_Y), RIDGE_Z, 1.0e-12, "north ridge height")
    _assert_close(north_surface_z(NORTH_TOE_Y), BASE_TOP_Z, 1.0e-12, "north toe height")
    _assert_close(math.degrees(math.atan2(RAMP_RISE, RAMP_RUN)), ANGLE_DEGREES, 1.0e-12, "ramp angle")
    _assert_close(RAMP_X_MAX - RAMP_X_MIN, RAMP_WIDTH, 1.0e-12, "ramp width")
    _assert_close(
        BASE_TOP_Z - RAMP_UNDERLAP - POCKET_VOID_TOP_Z,
        POCKET_VOID_VERTICAL_CLEARANCE,
        1.0e-12,
        "ramp-to-pocket vertical clearance",
    )
    if not (0.0 < RAMP_UNDERLAP <= MAX_ALLOWED_UNDERLAP):
        raise ValueError("Ramp underlap must be positive and no more than 0.05 mm")
    if CHALLENGE_PLATFORM != dict(PLATFORMS[0], key=CHALLENGE_PLATFORM["key"], label=CHALLENGE_PLATFORM["label"], filename=STL_FILENAME, position=(0.0, 0.0)):
        raise ValueError("Challenge platform diverged from the reviewed H2D 200 x 300 layout")
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


def _slope_proof(triangles, side):
    plane_tolerance = 0.003
    if side == "south":
        minimum_y, maximum_y = SOUTH_TOE_Y, RIDGE_Y
        plane = south_surface_z
        required = (
            (RAMP_X_MIN, SOUTH_TOE_Y, BASE_TOP_Z),
            (RAMP_X_MAX, SOUTH_TOE_Y, BASE_TOP_Z),
            (RAMP_X_MIN, RIDGE_Y, RIDGE_Z),
            (RAMP_X_MAX, RIDGE_Y, RIDGE_Z),
        )
    elif side == "north":
        minimum_y, maximum_y = RIDGE_Y, NORTH_TOE_Y
        plane = north_surface_z
        required = (
            (RAMP_X_MIN, RIDGE_Y, RIDGE_Z),
            (RAMP_X_MAX, RIDGE_Y, RIDGE_Z),
            (RAMP_X_MIN, NORTH_TOE_Y, BASE_TOP_Z),
            (RAMP_X_MAX, NORTH_TOE_Y, BASE_TOP_Z),
        )
    else:
        raise ValueError("Unknown slope side: %s" % side)
    selected = []
    for triangle in triangles:
        if all(
            RAMP_X_MIN - plane_tolerance <= vertex[0] <= RAMP_X_MAX + plane_tolerance
            and minimum_y - plane_tolerance <= vertex[1] <= maximum_y + plane_tolerance
            and abs(vertex[2] - plane(vertex[1])) <= plane_tolerance
            for vertex in triangle
        ):
            selected.append(triangle)
    if not selected:
        raise ValueError("STL contains no triangles on the exact %s ramp surface" % side)
    area = sum(_triangle_area(triangle) for triangle in selected)
    _assert_close(area, RAMP_WIDTH * RAMP_SLOPE_LENGTH, 0.002, "%s serialized slope area" % side)
    vertices = [vertex for triangle in selected for vertex in triangle]
    for expected in required:
        if not any(_vertex_matches(vertex, expected) for vertex in vertices):
            raise ValueError("%s STL slope is missing endpoint %s" % (side, expected))
    return {"triangle_count": len(selected), "area": area}


def validate_ramp_surface_triangles(triangles):
    south = _slope_proof(triangles, "south")
    north = _slope_proof(triangles, "north")
    total_area = south["area"] + north["area"]
    _assert_close(total_area, 2.0 * RAMP_WIDTH * RAMP_SLOPE_LENGTH, 0.004, "total serialized slope area")
    return {"south": south, "north": north, "total_area": total_area}


def _parse_float(receipts, key):
    try:
        return float(receipts[key])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Challenge-ramp receipt %s is missing or invalid" % key)


def validate_ramp_receipts(receipts):
    for key, expected in ramp_contract_receipt().items():
        if receipts.get(key) != expected:
            raise ValueError("Challenge-ramp receipt %s is wrong" % key)
    expected_values = {
        "ramp_method": RAMP_METHOD,
        "wall_extension_method": EXTENSION_METHOD,
        "pocket_centers_mm": pocket_layout_receipt(CHALLENGE_PLATFORM),
        "source_3dm_sha256": EXPECTED_SOURCE_SHA256,
        "source_params_sha256": EXPECTED_PARAMS_SHA256,
        "source_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "current_connector_sha256": EXPECTED_CURRENT_CONNECTOR_SHA256,
        "source_wall_objects": "13,14",
        "source_wall_bounds_mm": "west=0,0,10,19.2,200,82;east=180.8,0,10,200,200,82",
        "extended_wall_bounds_mm": "west=0,0,10,19.2,300,82;east=180.8,0,10,200,300,82",
        "stl_mesh_receipt": STL_MESH_RECEIPT,
        "pocket_void_boolean_receipt": EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
    }
    for key, expected in expected_values.items():
        if receipts.get(key) != expected:
            raise ValueError("Challenge-ramp receipt %s is wrong" % key)
    uniformity = receipts.get("wall_uniformity_receipt") or ""
    if uniformity.count("stations=50,100,150") != 2 or uniformity.count("max_deviation=") != 2:
        raise ValueError("Challenge-ramp wall-uniformity receipt is incomplete")
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
            raise ValueError("Challenge-ramp output set is incomplete; missing: %s" % ", ".join(sorted(missing)))
        print("OUTPUTS not generated yet; run this script through Rhino 8")
        return None
    if unexpected:
        raise ValueError("Challenge-ramp output folder has unexpected files: %s" % ", ".join(sorted(unexpected)))

    spec = load_reviewed_spec()
    stl_path = os.path.join(output_dir, STL_FILENAME)
    triangle_count, bounds = _read_binary_stl(stl_path)
    if triangle_count > STL_TRIANGLE_LIMIT:
        raise ValueError("Challenge-ramp STL has avoidable mesh density: %d triangles" % triangle_count)
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 300.0, RIDGE_Z)
    for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "challenge-ramp STL bound %d" % index)
    _validate_stl_pocket_receipt(stl_path, CHALLENGE_PLATFORM, spec)
    triangles = _read_stl_triangles(stl_path)
    topology = _audit_triangle_topology(triangles, STL_FILENAME)
    slopes = validate_ramp_surface_triangles(triangles)

    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("Checking the challenge-ramp 3dm requires rhino3dm") from exc
    model_path = os.path.join(output_dir, THREEDM_FILENAME)
    model = rhino3dm.File3dm.Read(model_path)
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Challenge-ramp 3dm is unreadable or not in millimeters")
    model_objects = list(model.Objects)
    if len(model_objects) != 1:
        raise ValueError("Challenge-ramp 3dm must contain exactly one object")
    model_object = model_objects[0]
    if model_object.Attributes.Name != OBJECT_NAME:
        raise ValueError("Challenge-ramp 3dm object name is wrong")
    if not bool(getattr(model_object.Geometry, "IsSolid", False)):
        raise ValueError("Challenge-ramp 3dm object is not a closed solid")
    receipt_keys = tuple(ramp_contract_receipt().keys()) + (
        "ramp_method",
        "wall_extension_method",
        "pocket_centers_mm",
        "source_3dm_sha256",
        "source_params_sha256",
        "source_bridge_sha256",
        "current_connector_sha256",
        "source_wall_objects",
        "source_wall_bounds_mm",
        "extended_wall_bounds_mm",
        "wall_uniformity_receipt",
        "stl_mesh_receipt",
        "pocket_void_boolean_receipt",
        "brep_volume_mm3",
        "stl_signed_volume_mm3",
        "mesh_volume_relative_error",
        "verified_trimmed_bounds_mm",
    )
    object_receipts = {key: model_object.Attributes.GetUserString(key) for key in receipt_keys}
    volume_receipts = validate_ramp_receipts(object_receipts)
    recorded_bounds = tuple(float(value) for value in object_receipts["verified_trimmed_bounds_mm"].split(","))
    if len(recorded_bounds) != 6:
        raise ValueError("Challenge-ramp 3dm bounds receipt is incomplete")
    for index, (actual, expected) in enumerate(zip(recorded_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "challenge-ramp 3dm recorded bound %d" % index)
    relative_volume_error = abs(topology["signed_volume"] - volume_receipts["brep_volume"]) / volume_receipts["brep_volume"]
    if relative_volume_error > STL_VOLUME_RELATIVE_TOLERANCE:
        raise ValueError("Serialized challenge-ramp STL volume differs from Brep by %.8f" % relative_volume_error)
    _assert_close(topology["signed_volume"], volume_receipts["stl_volume"], 0.10, "STL signed-volume receipt")
    _assert_close(
        _parse_float(object_receipts, "mesh_volume_relative_error"),
        relative_volume_error,
        1.0e-8,
        "mesh-volume error receipt",
    )
    document_receipts = dict(model.Strings)
    if document_receipts.get("generator") != "scripts/generate_30deg_up_down_ramp.py":
        raise ValueError("Challenge-ramp 3dm generator receipt is wrong")
    validate_ramp_receipts(document_receipts)
    print(
        "OUTPUT OK %s triangles=%d shells=%d volume=%.3f south_area=%.3f north_area=%.3f "
        "bounds=%s"
        % (
            STL_FILENAME,
            triangle_count,
            topology["component_count"],
            topology["signed_volume"],
            slopes["south"]["area"],
            slopes["north"]["area"],
            _format_bounds(bounds),
        )
    )
    print("OUTPUT OK %s objects=1 closed_solid=1" % THREEDM_FILENAME)
    return {
        "triangle_count": triangle_count,
        "bounds": bounds,
        "topology": topology,
        "slopes": slopes,
        "relative_volume_error": relative_volume_error,
    }


def check_only(output_dir=OUTPUT_DIR, require_outputs=False):
    validate_static_contract()
    receipts = verify_source_receipts()
    source_cutters = load_source_cutters_external()
    spec = load_reviewed_spec()
    profile = pocket_profile(spec, source_cutters)
    walls = validate_source_wall_receipts()
    tracked_fit = validate_connector_fit(SOURCE_BRIDGE_PATH, "tracked standard bridge", spec, source_cutters)
    current_fit = validate_connector_fit(CURRENT_CONNECTOR_PATH, "current rounded connector", spec, source_cutters)
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
            pocket_layout_receipt(CHALLENGE_PLATFORM),
            profile["full_span"],
            profile["depth"],
            tracked_fit["minimum_planar_clearance"],
            current_fit["minimum_planar_clearance"],
        )
    )
    print(
        "RAMP OK symmetric=1 angle=%.1f rise=%.1f run=%.13f slope=%.1f toes=%.13f/%.13f "
        "ridge=(Y%.1f,Z%.1f) approaches=%.13f x=%.1f..%.1f underlap=%.2f"
        % (
            ANGLE_DEGREES,
            RAMP_RISE,
            RAMP_RUN,
            RAMP_SLOPE_LENGTH,
            SOUTH_TOE_Y,
            NORTH_TOE_Y,
            RIDGE_Y,
            RIDGE_Z,
            FLAT_APPROACH_LENGTH,
            RAMP_X_MIN,
            RAMP_X_MAX,
            RAMP_UNDERLAP,
        )
    )
    print("WALL METHOD %s" % EXTENSION_METHOD)
    check_generated_outputs(output_dir, require_outputs=require_outputs)


def _create_ramp_wedge():
    profile_points = (
        Rhino.Geometry.Point3d(RAMP_X_MIN, SOUTH_TOE_Y, BASE_TOP_Z - RAMP_UNDERLAP),
        Rhino.Geometry.Point3d(RAMP_X_MIN, NORTH_TOE_Y, BASE_TOP_Z - RAMP_UNDERLAP),
        Rhino.Geometry.Point3d(RAMP_X_MIN, NORTH_TOE_Y, BASE_TOP_Z),
        Rhino.Geometry.Point3d(RAMP_X_MIN, RIDGE_Y, RIDGE_Z),
        Rhino.Geometry.Point3d(RAMP_X_MIN, SOUTH_TOE_Y, BASE_TOP_Z),
        Rhino.Geometry.Point3d(RAMP_X_MIN, SOUTH_TOE_Y, BASE_TOP_Z - RAMP_UNDERLAP),
    )
    profile = Rhino.Geometry.Polyline(profile_points).ToNurbsCurve()
    if not profile.IsClosed or not profile.IsPlanar(MODEL_TOLERANCE):
        raise RuntimeError("Challenge-ramp YZ profile is not a closed planar curve")
    surface = Rhino.Geometry.Surface.CreateExtrusion(
        profile,
        Rhino.Geometry.Vector3d(RAMP_WIDTH, 0.0, 0.0),
    )
    if surface is None:
        raise RuntimeError("Could not extrude the exact challenge-ramp profile")
    wedge = surface.ToBrep().CapPlanarHoles(MODEL_TOLERANCE)
    wedge.Faces.SplitKinkyFaces(math.radians(0.25), True)
    wedge = _validate_brep(wedge, "exact symmetric 30-degree ramp wedge")
    expected_bounds = (
        RAMP_X_MIN,
        SOUTH_TOE_Y,
        BASE_TOP_Z - RAMP_UNDERLAP,
        RAMP_X_MAX,
        NORTH_TOE_Y,
        RIDGE_Z,
    )
    actual_bounds = _bounds_tuple(wedge.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "challenge-ramp wedge bound %d" % index)
    return wedge


def _validate_final_brep(piece):
    piece = _validate_brep(piece, OBJECT_NAME)
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 300.0, RIDGE_Z)
    bounds = _bounds_tuple(piece.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "final challenge-ramp bound %d" % index)
    volume = abs(piece.GetVolume())
    if not math.isfinite(volume) or volume <= exposed_ramp_volume():
        raise RuntimeError("Final challenge-ramp Brep volume is implausible")
    return piece, bounds, volume


def _validate_final_pocket_voids(piece, spec, source_cutters):
    intersection_volumes = {}
    for side in ("north", "east", "south", "west"):
        centers = CHALLENGE_PLATFORM["pockets"][side]
        if len(centers) != 1:
            raise RuntimeError("Challenge-ramp pocket layout changed before void proof")
        cutter = _placed_source_cutter(source_cutters[side], CHALLENGE_PLATFORM, side, centers[0], spec)
        intersections = Rhino.Geometry.Brep.CreateBooleanIntersection(piece, cutter, MODEL_TOLERANCE)
        volume = 0.0
        if intersections:
            for intersection in intersections:
                if intersection is None or not intersection.IsValid:
                    raise RuntimeError("%s pocket intersection returned invalid geometry" % side)
                if intersection.IsSolid:
                    volume += abs(intersection.GetVolume())
        if not math.isfinite(volume) or volume > 1.0e-6:
            raise RuntimeError("%s source pocket was refilled by %.9f mm3" % (side, volume))
        intersection_volumes[side] = volume
    return intersection_volumes


def pocket_void_boolean_receipt(intersection_volumes):
    return ";".join(
        "%s=%.9f" % (side, intersection_volumes[side])
        for side in ("north", "east", "south", "west")
    )


def _validate_brep_slope_surfaces(piece):
    expected = {
        "south": (RAMP_X_MIN, SOUTH_TOE_Y, BASE_TOP_Z, RAMP_X_MAX, RIDGE_Y, RIDGE_Z),
        "north": (RAMP_X_MIN, RIDGE_Y, BASE_TOP_Z, RAMP_X_MAX, NORTH_TOE_Y, RIDGE_Z),
    }
    proofs = {}
    for label, expected_bounds in expected.items():
        candidates = []
        for index, face in enumerate(piece.Faces):
            bounds = _bounds_tuple(face.GetBoundingBox(True))
            if all(abs(actual - target) <= GEOMETRY_TOLERANCE for actual, target in zip(bounds, expected_bounds)):
                properties = Rhino.Geometry.AreaMassProperties.Compute(face)
                if properties is None:
                    raise RuntimeError("Could not measure exact %s slope Brep face" % label)
                candidates.append((index, float(properties.Area), bounds))
        if len(candidates) != 1:
            raise RuntimeError("Expected one exact %s slope Brep face, found %d" % (label, len(candidates)))
        _assert_close(
            candidates[0][1],
            RAMP_WIDTH * RAMP_SLOPE_LENGTH,
            1.0e-5,
            "exact %s Brep slope area" % label,
        )
        proofs[label] = {"face_index": candidates[0][0], "area": candidates[0][1]}
    return proofs


def build_challenge_ramp_piece():
    source_receipts = verify_source_receipts()
    spec = load_reviewed_spec()
    _source_cutter_model, source_cutters = load_source_cutters_rhino()
    pocket_profile(spec, source_cutters)
    _source_wall_model, source_walls = load_source_walls_rhino()
    uniformity = {
        "west": verify_uniform_central_section(source_walls["west"], "west"),
        "east": verify_uniform_central_section(source_walls["east"], "east"),
    }
    extended_walls = {
        "west": extend_wall_central_section(source_walls["west"], "west", uniformity["west"]),
        "east": extend_wall_central_section(source_walls["east"], "east", uniformity["east"]),
    }
    for label in ("west", "east"):
        bounds = _bounds_tuple(extended_walls[label].GetBoundingBox(True))
        for index, (actual, expected) in enumerate(zip(bounds, EXTENDED_WALL_BOUNDS[label])):
            _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s extended wall bound %d" % (label, index))
    base = _build_platform(CHALLENGE_PLATFORM, spec, source_cutters)
    wedge = _create_ramp_wedge()
    base_with_walls = _union(
        (base, extended_walls["west"], extended_walls["east"]),
        "challenge-ramp base plus reviewed extended walls",
        MODEL_TOLERANCE,
    )
    piece = _union(
        (base_with_walls, wedge),
        "challenge-ramp final fusion with exact wedge",
        MODEL_TOLERANCE,
    )
    piece, bounds, volume = _validate_final_brep(piece)
    pocket_void_proof = _validate_final_pocket_voids(piece, spec, source_cutters)
    if pocket_void_boolean_receipt(pocket_void_proof) != EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT:
        raise RuntimeError("Final challenge-ramp pocket-void receipt is not exact zero")
    return piece, spec, source_receipts, bounds, volume, pocket_void_proof, uniformity


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
            raise RuntimeError("Rhino returned an invalid challenge-ramp face mesh")
        mesh.Faces.ConvertQuadsToTriangles()
        mesh.Normals.ComputeNormals()
        mesh.Compact()
        for face in mesh.Faces:
            if not face.IsTriangle:
                raise RuntimeError("A non-triangle face remained in the challenge-ramp mesh")
            triangles.append((mesh.Vertices[face.A], mesh.Vertices[face.B], mesh.Vertices[face.C]))
    if not triangles:
        raise RuntimeError("Challenge-ramp mesh contains no triangles")
    return triangles


def wall_uniformity_text(uniformity):
    return uniformity_receipt(uniformity["west"]) + ";" + uniformity_receipt(uniformity["east"])


def _set_receipts(
    attributes,
    source_receipts,
    bounds,
    brep_volume,
    stl_volume,
    relative_error,
    pocket_void_proof,
    uniformity,
):
    attributes.SetUserString("dimensions_mm", "200.0 x 300.0 x 84.0")
    for key, value in ramp_contract_receipt().items():
        attributes.SetUserString(key, value)
    attributes.SetUserString("ramp_method", RAMP_METHOD)
    attributes.SetUserString("wall_extension_method", EXTENSION_METHOD)
    attributes.SetUserString("pocket_centers_mm", pocket_layout_receipt(CHALLENGE_PLATFORM))
    attributes.SetUserString("source_3dm_sha256", source_receipts["source_3dm"])
    attributes.SetUserString("source_params_sha256", source_receipts["params"])
    attributes.SetUserString("source_bridge_sha256", source_receipts["source_bridge"])
    attributes.SetUserString("current_connector_sha256", source_receipts["current_connector"])
    attributes.SetUserString("source_wall_objects", "13,14")
    attributes.SetUserString(
        "source_wall_bounds_mm",
        "west=0,0,10,19.2,200,82;east=180.8,0,10,200,200,82",
    )
    attributes.SetUserString(
        "extended_wall_bounds_mm",
        "west=0,0,10,19.2,300,82;east=180.8,0,10,200,300,82",
    )
    attributes.SetUserString("wall_uniformity_receipt", wall_uniformity_text(uniformity))
    attributes.SetUserString("stl_mesh_receipt", STL_MESH_RECEIPT)
    attributes.SetUserString("pocket_void_boolean_receipt", pocket_void_boolean_receipt(pocket_void_proof))
    attributes.SetUserString("brep_volume_mm3", "%.9f" % brep_volume)
    attributes.SetUserString("stl_signed_volume_mm3", "%.9f" % stl_volume)
    attributes.SetUserString("mesh_volume_relative_error", "%.12f" % relative_error)
    attributes.SetUserString("verified_trimmed_bounds_mm", ",".join("%.9f" % value for value in bounds))


def _validate_saved_3dm(path):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None or model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Could not reopen millimeter challenge-ramp 3dm")
    model_objects = list(model.Objects)
    if len(model_objects) != 1:
        raise RuntimeError("Reopened challenge-ramp 3dm must contain exactly one object")
    model_object = model_objects[0]
    if model_object.Attributes.Name != OBJECT_NAME:
        raise RuntimeError("Reopened challenge-ramp object name is wrong")
    geometry = _validate_brep(model_object.Geometry, "reopened challenge-ramp 3dm object")
    actual_bounds = _bounds_tuple(geometry.GetBoundingBox(True))
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 300.0, RIDGE_Z)
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "reopened challenge-ramp bound %d" % index)
    receipt_keys = tuple(ramp_contract_receipt().keys()) + (
        "ramp_method",
        "wall_extension_method",
        "pocket_centers_mm",
        "source_3dm_sha256",
        "source_params_sha256",
        "source_bridge_sha256",
        "current_connector_sha256",
        "source_wall_objects",
        "source_wall_bounds_mm",
        "extended_wall_bounds_mm",
        "wall_uniformity_receipt",
        "stl_mesh_receipt",
        "pocket_void_boolean_receipt",
        "brep_volume_mm3",
        "stl_signed_volume_mm3",
    )
    validate_ramp_receipts({key: model_object.Attributes.GetUserString(key) for key in receipt_keys})
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
    uniformity,
):
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is None:
        raise RuntimeError("Could not create headless challenge-ramp output document")
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    doc.ModelAbsoluteTolerance = MODEL_TOLERANCE
    doc.ModelAngleToleranceRadians = math.radians(0.25)
    layer = Rhino.DocObjects.Layer()
    layer.Name = "H2D30DegreeUpDownChallengeRamp"
    layer.Color = _color(185, 101, 49)
    layer_index = doc.Layers.Add(layer)
    object_id = doc.Objects.AddBrep(piece)
    rhino_object = doc.Objects.FindId(object_id)
    if rhino_object is None:
        raise RuntimeError("Could not add challenge-ramp Brep to output document")
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
        uniformity,
    )
    if not doc.Objects.ModifyAttributes(object_id, attributes, True):
        raise RuntimeError("Could not store challenge-ramp object receipts")
    doc.Strings.SetString("generator", "scripts/generate_30deg_up_down_ramp.py")
    document_attributes = Rhino.DocObjects.ObjectAttributes()
    _set_receipts(
        document_attributes,
        source_receipts,
        bounds,
        brep_volume,
        stl_volume,
        relative_error,
        pocket_void_proof,
        uniformity,
    )
    for key in document_attributes.GetUserStrings().AllKeys:
        doc.Strings.SetString(key, document_attributes.GetUserString(key))
    options = Rhino.FileIO.FileWriteOptions()
    options.SuppressDialogBoxes = True
    options.WriteSelectedObjectsOnly = False
    options.WriteGeometryOnly = False
    if not doc.WriteFile(path, options):
        raise RuntimeError("Could not write challenge-ramp 3dm: %s" % path)
    doc.Dispose()
    _validate_saved_3dm(path)


def generate(output_dir=OUTPUT_DIR):
    if Rhino is None or System is None:
        raise RuntimeError("CAD generation must be run through Rhino 8")
    validate_static_contract()
    (
        piece,
        spec,
        source_receipts,
        bounds,
        brep_volume,
        pocket_void_proof,
        uniformity,
    ) = build_challenge_ramp_piece()
    brep_slopes = _validate_brep_slope_surfaces(piece)
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    triangles = _mesh_stl_triangles(piece)
    numeric = [
        tuple((float(vertex.X), float(vertex.Y), float(vertex.Z)) for vertex in triangle)
        for triangle in triangles
    ]
    topology = _audit_triangle_topology(numeric, OBJECT_NAME)
    if len(triangles) > STL_TRIANGLE_LIMIT:
        raise RuntimeError(
            "Challenge-ramp meshing produced %d triangles, exceeding %d"
            % (len(triangles), STL_TRIANGLE_LIMIT)
        )
    relative_error = abs(topology["signed_volume"] - brep_volume) / brep_volume
    if relative_error > STL_VOLUME_RELATIVE_TOLERANCE:
        raise RuntimeError("Challenge-ramp mesh volume differs from exact Brep by %.8f relative" % relative_error)
    slope_proof = validate_ramp_surface_triangles(numeric)
    stl_path = os.path.join(output_dir, STL_FILENAME)
    _write_binary_stl(stl_path, OBJECT_NAME, triangles)
    _validate_stl_pocket_receipt(stl_path, CHALLENGE_PLATFORM, spec)
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
        uniformity,
    )
    print(
        "WROTE %s triangles=%d volume=%.3f mm3 volume_error=%.8f south_area=%.3f "
        "north_area=%.3f total_area=%.3f pocket_intersection=0 bounds=%s"
        % (
            os.path.relpath(stl_path, ROOT_DIR),
            len(triangles),
            topology["signed_volume"],
            relative_error,
            brep_slopes["south"]["area"],
            brep_slopes["north"]["area"],
            slope_proof["total_area"],
            _format_bounds(bounds),
        )
    )
    print("WROTE %s" % os.path.relpath(model_path, ROOT_DIR))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the symmetric H2D 30-degree challenge ramp")
    parser.add_argument("--check", action="store_true", help="verify source receipts and outputs without Rhino")
    parser.add_argument("--require-outputs", action="store_true", help="make --check fail if outputs are missing")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="challenge-ramp output folder")
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
        transcript_path = "/tmp/gridmaze_30deg_up_down_ramp_generation.log"
        with open(transcript_path, "w") as transcript:
            try:
                with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
                    main()
                transcript.write("GENERATION OK\n")
            except Exception:
                traceback.print_exc(file=transcript)
                raise
