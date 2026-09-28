#!/usr/bin/env python3
r"""Generate twelve reviewed H2D 200 x 300 challenge-ramp variants.

Rhino 8 generation::

    /Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
        /absolute/path/to/scripts/generate_challenge_ramp_variants.py

External source/artifact validation::

    python3 scripts/generate_challenge_ramp_variants.py --check --require-outputs
"""

from __future__ import print_function

import argparse
import contextlib
import math
import os
import re
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

from generate_30deg_up_down_ramp import (
    ANGLE_DEGREES,
    BASE_TOP_Z,
    CHALLENGE_PLATFORM,
    EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
    GEOMETRY_TOLERANCE,
    MODEL_TOLERANCE,
    NORTH_TOE_Y,
    POCKET_VOID_TOP_Z,
    POCKET_VOID_VERTICAL_CLEARANCE,
    RAMP_RUN,
    RAMP_SLOPE_LENGTH,
    RAMP_UNDERLAP,
    RAMP_WIDTH,
    RAMP_X_MAX,
    RAMP_X_MIN,
    RIDGE_Y,
    RIDGE_Z,
    SOUTH_TOE_Y,
    STL_MESH_MAXIMUM_EDGE,
    STL_MESH_MINIMUM_EDGE,
    STL_MESH_RECEIPT,
    STL_MESH_TOLERANCE,
    STL_TRIANGLE_LIMIT,
    STL_VOLUME_RELATIVE_TOLERANCE,
    WALL_TOP_Z,
    _parse_float,
    _read_stl_triangles,
    _triangle_area,
    _validate_final_pocket_voids,
    pocket_void_boolean_receipt,
    validate_source_wall_receipts,
    wall_uniformity_text,
)
from generate_h2d_compatible_platforms import (
    CURRENT_CONNECTOR_PATH,
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    SOURCE_BRIDGE_PATH,
    _build_platform,
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
    extend_wall_central_section,
    load_source_walls_rhino,
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


OUTPUT_DIR = os.path.join(ROOT_DIR, "output", "challenge-ramp-variants")
OUTPUT_3DM_FILENAME = "maze_piece_h2d_200x300_challenge_variants_v1.3dm"
OUTPUT_3DM = os.path.join(OUTPUT_DIR, OUTPUT_3DM_FILENAME)
EXPECTED_VARIANT_COUNT = 12

DOUBLE_HUMP_RISE = 30.0
DOUBLE_HUMP_RUN = 51.9615242270663
DOUBLE_HUMP_SLOPE_LENGTH = 60.0
DOUBLE_HUMP_VALLEY_LENGTH = 20.0
DOUBLE_HUMP_APPROACH = 36.0769515458674

FLAT_TOP_LENGTH = 30.0
FLAT_TOP_SOUTH_EDGE = 135.0
FLAT_TOP_NORTH_EDGE = 165.0
FLAT_TOP_APPROACH = 6.8282402399031

CENTRAL_PLATFORM_LENGTH = 80.0
CENTRAL_PLATFORM_Z = 60.0
CENTRAL_PLATFORM_SOUTH_EDGE = 110.0
CENTRAL_PLATFORM_NORTH_EDGE = 190.0
CENTRAL_PLATFORM_RUN = 86.6025403784439
CENTRAL_PLATFORM_APPROACH = 23.3974596215561

OFFSET_SOUTH_TOE = 20.0
OFFSET_NORTH_TOE = 280.0
OFFSET_RIDGE_Y = 100.0
OFFSET_RIDGE_Z = 84.0
OFFSET_SOUTH_ANGLE = math.degrees(math.atan2(74.0, 80.0))
OFFSET_NORTH_ANGLE = math.degrees(math.atan2(74.0, 180.0))

ROUNDED_RADIUS = 15.0
ROUNDED_CENTER_Y = 150.0
ROUNDED_CENTER_Z = 69.0
ROUNDED_TANGENT_SOUTH_Y = 142.5
ROUNDED_TANGENT_NORTH_Y = 157.5
ROUNDED_TANGENT_Z = 84.0 - 15.0 + 15.0 * math.cos(math.radians(30.0))
ROUNDED_LINEAR_RUN = (ROUNDED_TANGENT_Z - BASE_TOP_Z) / math.tan(math.radians(30.0))
ROUNDED_SOUTH_TOE = ROUNDED_TANGENT_SOUTH_Y - ROUNDED_LINEAR_RUN
ROUNDED_NORTH_TOE = ROUNDED_TANGENT_NORTH_Y + ROUNDED_LINEAR_RUN
ROUNDED_APPROACH = ROUNDED_SOUTH_TOE
ROUNDED_ARC_LENGTH = ROUNDED_RADIUS * math.radians(60.0)
ROUNDED_MAX_CHORD_DEVIATION = STL_MESH_TOLERANCE
_ROUNDED_MAX_SEGMENT_ANGLE = 2.0 * math.acos(
    1.0 - ROUNDED_MAX_CHORD_DEVIATION / ROUNDED_RADIUS
)
_ROUNDED_FULL_MAX_SEGMENTS = int(math.radians(60.0) // _ROUNDED_MAX_SEGMENT_ANGLE)
_ROUNDED_REMAINDER_ANGLE = (
    math.radians(60.0) - _ROUNDED_FULL_MAX_SEGMENTS * _ROUNDED_MAX_SEGMENT_ANGLE
)
ROUNDED_MAX_FACET_AREA_DEFICIT = RAMP_WIDTH * (
    ROUNDED_ARC_LENGTH
    - _ROUNDED_FULL_MAX_SEGMENTS
    * 2.0
    * ROUNDED_RADIUS
    * math.sin(_ROUNDED_MAX_SEGMENT_ANGLE / 2.0)
    - 2.0 * ROUNDED_RADIUS * math.sin(_ROUNDED_REMAINDER_ANGLE / 2.0)
)

RIB_COUNT_PER_SLOPE = 6
RIB_TRAVEL_WIDTH = 3.0
RIB_PROJECTED_Y_WIDTH = RIB_TRAVEL_WIDTH * math.cos(math.radians(30.0))
RIB_HEIGHT = 1.5
RIB_FUSION_UNDERLAP = 0.05
SOUTH_RIB_CENTERS = tuple(
    SOUTH_TOE_Y + RAMP_RUN * index / 7.0 for index in range(1, RIB_COUNT_PER_SLOPE + 1)
)
NORTH_RIB_CENTERS = tuple(sorted(300.0 - value for value in SOUTH_RIB_CENTERS))

STEP_COUNT = 10
STEP_DROP = 7.4
STEP_TREAD_RUN = 12.81717597600969

LAYOUT_COLUMNS = 4
LAYOUT_X_SPACING = 230.0
LAYOUT_Y_SPACING = 330.0

RAMP_PROFILE_METHOD = (
    "closed slicer-infill YZ profile extruded 161.6 mm in X with 0.05 mm hidden top-skin "
    "underlap; all sharp profile kinks split before Boolean fusion"
)
RIB_METHOD = (
    "six transverse ribs per slope at pinned 1/7 stations; each exact 3.0 mm along slope travel, "
    "1.5 mm vertical height, full X=19.2..180.8 width, 0.05 mm slope underlap"
)
ROUNDED_METHOD = (
    "genuine Rhino circular Arc R15 centered at Y150 Z69, tangent to exact 30-degree faces at "
    "Y142.5/Y157.5; meshed chord deviation <=0.040 mm; no plateau"
)
STEP_METHOD = (
    "south exact 30-degree climb; north ten horizontal treads of 12.81717597600969 mm and ten "
    "vertical drops of 7.4 mm; sharp tread/riser kinks"
)


def _segment(label, first, second, tolerance=0.01):
    return {
        "label": label,
        "first": (float(first[0]), float(first[1])),
        "second": (float(second[0]), float(second[1])),
        "area_tolerance": float(tolerance),
    }


def _sharp_spec(key, filename, label, points, wall_mode="full", special=None, receipt=""):
    points = tuple((float(y), float(z)) for y, z in points)
    surfaces = []
    for index in range(len(points) - 1):
        first = points[index]
        second = points[index + 1]
        if first[1] <= BASE_TOP_Z and second[1] <= BASE_TOP_Z:
            continue
        surfaces.append(_segment("surface_%02d" % (index + 1), first, second))
    profile_peak = max(point[1] for point in points)
    overall_max = max(profile_peak, WALL_TOP_Z if wall_mode != "none" else BASE_TOP_Z)
    return {
        "key": key,
        "filename": filename,
        "object_name": os.path.splitext(filename)[0],
        "label": label,
        "profile_kind": "sharp",
        "points": points,
        "surfaces": tuple(surfaces),
        "wall_mode": wall_mode,
        "special": special,
        "profile_peak_z": profile_peak,
        "expected_max_z": overall_max,
        "profile_receipt": receipt,
    }


def _low_hill_spec(rise):
    run = float(rise) / math.tan(math.radians(30.0))
    toe_south = RIDGE_Y - run
    toe_north = RIDGE_Y + run
    peak_z = BASE_TOP_Z + float(rise)
    return _sharp_spec(
        "low_hill_%dmm_rise" % int(rise),
        "maze_piece_h2d_200x300_low_hill_%dmm_rise_v1.stl" % int(rise),
        "Low Hill %d mm Rise" % int(rise),
        ((toe_south, BASE_TOP_Z), (RIDGE_Y, peak_z), (toe_north, BASE_TOP_Z)),
        receipt=(
            "rise=%.1f;peak_y=150;peak_z=%.1f;run_each=%.13f;angle_each=30;"
            "toes=%.13f,%.13f;approaches=%.13f"
            % (rise, peak_z, run, toe_south, toe_north, toe_south)
        ),
    )


def _double_hump_points():
    first_toe = DOUBLE_HUMP_APPROACH
    first_peak = first_toe + DOUBLE_HUMP_RUN
    valley_south = first_peak + DOUBLE_HUMP_RUN
    valley_north = valley_south + DOUBLE_HUMP_VALLEY_LENGTH
    second_peak = valley_north + DOUBLE_HUMP_RUN
    second_toe = second_peak + DOUBLE_HUMP_RUN
    return (
        (first_toe, BASE_TOP_Z),
        (first_peak, BASE_TOP_Z + DOUBLE_HUMP_RISE),
        (valley_south, BASE_TOP_Z),
        (valley_north, BASE_TOP_Z),
        (second_peak, BASE_TOP_Z + DOUBLE_HUMP_RISE),
        (second_toe, BASE_TOP_Z),
    )


def _step_profile_points():
    points = [(SOUTH_TOE_Y, BASE_TOP_Z), (RIDGE_Y, RIDGE_Z)]
    for index in range(STEP_COUNT):
        tread_end_y = RIDGE_Y + STEP_TREAD_RUN * (index + 1)
        tread_z = RIDGE_Z - STEP_DROP * index
        next_z = RIDGE_Z - STEP_DROP * (index + 1)
        points.append((tread_end_y, tread_z))
        points.append((tread_end_y, next_z))
    return tuple(points)


def variant_specs():
    sharp_ridge_points = (
        (SOUTH_TOE_Y, BASE_TOP_Z),
        (RIDGE_Y, RIDGE_Z),
        (NORTH_TOE_Y, BASE_TOP_Z),
    )
    specs = [
        _sharp_spec(
            "flat_top_30mm",
            "maze_piece_h2d_200x300_flat_top_30mm_v1.stl",
            "Flat Top 30 mm",
            (
                (FLAT_TOP_APPROACH, BASE_TOP_Z),
                (FLAT_TOP_SOUTH_EDGE, RIDGE_Z),
                (FLAT_TOP_NORTH_EDGE, RIDGE_Z),
                (300.0 - FLAT_TOP_APPROACH, BASE_TOP_Z),
            ),
            receipt=(
                "rise=74;angle_each=30;plateau_y=135..165;plateau_length=30;top_z=84;"
                "approaches=6.8282402399031"
            ),
        ),
        _sharp_spec(
            "double_hump_30mm_rise",
            "maze_piece_h2d_200x300_double_hump_30mm_rise_v1.stl",
            "Double Hump 30 mm Rise",
            _double_hump_points(),
            receipt=(
                "humps=2;rise_each=30;peak_z=40;angle_faces=30;run_each=51.9615242270663;"
                "slope_each=60;central_valley=20;approaches=36.0769515458674"
            ),
        ),
        _sharp_spec(
            "traction_ribs",
            "maze_piece_h2d_200x300_traction_ribs_v1.stl",
            "Traction Ribs",
            sharp_ridge_points,
            special="traction_ribs",
            receipt=(
                "base_profile=symmetric_full_height;rib_count_per_slope=6;rib_travel_width=3;"
                "rib_height=1.5;south_centers=%s;north_centers=%s"
                % (
                    ",".join("%.13f" % value for value in SOUTH_RIB_CENTERS),
                    ",".join("%.13f" % value for value in NORTH_RIB_CENTERS),
                )
            ),
        ),
        _low_hill_spec(20.0),
        _low_hill_spec(40.0),
        _low_hill_spec(60.0),
        _sharp_spec(
            "offset_ridge",
            "maze_piece_h2d_200x300_offset_ridge_v1.stl",
            "Offset Ridge",
            ((OFFSET_SOUTH_TOE, BASE_TOP_Z), (OFFSET_RIDGE_Y, OFFSET_RIDGE_Z), (OFFSET_NORTH_TOE, BASE_TOP_Z)),
            receipt=(
                "toes=20,280;peak_y=100;peak_z=84;south_angle=%.12f;north_angle=%.12f;"
                "approaches=20"
                % (OFFSET_SOUTH_ANGLE, OFFSET_NORTH_ANGLE)
            ),
        ),
        {
            "key": "rounded_crest_r15",
            "filename": "maze_piece_h2d_200x300_rounded_crest_r15_v1.stl",
            "object_name": "maze_piece_h2d_200x300_rounded_crest_r15_v1",
            "label": "Rounded Crest R15",
            "profile_kind": "rounded",
            "points": (),
            "surfaces": (
                _segment(
                    "south_linear",
                    (ROUNDED_SOUTH_TOE, BASE_TOP_Z),
                    (ROUNDED_TANGENT_SOUTH_Y, ROUNDED_TANGENT_Z),
                ),
                _segment(
                    "north_linear",
                    (ROUNDED_TANGENT_NORTH_Y, ROUNDED_TANGENT_Z),
                    (ROUNDED_NORTH_TOE, BASE_TOP_Z),
                ),
            ),
            "wall_mode": "full",
            "special": "rounded",
            "profile_peak_z": RIDGE_Z,
            "expected_max_z": RIDGE_Z,
            "profile_receipt": (
                "radius=15;center_yz=150,69;top_yz=150,84;tangencies_y=142.5,157.5;"
                "tangent_z=%.12f;linear_angle=30;toes=%.13f,%.13f;approaches=%.13f"
                % (ROUNDED_TANGENT_Z, ROUNDED_SOUTH_TOE, ROUNDED_NORTH_TOE, ROUNDED_APPROACH)
            ),
        },
        _sharp_spec(
            "central_platform_80mm",
            "maze_piece_h2d_200x300_central_platform_80mm_v1.stl",
            "Central Platform 80 mm",
            (
                (CENTRAL_PLATFORM_APPROACH, BASE_TOP_Z),
                (CENTRAL_PLATFORM_SOUTH_EDGE, CENTRAL_PLATFORM_Z),
                (CENTRAL_PLATFORM_NORTH_EDGE, CENTRAL_PLATFORM_Z),
                (300.0 - CENTRAL_PLATFORM_APPROACH, BASE_TOP_Z),
            ),
            receipt=(
                "rise=50;platform_y=110..190;platform_length=80;platform_z=60;angle_each=30;"
                "run_each=86.6025403784439;approaches=23.3974596215561"
            ),
        ),
        _sharp_spec(
            "single_wall_ridge",
            "maze_piece_h2d_200x300_single_wall_ridge_v1.stl",
            "Single Wall Ridge",
            sharp_ridge_points,
            wall_mode="west",
            receipt="base_profile=symmetric_full_height;walls=west_only;east_wall=omitted",
        ),
        _sharp_spec(
            "open_sides_ridge",
            "maze_piece_h2d_200x300_open_sides_ridge_v1.stl",
            "Open Sides Ridge",
            sharp_ridge_points,
            wall_mode="none",
            receipt="base_profile=symmetric_full_height;walls=none",
        ),
        _sharp_spec(
            "ramp_up_steps_down",
            "maze_piece_h2d_200x300_ramp_up_steps_down_v1.stl",
            "Ramp Up Steps Down",
            _step_profile_points(),
            special="steps",
            receipt=(
                "orientation=smooth_up_south_steps_down_north;south_toe=21.8282402399031;"
                "south_angle=30;ridge_yz=150,84;steps=10;drop_each=7.4;"
                "tread_each=12.81717597600969;north_toe=278.1717597600969"
            ),
        ),
    ]
    if len(specs) != EXPECTED_VARIANT_COUNT:
        raise RuntimeError("Challenge-ramp definition count is not twelve")
    return tuple(specs)


VARIANTS = variant_specs()
VARIANT_BY_KEY = {variant["key"]: variant for variant in VARIANTS}


def combined_position(variant):
    index = next(index for index, candidate in enumerate(VARIANTS) if candidate["key"] == variant["key"])
    return (
        float(index % LAYOUT_COLUMNS) * LAYOUT_X_SPACING,
        float(index // LAYOUT_COLUMNS) * LAYOUT_Y_SPACING,
    )


def profile_points_receipt(variant):
    if variant["profile_kind"] == "rounded":
        return (
            "%.13f,10->142.5,%.12f->ARC_R15_TOP_150,84->157.5,%.12f->%.13f,10"
            % (ROUNDED_SOUTH_TOE, ROUNDED_TANGENT_Z, ROUNDED_TANGENT_Z, ROUNDED_NORTH_TOE)
        )
    return "->".join("%.13f,%.9f" % point for point in variant["points"])


def surface_contract_receipt(variant):
    return "|".join(
        "%s:%.13f,%.9f->%.13f,%.9f:area=%.9f"
        % (
            surface["label"],
            surface["first"][0],
            surface["first"][1],
            surface["second"][0],
            surface["second"][1],
            RAMP_WIDTH
            * math.hypot(
                surface["second"][0] - surface["first"][0],
                surface["second"][1] - surface["first"][1],
            ),
        )
        for surface in variant["surfaces"]
    )


def validate_static_contracts():
    expected_filenames = (
        "maze_piece_h2d_200x300_flat_top_30mm_v1.stl",
        "maze_piece_h2d_200x300_double_hump_30mm_rise_v1.stl",
        "maze_piece_h2d_200x300_traction_ribs_v1.stl",
        "maze_piece_h2d_200x300_low_hill_20mm_rise_v1.stl",
        "maze_piece_h2d_200x300_low_hill_40mm_rise_v1.stl",
        "maze_piece_h2d_200x300_low_hill_60mm_rise_v1.stl",
        "maze_piece_h2d_200x300_offset_ridge_v1.stl",
        "maze_piece_h2d_200x300_rounded_crest_r15_v1.stl",
        "maze_piece_h2d_200x300_central_platform_80mm_v1.stl",
        "maze_piece_h2d_200x300_single_wall_ridge_v1.stl",
        "maze_piece_h2d_200x300_open_sides_ridge_v1.stl",
        "maze_piece_h2d_200x300_ramp_up_steps_down_v1.stl",
    )
    if tuple(variant["filename"] for variant in VARIANTS) != expected_filenames:
        raise ValueError("Challenge-ramp filenames/order changed")
    if len({variant["key"] for variant in VARIANTS}) != EXPECTED_VARIANT_COUNT:
        raise ValueError("Challenge-ramp keys are not unique")
    if CHALLENGE_PLATFORM["pockets"] != {
        "north": (100.0,),
        "east": (150.0,),
        "south": (100.0,),
        "west": (150.0,),
    }:
        raise ValueError("Reviewed H2D pocket layout changed")
    _assert_close(FLAT_TOP_APPROACH, FLAT_TOP_SOUTH_EDGE - RAMP_RUN, 1.0e-12, "flat-top approach")
    _assert_close(
        DOUBLE_HUMP_APPROACH,
        (300.0 - 4.0 * DOUBLE_HUMP_RUN - DOUBLE_HUMP_VALLEY_LENGTH) / 2.0,
        1.0e-12,
        "double-hump approach",
    )
    _assert_close(CENTRAL_PLATFORM_APPROACH, CENTRAL_PLATFORM_SOUTH_EDGE - CENTRAL_PLATFORM_RUN, 1.0e-12, "platform approach")
    _assert_close(ROUNDED_TANGENT_Z, ROUNDED_CENTER_Z + ROUNDED_RADIUS * math.cos(math.radians(30.0)), 1.0e-12, "rounded tangent Z")
    _assert_close(ROUNDED_APPROACH, 300.0 - ROUNDED_NORTH_TOE, 1.0e-12, "rounded symmetry")
    _assert_close(OFFSET_SOUTH_ANGLE, 42.76882539196875, 1.0e-12, "offset south angle")
    _assert_close(OFFSET_NORTH_ANGLE, 22.34810834790941, 1.0e-12, "offset north angle")
    _assert_close(STEP_TREAD_RUN * STEP_COUNT, RAMP_RUN, 1.0e-12, "step descent run")
    _assert_close(STEP_DROP * STEP_COUNT, 74.0, 1.0e-12, "step descent drop")
    _assert_close(RIB_PROJECTED_Y_WIDTH / math.cos(math.radians(30.0)), RIB_TRAVEL_WIDTH, 1.0e-12, "rib travel width")
    if any(
        abs(south + north - 300.0) > 1.0e-12
        for south, north in zip(SOUTH_RIB_CENTERS, reversed(NORTH_RIB_CENTERS))
    ):
        raise ValueError("Traction-rib centers are not symmetric")
    positions = [combined_position(variant) for variant in VARIANTS]
    for first_index, first in enumerate(positions):
        first_box = (first[0], first[1], first[0] + 200.0, first[1] + 300.0)
        for second in positions[first_index + 1 :]:
            second_box = (second[0], second[1], second[0] + 200.0, second[1] + 300.0)
            if min(first_box[2], second_box[2]) > max(first_box[0], second_box[0]) and min(first_box[3], second_box[3]) > max(first_box[1], second_box[1]):
                raise ValueError("Combined challenge-ramp layout overlaps")
    return VARIANTS


def _point_on_segment_yz(vertex, first, second, tolerance=0.003):
    y, z = vertex[1], vertex[2]
    dy = second[0] - first[0]
    dz = second[1] - first[1]
    length = math.hypot(dy, dz)
    if length <= 0.0:
        return False
    cross_distance = abs((y - first[0]) * dz - (z - first[1]) * dy) / length
    projection = ((y - first[0]) * dy + (z - first[1]) * dz) / (length * length)
    return cross_distance <= tolerance and -tolerance <= projection <= 1.0 + tolerance


def _segment_surface_proof(triangles, surface, expected_area=None):
    selected = []
    for triangle in triangles:
        if all(
            RAMP_X_MIN - 0.003 <= vertex[0] <= RAMP_X_MAX + 0.003
            and _point_on_segment_yz(vertex, surface["first"], surface["second"])
            for vertex in triangle
        ) and max(vertex[0] for vertex in triangle) - min(vertex[0] for vertex in triangle) > 0.003:
            selected.append(triangle)
    if not selected:
        raise ValueError("STL contains no triangles for %s" % surface["label"])
    area = sum(_triangle_area(triangle) for triangle in selected)
    if expected_area is None:
        expected_area = RAMP_WIDTH * math.hypot(
            surface["second"][0] - surface["first"][0],
            surface["second"][1] - surface["first"][1],
        )
    _assert_close(area, expected_area, surface["area_tolerance"], "%s serialized area" % surface["label"])
    vertices = [vertex for triangle in selected for vertex in triangle]
    for y, z in (surface["first"], surface["second"]):
        for x in (RAMP_X_MIN, RAMP_X_MAX):
            if not any(
                abs(vertex[0] - x) <= GEOMETRY_TOLERANCE
                and abs(vertex[1] - y) <= GEOMETRY_TOLERANCE
                and abs(vertex[2] - z) <= GEOMETRY_TOLERANCE
                for vertex in vertices
            ):
                raise ValueError("%s is missing endpoint (%.3f, %.3f, %.3f)" % (surface["label"], x, y, z))
    return {"triangle_count": len(selected), "area": area}


def _traction_surface_proof(triangles):
    base_surfaces = (
        _segment("south_base_slope", (SOUTH_TOE_Y, BASE_TOP_Z), (RIDGE_Y, RIDGE_Z), 0.02),
        _segment("north_base_slope", (RIDGE_Y, RIDGE_Z), (NORTH_TOE_Y, BASE_TOP_Z), 0.02),
    )
    expected_exposed_area = RAMP_WIDTH * (
        RAMP_SLOPE_LENGTH - RIB_COUNT_PER_SLOPE * RIB_TRAVEL_WIDTH
    )
    base_proofs = tuple(
        _segment_surface_proof(triangles, surface, expected_exposed_area)
        for surface in base_surfaces
    )
    rib_proofs = []
    half_y = RIB_PROJECTED_Y_WIDTH / 2.0
    for side, centers, plane in (
        ("south", SOUTH_RIB_CENTERS, lambda y: BASE_TOP_Z + math.tan(math.radians(30.0)) * (y - SOUTH_TOE_Y)),
        ("north", NORTH_RIB_CENTERS, lambda y: BASE_TOP_Z + math.tan(math.radians(30.0)) * (NORTH_TOE_Y - y)),
    ):
        for index, center in enumerate(centers, 1):
            y0, y1 = center - half_y, center + half_y
            surface = _segment(
                "%s_rib_%d_top" % (side, index),
                (y0, plane(y0) + RIB_HEIGHT),
                (y1, plane(y1) + RIB_HEIGHT),
                0.01,
            )
            rib_proofs.append(
                _segment_surface_proof(
                    triangles,
                    surface,
                    RAMP_WIDTH * RIB_TRAVEL_WIDTH,
                )
            )
    if len(rib_proofs) != 12:
        raise ValueError("Traction-rib proof did not find exactly twelve rib tops")
    return {
        "base": base_proofs,
        "ribs": tuple(rib_proofs),
        "rib_count": len(rib_proofs),
        "rib_top_area_each": RAMP_WIDTH * RIB_TRAVEL_WIDTH,
    }


def _rounded_surface_proof(triangles):
    variant = VARIANT_BY_KEY["rounded_crest_r15"]
    linear = tuple(_segment_surface_proof(triangles, surface) for surface in variant["surfaces"])
    arc_triangles = []
    arc_vertices = []
    for triangle in triangles:
        if all(
            RAMP_X_MIN - 0.003 <= vertex[0] <= RAMP_X_MAX + 0.003
            and ROUNDED_TANGENT_SOUTH_Y - 0.003 <= vertex[1] <= ROUNDED_TANGENT_NORTH_Y + 0.003
            and abs(
                math.hypot(vertex[1] - ROUNDED_CENTER_Y, vertex[2] - ROUNDED_CENTER_Z)
                - ROUNDED_RADIUS
            )
            <= 0.003
            and vertex[2] >= ROUNDED_TANGENT_Z - 0.003
            for vertex in triangle
        ) and max(vertex[0] for vertex in triangle) - min(vertex[0] for vertex in triangle) > 0.003:
            arc_triangles.append(triangle)
            arc_vertices.extend(triangle)
    if not arc_triangles:
        raise ValueError("Rounded crest STL contains no circular-arc surface triangles")
    arc_area = sum(_triangle_area(triangle) for triangle in arc_triangles)
    expected_area = RAMP_WIDTH * ROUNDED_ARC_LENGTH
    if (
        arc_area > expected_area + 0.01
        or expected_area - arc_area > ROUNDED_MAX_FACET_AREA_DEFICIT + 0.01
    ):
        raise ValueError(
            "Rounded crest faceted area %.6f differs excessively from exact %.6f"
            % (arc_area, expected_area)
        )
    stations = sorted(
        {
            (round(vertex[1], 7), round(vertex[2], 7))
            for vertex in arc_vertices
            if abs(vertex[0] - RAMP_X_MIN) <= 0.003 or abs(vertex[0] - RAMP_X_MAX) <= 0.003
        }
    )
    if len(stations) < 5:
        raise ValueError("Rounded crest arc is visibly under-segmented")
    maximum_deviation = 0.0
    for first, second in zip(stations, stations[1:]):
        midpoint_y = (first[0] + second[0]) / 2.0
        chord_midpoint_z = (first[1] + second[1]) / 2.0
        exact_z = ROUNDED_CENTER_Z + math.sqrt(
            max(0.0, ROUNDED_RADIUS ** 2 - (midpoint_y - ROUNDED_CENTER_Y) ** 2)
        )
        maximum_deviation = max(maximum_deviation, exact_z - chord_midpoint_z)
    if maximum_deviation > ROUNDED_MAX_CHORD_DEVIATION + 1.0e-4:
        raise ValueError(
            "Rounded crest chord deviation %.6f exceeds %.6f mm"
            % (maximum_deviation, ROUNDED_MAX_CHORD_DEVIATION)
        )
    horizontal_peak_area = 0.0
    for triangle in triangles:
        if all(abs(vertex[2] - RIDGE_Z) <= 0.001 for vertex in triangle):
            horizontal_peak_area += _triangle_area(triangle)
    if horizontal_peak_area > 1.0e-4:
        raise ValueError("Rounded crest contains an unintended top plateau")
    required = (
        (RAMP_X_MIN, RIDGE_Y, RIDGE_Z),
        (RAMP_X_MAX, RIDGE_Y, RIDGE_Z),
        (RAMP_X_MIN, ROUNDED_TANGENT_SOUTH_Y, ROUNDED_TANGENT_Z),
        (RAMP_X_MAX, ROUNDED_TANGENT_NORTH_Y, ROUNDED_TANGENT_Z),
    )
    for expected in required:
        if not any(
            abs(vertex[0] - expected[0]) <= GEOMETRY_TOLERANCE
            and abs(vertex[1] - expected[1]) <= GEOMETRY_TOLERANCE
            and abs(vertex[2] - expected[2]) <= GEOMETRY_TOLERANCE
            for vertex in arc_vertices
        ):
            raise ValueError("Rounded crest is missing key point %s" % (expected,))
    return {
        "linear": linear,
        "arc_triangle_count": len(arc_triangles),
        "arc_area": arc_area,
        "exact_arc_area": expected_area,
        "station_count": len(stations),
        "maximum_chord_deviation": maximum_deviation,
    }


def validate_serialized_profile(triangles, variant):
    if variant.get("special") == "traction_ribs":
        return _traction_surface_proof(triangles)
    if variant["profile_kind"] == "rounded":
        return _rounded_surface_proof(triangles)
    proofs = tuple(_segment_surface_proof(triangles, surface) for surface in variant["surfaces"])
    expected_count = 21 if variant.get("special") == "steps" else len(variant["surfaces"])
    if len(proofs) != expected_count:
        raise ValueError("%s surface-proof count is wrong" % variant["key"])
    return {"surfaces": proofs, "surface_count": len(proofs)}


def validate_common_receipts(receipts, variant):
    expected = {
        "variant_key": variant["key"],
        "dimensions_mm": "200.0 x 300.0 x %.1f" % variant["expected_max_z"],
        "wall_mode": variant["wall_mode"],
        "profile_kind": variant["profile_kind"],
        "profile_points_mm": profile_points_receipt(variant),
        "profile_contract": variant["profile_receipt"],
        "surface_contract": surface_contract_receipt(variant),
        "ramp_profile_method": RAMP_PROFILE_METHOD,
        "wall_extension_method": EXTENSION_METHOD,
        "pocket_centers_mm": pocket_layout_receipt(CHALLENGE_PLATFORM),
        "source_3dm_sha256": EXPECTED_SOURCE_SHA256,
        "source_params_sha256": EXPECTED_PARAMS_SHA256,
        "source_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "current_connector_sha256": EXPECTED_CURRENT_CONNECTOR_SHA256,
        "source_wall_objects": "13,14",
        "stl_mesh_receipt": STL_MESH_RECEIPT,
        "pocket_void_z_mm": "0.000000000..8.000000000",
        "ramp_underlap_z_mm": "9.950000000..10.000000000",
        "pocket_void_vertical_clearance_mm": "1.950000000",
        "pocket_void_boolean_receipt": EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
    }
    if variant.get("special") == "traction_ribs":
        expected["special_method"] = RIB_METHOD
    elif variant["profile_kind"] == "rounded":
        expected["special_method"] = ROUNDED_METHOD
    elif variant.get("special") == "steps":
        expected["special_method"] = STEP_METHOD
    else:
        expected["special_method"] = "none"
    for key, expected_value in expected.items():
        if receipts.get(key) != expected_value:
            raise ValueError("%s receipt %s is wrong" % (variant["key"], key))
    uniformity = receipts.get("wall_uniformity_receipt") or ""
    if uniformity.count("stations=50,100,150") != 2 or uniformity.count("max_deviation=") != 2:
        raise ValueError("%s wall-uniformity receipt is incomplete" % variant["key"])
    return {
        "brep_volume": _parse_float(receipts, "brep_volume_mm3"),
        "stl_volume": _parse_float(receipts, "stl_signed_volume_mm3"),
    }


def expected_output_names():
    return {variant["filename"] for variant in VARIANTS} | {OUTPUT_3DM_FILENAME}


def check_generated_outputs(output_dir=OUTPUT_DIR, require_outputs=False):
    expected_names = expected_output_names()
    actual_names = set()
    if os.path.isdir(output_dir):
        actual_names = {name for name in os.listdir(output_dir) if not name.startswith(".")}
    missing = expected_names - actual_names
    unexpected = actual_names - expected_names
    if missing:
        if require_outputs or actual_names:
            raise ValueError("Challenge-ramp variant output set is incomplete; missing: %s" % ", ".join(sorted(missing)))
        print("OUTPUTS not generated yet; run this script through Rhino 8")
        return []
    if unexpected:
        raise ValueError("Challenge-ramp variant output folder has unexpected files: %s" % ", ".join(sorted(unexpected)))
    spec = load_reviewed_spec()
    summaries = []
    for variant in VARIANTS:
        path = os.path.join(output_dir, variant["filename"])
        triangle_count, bounds = _read_binary_stl(path)
        if triangle_count > STL_TRIANGLE_LIMIT:
            raise ValueError("%s exceeds the %d-triangle limit" % (variant["key"], STL_TRIANGLE_LIMIT))
        expected_bounds = (0.0, 0.0, 0.0, 200.0, 300.0, variant["expected_max_z"])
        for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
            _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s STL bound %d" % (variant["key"], index))
        _validate_stl_pocket_receipt(path, CHALLENGE_PLATFORM, spec)
        triangles = _read_stl_triangles(path)
        topology = _audit_triangle_topology(triangles, variant["filename"])
        profile_proof = validate_serialized_profile(triangles, variant)
        summaries.append(
            {
                "variant": variant,
                "triangle_count": triangle_count,
                "bounds": bounds,
                "topology": topology,
                "profile_proof": profile_proof,
            }
        )

    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("Checking the combined challenge-ramp 3dm requires rhino3dm") from exc
    combined_path = os.path.join(output_dir, OUTPUT_3DM_FILENAME)
    model = rhino3dm.File3dm.Read(combined_path)
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Combined challenge-ramp 3dm is unreadable or not in millimeters")
    document_receipts = dict(model.Strings)
    _validate_document_receipts(document_receipts)
    model_objects = list(model.Objects)
    solids = [obj for obj in model_objects if bool(getattr(obj.Geometry, "IsSolid", False))]
    if len(model_objects) != EXPECTED_VARIANT_COUNT or len(solids) != EXPECTED_VARIANT_COUNT:
        raise ValueError("Combined challenge-ramp 3dm must contain exactly twelve closed solids")
    by_name = {obj.Attributes.Name: obj for obj in solids}
    receipt_keys = (
        "variant_key",
        "dimensions_mm",
        "wall_mode",
        "profile_kind",
        "profile_points_mm",
        "profile_contract",
        "surface_contract",
        "ramp_profile_method",
        "wall_extension_method",
        "pocket_centers_mm",
        "source_3dm_sha256",
        "source_params_sha256",
        "source_bridge_sha256",
        "current_connector_sha256",
        "source_wall_objects",
        "wall_uniformity_receipt",
        "stl_mesh_receipt",
        "pocket_void_z_mm",
        "ramp_underlap_z_mm",
        "pocket_void_vertical_clearance_mm",
        "pocket_void_boolean_receipt",
        "special_method",
        "brep_volume_mm3",
        "stl_signed_volume_mm3",
        "mesh_volume_relative_error",
        "local_bounds_mm",
        "layout_translation_mm",
        "laid_out_bounds_mm",
    )
    for summary in summaries:
        variant = summary["variant"]
        if variant["object_name"] not in by_name:
            raise ValueError("Combined challenge-ramp 3dm is missing %s" % variant["object_name"])
        attributes = by_name[variant["object_name"]].Attributes
        receipts = {key: attributes.GetUserString(key) for key in receipt_keys}
        volumes = validate_common_receipts(receipts, variant)
        local_bounds = tuple(float(value) for value in receipts["local_bounds_mm"].split(","))
        expected_local = (0.0, 0.0, 0.0, 200.0, 300.0, variant["expected_max_z"])
        for index, (actual, expected) in enumerate(zip(local_bounds, expected_local)):
            _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s local bound %d" % (variant["key"], index))
        position = combined_position(variant)
        if receipts["layout_translation_mm"] != "%.1f,%.1f,0.0" % position:
            raise ValueError("%s layout-translation receipt is wrong" % variant["key"])
        laid_out = tuple(float(value) for value in receipts["laid_out_bounds_mm"].split(","))
        expected_laid_out = (
            position[0],
            position[1],
            0.0,
            position[0] + 200.0,
            position[1] + 300.0,
            variant["expected_max_z"],
        )
        for index, (actual, expected) in enumerate(zip(laid_out, expected_laid_out)):
            _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s laid-out bound %d" % (variant["key"], index))
        relative_error = abs(summary["topology"]["signed_volume"] - volumes["brep_volume"]) / volumes["brep_volume"]
        if relative_error > STL_VOLUME_RELATIVE_TOLERANCE:
            raise ValueError("%s STL/Brep volume error %.8f" % (variant["key"], relative_error))
        _assert_close(summary["topology"]["signed_volume"], volumes["stl_volume"], 0.20, "%s STL-volume receipt" % variant["key"])
        _assert_close(_parse_float(receipts, "mesh_volume_relative_error"), relative_error, 1.0e-8, "%s volume-error receipt" % variant["key"])
    for summary in summaries:
        print(
            "OUTPUT OK %-33s triangles=%d volume=%.3f bounds=%s"
            % (
                summary["variant"]["key"],
                summary["triangle_count"],
                summary["topology"]["signed_volume"],
                _format_bounds(summary["bounds"]),
            )
        )
    print("OUTPUT OK %s solids=12" % OUTPUT_3DM_FILENAME)
    return summaries


def check_only(output_dir=OUTPUT_DIR, require_outputs=False):
    validate_static_contracts()
    source_receipts = verify_source_receipts()
    walls = validate_source_wall_receipts()
    spec = load_reviewed_spec()
    source_cutters = load_source_cutters_external()
    profile = pocket_profile(spec, source_cutters)
    tracked_fit = validate_connector_fit(SOURCE_BRIDGE_PATH, "tracked standard bridge", spec, source_cutters)
    current_fit = validate_connector_fit(CURRENT_CONNECTOR_PATH, "current rounded connector", spec, source_cutters)
    print(
        "SOURCE OK sha256=%s walls=%s variants=12"
        % (source_receipts["source_3dm"], ",".join(str(record["index"]) for record in walls))
    )
    print(
        "INTERFACE OK pockets=%s cutter_span=%.6f depth=%.1f bridge_clearance=%.3f/%.3f"
        % (
            pocket_layout_receipt(CHALLENGE_PLATFORM),
            profile["full_span"],
            profile["depth"],
            tracked_fit["minimum_planar_clearance"],
            current_fit["minimum_planar_clearance"],
        )
    )
    print("WALL METHOD %s" % EXTENSION_METHOD)
    print("PROFILE METHOD %s" % RAMP_PROFILE_METHOD)
    check_generated_outputs(output_dir, require_outputs=require_outputs)


def _line_curve(first, second):
    return Rhino.Geometry.LineCurve(
        Rhino.Geometry.Point3d(RAMP_X_MIN, float(first[0]), float(first[1])),
        Rhino.Geometry.Point3d(RAMP_X_MIN, float(second[0]), float(second[1])),
    )


def _sharp_profile_curve(variant):
    points = variant["points"]
    profile_points = [
        Rhino.Geometry.Point3d(RAMP_X_MIN, points[0][0], BASE_TOP_Z - RAMP_UNDERLAP),
        Rhino.Geometry.Point3d(RAMP_X_MIN, points[-1][0], BASE_TOP_Z - RAMP_UNDERLAP),
    ]
    profile_points.extend(
        Rhino.Geometry.Point3d(RAMP_X_MIN, y, z) for y, z in reversed(points)
    )
    profile_points.append(profile_points[0])
    curve = Rhino.Geometry.Polyline(profile_points).ToNurbsCurve()
    if curve is None or not curve.IsClosed or not curve.IsPlanar(MODEL_TOLERANCE):
        raise RuntimeError("%s sharp YZ profile is not a closed planar curve" % variant["key"])
    return curve


def _rounded_profile_curve():
    south_underlap = (ROUNDED_SOUTH_TOE, BASE_TOP_Z - RAMP_UNDERLAP)
    north_underlap = (ROUNDED_NORTH_TOE, BASE_TOP_Z - RAMP_UNDERLAP)
    north_toe = (ROUNDED_NORTH_TOE, BASE_TOP_Z)
    north_tangent = (ROUNDED_TANGENT_NORTH_Y, ROUNDED_TANGENT_Z)
    crest = (ROUNDED_CENTER_Y, RIDGE_Z)
    south_tangent = (ROUNDED_TANGENT_SOUTH_Y, ROUNDED_TANGENT_Z)
    south_toe = (ROUNDED_SOUTH_TOE, BASE_TOP_Z)
    curve = Rhino.Geometry.PolyCurve()
    for first, second in (
        (south_underlap, north_underlap),
        (north_underlap, north_toe),
        (north_toe, north_tangent),
    ):
        if not curve.Append(_line_curve(first, second)):
            raise RuntimeError("Could not append a line to the rounded-crest YZ profile")
    arc = Rhino.Geometry.Arc(
        Rhino.Geometry.Point3d(RAMP_X_MIN, north_tangent[0], north_tangent[1]),
        Rhino.Geometry.Point3d(RAMP_X_MIN, crest[0], crest[1]),
        Rhino.Geometry.Point3d(RAMP_X_MIN, south_tangent[0], south_tangent[1]),
    )
    if not arc.IsValid:
        raise RuntimeError("Could not create the exact rounded-crest R15 arc")
    _assert_close(arc.Radius, ROUNDED_RADIUS, 1.0e-9, "Rhino rounded-crest arc radius")
    if not curve.Append(Rhino.Geometry.ArcCurve(arc)):
        raise RuntimeError("Could not append the exact R15 arc to the rounded-crest profile")
    for first, second in (
        (south_tangent, south_toe),
        (south_toe, south_underlap),
    ):
        if not curve.Append(_line_curve(first, second)):
            raise RuntimeError("Could not close the rounded-crest YZ profile")
    if not curve.IsClosed or not curve.IsPlanar(MODEL_TOLERANCE):
        raise RuntimeError("Rounded-crest YZ profile is not a closed planar curve")
    return curve


def _extrude_profile_curve(curve, name):
    surface = Rhino.Geometry.Surface.CreateExtrusion(
        curve,
        Rhino.Geometry.Vector3d(RAMP_WIDTH, 0.0, 0.0),
    )
    if surface is None:
        raise RuntimeError("Could not extrude %s" % name)
    wedge = surface.ToBrep().CapPlanarHoles(MODEL_TOLERANCE)
    if wedge is None:
        raise RuntimeError("Could not cap %s" % name)
    wedge.Faces.SplitKinkyFaces(math.radians(0.25), True)
    return _validate_brep(wedge, name)


def _split_step_terminal_riser(wedge):
    final_riser_top = RIDGE_Z - STEP_DROP * (STEP_COUNT - 1)
    expected_combined_bounds = (
        RAMP_X_MIN,
        NORTH_TOE_Y,
        BASE_TOP_Z - RAMP_UNDERLAP,
        RAMP_X_MAX,
        NORTH_TOE_Y,
        final_riser_top,
    )
    candidates = []
    for face in wedge.Faces:
        bounds = _bounds_tuple(face.GetBoundingBox(True))
        if all(abs(actual - expected) <= GEOMETRY_TOLERANCE for actual, expected in zip(bounds, expected_combined_bounds)):
            candidates.append(face)
    if len(candidates) != 1:
        raise RuntimeError("Expected one combined final-riser/underlap face, found %d" % len(candidates))
    split_curve = Rhino.Geometry.LineCurve(
        Rhino.Geometry.Point3d(RAMP_X_MIN, NORTH_TOE_Y, BASE_TOP_Z),
        Rhino.Geometry.Point3d(RAMP_X_MAX, NORTH_TOE_Y, BASE_TOP_Z),
    )
    split = candidates[0].Split([split_curve], MODEL_TOLERANCE)
    if split is None:
        raise RuntimeError("Could not split the final north riser at the exact Z10 floor kink")
    split = _validate_brep(split, "step wedge with explicit final-riser split")
    return split


def _split_rounded_tangent_faces(wedge):
    expected_top_bounds = (
        RAMP_X_MIN,
        ROUNDED_SOUTH_TOE,
        BASE_TOP_Z,
        RAMP_X_MAX,
        ROUNDED_NORTH_TOE,
        RIDGE_Z,
    )
    candidates = []
    for face in wedge.Faces:
        bounds = _bounds_tuple(face.GetBoundingBox(True))
        if all(abs(actual - expected) <= GEOMETRY_TOLERANCE for actual, expected in zip(bounds, expected_top_bounds)):
            candidates.append(face)
    if len(candidates) != 1:
        raise RuntimeError("Expected one pre-split rounded tangent top face, found %d" % len(candidates))
    split_lines = [
        Rhino.Geometry.LineCurve(
            Rhino.Geometry.Point3d(RAMP_X_MIN, y, z),
            Rhino.Geometry.Point3d(RAMP_X_MAX, y, z),
        )
        for y, z in (
            (ROUNDED_TANGENT_SOUTH_Y, ROUNDED_TANGENT_Z),
            (ROUNDED_CENTER_Y, RIDGE_Z),
            (ROUNDED_TANGENT_NORTH_Y, ROUNDED_TANGENT_Z),
        )
    ]
    split = candidates[0].Split(split_lines, MODEL_TOLERANCE)
    if split is None:
        raise RuntimeError("Could not split the rounded top at its tangent and crest generators")
    return _validate_brep(split, "rounded wedge with explicit tangent/crest face splits")


def _create_ramp_wedge(variant):
    curve = _rounded_profile_curve() if variant["profile_kind"] == "rounded" else _sharp_profile_curve(variant)
    wedge = _extrude_profile_curve(curve, "%s exact ramp wedge" % variant["key"])
    if variant.get("special") == "steps":
        wedge = _split_step_terminal_riser(wedge)
    elif variant["profile_kind"] == "rounded":
        wedge = _split_rounded_tangent_faces(wedge)
    if variant["profile_kind"] == "rounded":
        minimum_y, maximum_y = ROUNDED_SOUTH_TOE, ROUNDED_NORTH_TOE
    else:
        minimum_y, maximum_y = variant["points"][0][0], variant["points"][-1][0]
    expected_bounds = (
        RAMP_X_MIN,
        minimum_y,
        BASE_TOP_Z - RAMP_UNDERLAP,
        RAMP_X_MAX,
        maximum_y,
        variant["profile_peak_z"],
    )
    actual_bounds = _bounds_tuple(wedge.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s wedge bound %d" % (variant["key"], index))
    return wedge


def _face_area(face, description):
    properties = Rhino.Geometry.AreaMassProperties.Compute(face)
    if properties is None:
        raise RuntimeError("Could not measure %s" % description)
    return float(properties.Area)


def _brep_segment_face_proof(brep, surface, expected_area=None):
    first, second = surface["first"], surface["second"]
    if expected_area is None:
        expected_area = RAMP_WIDTH * math.hypot(second[0] - first[0], second[1] - first[1])
    expected_bounds = (
        RAMP_X_MIN,
        min(first[0], second[0]),
        min(first[1], second[1]),
        RAMP_X_MAX,
        max(first[0], second[0]),
        max(first[1], second[1]),
    )
    candidates = []
    for index, face in enumerate(brep.Faces):
        bounds = _bounds_tuple(face.GetBoundingBox(True))
        if all(abs(actual - expected) <= GEOMETRY_TOLERANCE for actual, expected in zip(bounds, expected_bounds)):
            candidates.append((index, _face_area(face, "%s Brep face" % surface["label"]), bounds))
    if not candidates and abs(first[0] - second[0]) <= 1.0e-12:
        # BrepFace.Split retains the parent surface's loose Z bounding box on
        # each child trim.  Identify the deliberately split terminal riser by
        # its exact X/Y extent and exact trimmed area instead.
        for index, face in enumerate(brep.Faces):
            bounds = _bounds_tuple(face.GetBoundingBox(True))
            area = _face_area(face, "%s split Brep face" % surface["label"])
            if (
                abs(bounds[0] - expected_bounds[0]) <= GEOMETRY_TOLERANCE
                and abs(bounds[1] - expected_bounds[1]) <= GEOMETRY_TOLERANCE
                and abs(bounds[3] - expected_bounds[3]) <= GEOMETRY_TOLERANCE
                and abs(bounds[4] - expected_bounds[4]) <= GEOMETRY_TOLERANCE
                and bounds[2] <= expected_bounds[2] + GEOMETRY_TOLERANCE
                and bounds[5] >= expected_bounds[5] - GEOMETRY_TOLERANCE
                and abs(area - expected_area) <= 1.0e-5
            ):
                candidates.append((index, area, bounds))
    if len(candidates) != 1:
        raise RuntimeError(
            "Expected one exact %s Brep face, found %d" % (surface["label"], len(candidates))
        )
    _assert_close(candidates[0][1], expected_area, 1.0e-5, "%s exact Brep area" % surface["label"])
    return {"face_index": candidates[0][0], "area": candidates[0][1]}


def _validate_wedge_surfaces(wedge, variant):
    if variant["profile_kind"] == "rounded":
        # The geometry is G1 smooth, but deliberate trim splits at both tangent
        # generators keep the exact planar and circular serialization proofs
        # independent. Split child faces retain the parent surface's loose box,
        # so their exact trimmed areas are the robust identifiers.
        linear_length = math.hypot(
            ROUNDED_LINEAR_RUN,
            ROUNDED_TANGENT_Z - BASE_TOP_Z,
        )
        linear_area = RAMP_WIDTH * linear_length
        arc_half_area = RAMP_WIDTH * ROUNDED_ARC_LENGTH / 2.0
        linear_candidates = []
        arc_candidates = []
        for index, face in enumerate(wedge.Faces):
            area = _face_area(face, "rounded split Brep face")
            if abs(area - linear_area) <= 1.0e-4:
                linear_candidates.append((index, area))
            if abs(area - arc_half_area) <= 1.0e-4:
                arc_candidates.append((index, area))
        if len(linear_candidates) != 2 or len(arc_candidates) != 2:
            raise RuntimeError(
                "Rounded split-face proof expected two line faces and two half-arc faces; found %d/%d"
                % (len(linear_candidates), len(arc_candidates))
            )
        return {
            "south_linear": {"face_index": linear_candidates[0][0], "area": linear_candidates[0][1]},
            "north_linear": {"face_index": linear_candidates[1][0], "area": linear_candidates[1][1]},
            "rounded_arc_r15_south": {"face_index": arc_candidates[0][0], "area": arc_candidates[0][1]},
            "rounded_arc_r15_north": {"face_index": arc_candidates[1][0], "area": arc_candidates[1][1]},
        }
    proofs = {
        surface["label"]: _brep_segment_face_proof(wedge, surface)
        for surface in variant["surfaces"]
    }
    if variant.get("special") == "steps" and len(proofs) != 21:
        raise RuntimeError("Step wedge does not expose exactly 21 sharp tread/riser surfaces")
    return proofs


def _slope_z(side, y):
    if side == "south":
        return BASE_TOP_Z + math.tan(math.radians(ANGLE_DEGREES)) * (float(y) - SOUTH_TOE_Y)
    if side == "north":
        return BASE_TOP_Z + math.tan(math.radians(ANGLE_DEGREES)) * (NORTH_TOE_Y - float(y))
    raise ValueError("Unknown traction-rib side: %s" % side)


def _create_traction_rib(side, index, center):
    half_y = RIB_PROJECTED_Y_WIDTH / 2.0
    y0, y1 = center - half_y, center + half_y
    points = (
        (y0, _slope_z(side, y0) - RIB_FUSION_UNDERLAP),
        (y1, _slope_z(side, y1) - RIB_FUSION_UNDERLAP),
        (y1, _slope_z(side, y1) + RIB_HEIGHT),
        (y0, _slope_z(side, y0) + RIB_HEIGHT),
    )
    profile_points = [
        Rhino.Geometry.Point3d(RAMP_X_MIN, y, z) for y, z in points
    ]
    profile_points.append(profile_points[0])
    profile = Rhino.Geometry.Polyline(profile_points).ToNurbsCurve()
    rib = _extrude_profile_curve(profile, "%s traction rib %d" % (side, index))
    top_surface = _segment(
        "%s_rib_%d_top" % (side, index),
        (y0, _slope_z(side, y0) + RIB_HEIGHT),
        (y1, _slope_z(side, y1) + RIB_HEIGHT),
    )
    proof = _brep_segment_face_proof(rib, top_surface, RAMP_WIDTH * RIB_TRAVEL_WIDTH)
    return rib, proof


def _create_traction_ribs():
    ribs = []
    proofs = []
    for side, centers in (("south", SOUTH_RIB_CENTERS), ("north", NORTH_RIB_CENTERS)):
        for index, center in enumerate(centers, 1):
            rib, proof = _create_traction_rib(side, index, center)
            ribs.append(rib)
            proofs.append(proof)
    if len(ribs) != 12:
        raise RuntimeError("Traction-rib construction did not produce exactly twelve ribs")
    return ribs, proofs


def _validate_final_piece(piece, variant, minimum_volume):
    piece = _validate_brep(piece, variant["object_name"])
    expected_bounds = (0.0, 0.0, 0.0, 200.0, 300.0, variant["expected_max_z"])
    bounds = _bounds_tuple(piece.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
        _assert_close(actual, expected, GEOMETRY_TOLERANCE, "%s final bound %d" % (variant["key"], index))
    volume = abs(float(piece.GetVolume()))
    if not math.isfinite(volume) or volume <= minimum_volume:
        raise RuntimeError("%s final Brep volume is implausible" % variant["key"])
    return piece, bounds, volume


def _duplicate(brep):
    duplicate = brep.DuplicateBrep()
    if duplicate is None:
        raise RuntimeError("Could not duplicate a reviewed challenge-ramp Brep")
    return duplicate


def build_challenge_variant_pieces():
    source_receipts = verify_source_receipts()
    spec = load_reviewed_spec()
    _cutter_model, source_cutters = load_source_cutters_rhino()
    pocket_profile(spec, source_cutters)
    _wall_model, source_walls = load_source_walls_rhino()
    uniformity = {
        "west": verify_uniform_central_section(source_walls["west"], "west"),
        "east": verify_uniform_central_section(source_walls["east"], "east"),
    }
    extended_walls = {
        "west": extend_wall_central_section(source_walls["west"], "west", uniformity["west"]),
        "east": extend_wall_central_section(source_walls["east"], "east", uniformity["east"]),
    }
    base = _build_platform(CHALLENGE_PLATFORM, spec, source_cutters)
    assemblies = {
        "none": _duplicate(base),
        "west": _union(
            (_duplicate(base), _duplicate(extended_walls["west"])),
            "reviewed H2D base plus west source wall",
            MODEL_TOLERANCE,
        ),
        "full": _union(
            (_duplicate(base), _duplicate(extended_walls["west"]), _duplicate(extended_walls["east"])),
            "reviewed H2D base plus both source walls",
            MODEL_TOLERANCE,
        ),
    }
    pieces = {}
    build_proofs = {}
    for variant in VARIANTS:
        wedge = _create_ramp_wedge(variant)
        wedge_surfaces = _validate_wedge_surfaces(wedge, variant)
        assembly = _duplicate(assemblies[variant["wall_mode"]])
        minimum_volume = abs(float(assembly.GetVolume()))
        piece = _union(
            (assembly, wedge),
            "%s base/ramp fusion" % variant["key"],
            MODEL_TOLERANCE,
        )
        rib_surfaces = ()
        if variant.get("special") == "traction_ribs":
            ribs, rib_surfaces = _create_traction_ribs()
            piece = _union(
                tuple([piece] + ribs),
                "traction-rib final fusion",
                MODEL_TOLERANCE,
            )
        piece, bounds, volume = _validate_final_piece(piece, variant, minimum_volume)
        pocket_void_proof = _validate_final_pocket_voids(piece, spec, source_cutters)
        if pocket_void_boolean_receipt(pocket_void_proof) != EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT:
            raise RuntimeError("%s pocket-void receipt is not exact zero" % variant["key"])
        pieces[variant["key"]] = piece
        build_proofs[variant["key"]] = {
            "bounds": bounds,
            "volume": volume,
            "pocket_voids": pocket_void_proof,
            "wedge_surfaces": wedge_surfaces,
            "rib_surfaces": rib_surfaces,
        }
        print(
            "BUILT %-33s faces=%d volume=%.3f bounds=%s"
            % (variant["key"], piece.Faces.Count, volume, _format_bounds(bounds))
        )
    return pieces, build_proofs, spec, source_receipts, uniformity


def _mesh_stl_triangles(brep, name):
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
        raise RuntimeError("Could not mesh %s" % name)
    triangles = []
    for mesh in meshes:
        if mesh is None or not mesh.IsValid:
            raise RuntimeError("Rhino returned an invalid face mesh for %s" % name)
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


def _translated_copy(brep, x, y):
    duplicate = _duplicate(brep)
    if not duplicate.Transform(Rhino.Geometry.Transform.Translation(float(x), float(y), 0.0)):
        raise RuntimeError("Could not translate a challenge-ramp preview Brep")
    return duplicate


def _special_method(variant):
    if variant.get("special") == "traction_ribs":
        return RIB_METHOD
    if variant["profile_kind"] == "rounded":
        return ROUNDED_METHOD
    if variant.get("special") == "steps":
        return STEP_METHOD
    return "none"


def _profile_brep_proof_text(build_proof):
    entries = []
    for label in sorted(build_proof["wedge_surfaces"]):
        entries.append("%s=%.9f" % (label, build_proof["wedge_surfaces"][label]["area"]))
    if build_proof["rib_surfaces"]:
        entries.append(
            "rib_tops=%d@%.9f"
            % (len(build_proof["rib_surfaces"]), RAMP_WIDTH * RIB_TRAVEL_WIDTH)
        )
    return ";".join(entries)


def _set_object_receipts(
    attributes,
    variant,
    source_receipts,
    uniformity,
    build_proof,
    stl_volume,
    relative_error,
    local_bounds,
    translation,
    laid_out_bounds,
):
    attributes.SetUserString("variant_key", variant["key"])
    attributes.SetUserString("dimensions_mm", "200.0 x 300.0 x %.1f" % variant["expected_max_z"])
    attributes.SetUserString("wall_mode", variant["wall_mode"])
    attributes.SetUserString("profile_kind", variant["profile_kind"])
    attributes.SetUserString("profile_points_mm", profile_points_receipt(variant))
    attributes.SetUserString("profile_contract", variant["profile_receipt"])
    attributes.SetUserString("surface_contract", surface_contract_receipt(variant))
    attributes.SetUserString("ramp_profile_method", RAMP_PROFILE_METHOD)
    attributes.SetUserString("special_method", _special_method(variant))
    attributes.SetUserString("wall_extension_method", EXTENSION_METHOD)
    attributes.SetUserString("pocket_centers_mm", pocket_layout_receipt(CHALLENGE_PLATFORM))
    attributes.SetUserString("source_3dm_sha256", source_receipts["source_3dm"])
    attributes.SetUserString("source_params_sha256", source_receipts["params"])
    attributes.SetUserString("source_bridge_sha256", source_receipts["source_bridge"])
    attributes.SetUserString("current_connector_sha256", source_receipts["current_connector"])
    attributes.SetUserString("source_wall_objects", "13,14")
    attributes.SetUserString("wall_uniformity_receipt", wall_uniformity_text(uniformity))
    attributes.SetUserString("stl_mesh_receipt", STL_MESH_RECEIPT)
    attributes.SetUserString("pocket_void_z_mm", "0.000000000..8.000000000")
    attributes.SetUserString("ramp_underlap_z_mm", "9.950000000..10.000000000")
    attributes.SetUserString("pocket_void_vertical_clearance_mm", "1.950000000")
    attributes.SetUserString(
        "pocket_void_boolean_receipt",
        pocket_void_boolean_receipt(build_proof["pocket_voids"]),
    )
    attributes.SetUserString("brep_profile_surface_proof", _profile_brep_proof_text(build_proof))
    attributes.SetUserString("brep_volume_mm3", "%.9f" % build_proof["volume"])
    attributes.SetUserString("stl_signed_volume_mm3", "%.9f" % stl_volume)
    attributes.SetUserString("mesh_volume_relative_error", "%.12f" % relative_error)
    attributes.SetUserString("local_bounds_mm", ",".join("%.9f" % value for value in local_bounds))
    attributes.SetUserString(
        "layout_translation_mm",
        "%.1f,%.1f,0.0" % (translation[0], translation[1]),
    )
    attributes.SetUserString("laid_out_bounds_mm", ",".join("%.9f" % value for value in laid_out_bounds))


def _document_layout_receipt():
    return "columns=4;x_spacing=230;y_spacing=330;positions=" + "|".join(
        "%s@%.1f,%.1f" % ((variant["key"],) + combined_position(variant))
        for variant in VARIANTS
    )


def _validate_document_receipts(strings):
    expected = {
        "generator": "scripts/generate_challenge_ramp_variants.py",
        "variant_count": "12",
        "variant_names": ",".join(variant["object_name"] for variant in VARIANTS),
        "layout_receipt": _document_layout_receipt(),
        "source_3dm_sha256": EXPECTED_SOURCE_SHA256,
        "source_params_sha256": EXPECTED_PARAMS_SHA256,
        "source_bridge_sha256": EXPECTED_BRIDGE_SHA256,
        "current_connector_sha256": EXPECTED_CURRENT_CONNECTOR_SHA256,
        "source_wall_objects": "13,14",
        "wall_extension_method": EXTENSION_METHOD,
        "ramp_profile_method": RAMP_PROFILE_METHOD,
        "pocket_centers_mm": pocket_layout_receipt(CHALLENGE_PLATFORM),
        "output_files": ",".join(variant["filename"] for variant in VARIANTS),
    }
    for key, expected_value in expected.items():
        if strings.get(key) != expected_value:
            raise ValueError("Combined challenge-ramp document receipt %s is wrong" % key)
    uniformity = strings.get("wall_uniformity_receipt") or ""
    if uniformity.count("stations=50,100,150") != 2:
        raise ValueError("Combined challenge-ramp document wall receipt is incomplete")


def _validate_saved_3dm(path):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None or model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Could not reopen the millimeter challenge-ramp variant 3dm")
    objects = list(model.Objects)
    if len(objects) != EXPECTED_VARIANT_COUNT:
        raise RuntimeError("Reopened challenge-ramp variant 3dm must contain exactly twelve objects")
    by_name = {model_object.Attributes.Name: model_object for model_object in objects}
    if set(by_name) != {variant["object_name"] for variant in VARIANTS}:
        raise RuntimeError("Reopened challenge-ramp variant names are wrong")
    for variant in VARIANTS:
        model_object = by_name[variant["object_name"]]
        geometry = _validate_brep(model_object.Geometry, "reopened %s" % variant["key"])
        position = combined_position(variant)
        expected_bounds = (
            position[0],
            position[1],
            0.0,
            position[0] + 200.0,
            position[1] + 300.0,
            variant["expected_max_z"],
        )
        bounds = _bounds_tuple(geometry.GetBoundingBox(True))
        for index, (actual, expected) in enumerate(zip(bounds, expected_bounds)):
            _assert_close(actual, expected, GEOMETRY_TOLERANCE, "reopened %s bound %d" % (variant["key"], index))
        receipts = {
            key: model_object.Attributes.GetUserString(key)
            for key in (
                "variant_key",
                "dimensions_mm",
                "wall_mode",
                "profile_kind",
                "profile_points_mm",
                "profile_contract",
                "surface_contract",
                "ramp_profile_method",
                "wall_extension_method",
                "pocket_centers_mm",
                "source_3dm_sha256",
                "source_params_sha256",
                "source_bridge_sha256",
                "current_connector_sha256",
                "source_wall_objects",
                "wall_uniformity_receipt",
                "stl_mesh_receipt",
                "pocket_void_z_mm",
                "ramp_underlap_z_mm",
                "pocket_void_vertical_clearance_mm",
                "pocket_void_boolean_receipt",
                "special_method",
                "brep_volume_mm3",
                "stl_signed_volume_mm3",
                "mesh_volume_relative_error",
            )
        }
        volume_receipts = validate_common_receipts(receipts, variant)
        _assert_close(
            abs(float(geometry.GetVolume())),
            volume_receipts["brep_volume"],
            0.01,
            "reopened %s Brep volume" % variant["key"],
        )
    document_keys = (
        "generator",
        "variant_count",
        "variant_names",
        "layout_receipt",
        "source_3dm_sha256",
        "source_params_sha256",
        "source_bridge_sha256",
        "current_connector_sha256",
        "source_wall_objects",
        "wall_extension_method",
        "wall_uniformity_receipt",
        "ramp_profile_method",
        "pocket_centers_mm",
        "output_files",
    )
    _validate_document_receipts(
        {key: model.Strings.GetValue(key) for key in document_keys}
    )
    print("REOPENED %s: twelve laid-out closed solids with exact receipts and accurate bounds" % os.path.basename(path))


def _save_combined(
    pieces,
    path,
    source_receipts,
    uniformity,
    build_proofs,
    mesh_receipts,
):
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is None:
        raise RuntimeError("Could not create a headless challenge-ramp variant document")
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    doc.ModelAbsoluteTolerance = MODEL_TOLERANCE
    doc.ModelAngleToleranceRadians = math.radians(0.25)
    root_layer = Rhino.DocObjects.Layer()
    root_layer.Name = "H2DChallengeRampVariants"
    root_layer.Color = _color(92, 105, 122)
    root_index = doc.Layers.Add(root_layer)
    colors = (
        (70, 125, 190),
        (225, 135, 55),
        (75, 155, 110),
        (145, 100, 185),
        (195, 80, 95),
        (75, 155, 175),
        (190, 125, 60),
        (105, 135, 205),
        (150, 115, 70),
        (95, 150, 95),
        (125, 125, 135),
        (200, 105, 65),
    )
    for index, variant in enumerate(VARIANTS):
        layer = Rhino.DocObjects.Layer()
        layer.Name = variant["label"]
        layer.ParentLayerId = doc.Layers[root_index].Id
        layer.Color = _color(*colors[index])
        layer_index = doc.Layers.Add(layer)
        if layer_index < 0:
            raise RuntimeError("Could not add layer for %s" % variant["key"])
        position = combined_position(variant)
        preview = _translated_copy(pieces[variant["key"]], position[0], position[1])
        laid_out_bounds = _bounds_tuple(preview.GetBoundingBox(True))
        object_id = doc.Objects.AddBrep(preview)
        rhino_object = doc.Objects.FindId(object_id)
        if rhino_object is None:
            raise RuntimeError("Could not add %s to the combined 3dm" % variant["key"])
        attributes = rhino_object.Attributes
        attributes.Name = variant["object_name"]
        attributes.LayerIndex = layer_index
        attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
        mesh_receipt = mesh_receipts[variant["key"]]
        _set_object_receipts(
            attributes,
            variant,
            source_receipts,
            uniformity,
            build_proofs[variant["key"]],
            mesh_receipt["stl_volume"],
            mesh_receipt["relative_error"],
            build_proofs[variant["key"]]["bounds"],
            position,
            laid_out_bounds,
        )
        if not doc.Objects.ModifyAttributes(object_id, attributes, True):
            raise RuntimeError("Could not save receipts for %s" % variant["key"])
    document_receipts = {
        "generator": "scripts/generate_challenge_ramp_variants.py",
        "variant_count": "12",
        "variant_names": ",".join(variant["object_name"] for variant in VARIANTS),
        "layout_receipt": _document_layout_receipt(),
        "source_3dm_sha256": source_receipts["source_3dm"],
        "source_params_sha256": source_receipts["params"],
        "source_bridge_sha256": source_receipts["source_bridge"],
        "current_connector_sha256": source_receipts["current_connector"],
        "source_wall_objects": "13,14",
        "wall_extension_method": EXTENSION_METHOD,
        "wall_uniformity_receipt": wall_uniformity_text(uniformity),
        "ramp_profile_method": RAMP_PROFILE_METHOD,
        "pocket_centers_mm": pocket_layout_receipt(CHALLENGE_PLATFORM),
        "output_files": ",".join(variant["filename"] for variant in VARIANTS),
    }
    for key, value in document_receipts.items():
        doc.Strings.SetString(key, value)
    options = Rhino.FileIO.FileWriteOptions()
    options.SuppressDialogBoxes = True
    options.WriteSelectedObjectsOnly = False
    options.WriteGeometryOnly = False
    if not doc.WriteFile(path, options):
        raise RuntimeError("Could not write combined challenge-ramp variant 3dm: %s" % path)
    doc.Dispose()
    _validate_saved_3dm(path)


def generate(output_dir=OUTPUT_DIR):
    if Rhino is None or System is None:
        raise RuntimeError("CAD generation must be run through Rhino 8")
    validate_static_contracts()
    pieces, build_proofs, spec, source_receipts, uniformity = build_challenge_variant_pieces()
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    mesh_receipts = {}
    for variant in VARIANTS:
        piece = pieces[variant["key"]]
        triangles = _mesh_stl_triangles(piece, variant["object_name"])
        if len(triangles) > STL_TRIANGLE_LIMIT:
            raise RuntimeError(
                "%s meshing produced %d triangles, exceeding %d"
                % (variant["key"], len(triangles), STL_TRIANGLE_LIMIT)
            )
        numeric = [
            tuple((float(vertex.X), float(vertex.Y), float(vertex.Z)) for vertex in triangle)
            for triangle in triangles
        ]
        topology = _audit_triangle_topology(numeric, variant["object_name"])
        brep_volume = build_proofs[variant["key"]]["volume"]
        relative_error = abs(topology["signed_volume"] - brep_volume) / brep_volume
        if relative_error > STL_VOLUME_RELATIVE_TOLERANCE:
            raise RuntimeError(
                "%s mesh volume differs from its exact Brep by %.8f relative"
                % (variant["key"], relative_error)
            )
        validate_serialized_profile(numeric, variant)
        path = os.path.join(output_dir, variant["filename"])
        _write_binary_stl(path, variant["object_name"], triangles)
        _validate_stl_pocket_receipt(path, CHALLENGE_PLATFORM, spec)
        serialized_triangles = _read_stl_triangles(path)
        serialized_topology = _audit_triangle_topology(serialized_triangles, variant["filename"])
        validate_serialized_profile(serialized_triangles, variant)
        serialized_error = abs(serialized_topology["signed_volume"] - brep_volume) / brep_volume
        if serialized_error > STL_VOLUME_RELATIVE_TOLERANCE:
            raise RuntimeError(
                "%s serialized STL volume differs from its exact Brep by %.8f relative"
                % (variant["key"], serialized_error)
            )
        mesh_receipts[variant["key"]] = {
            "stl_volume": serialized_topology["signed_volume"],
            "relative_error": serialized_error,
            "triangle_count": len(triangles),
        }
        print(
            "WROTE %-66s triangles=%d volume=%.3f error=%.8f"
            % (
                os.path.relpath(path, ROOT_DIR),
                len(triangles),
                serialized_topology["signed_volume"],
                serialized_error,
            )
        )
    combined_path = os.path.join(output_dir, OUTPUT_3DM_FILENAME)
    _save_combined(
        pieces,
        combined_path,
        source_receipts,
        uniformity,
        build_proofs,
        mesh_receipts,
    )
    print("WROTE %s" % os.path.relpath(combined_path, ROOT_DIR))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate twelve H2D challenge-ramp variants")
    parser.add_argument("--check", action="store_true", help="verify source receipts and outputs without Rhino")
    parser.add_argument("--require-outputs", action="store_true", help="make --check fail if outputs are missing")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="challenge-ramp variant output folder")
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
        transcript_path = "/tmp/gridmaze_challenge_ramp_variants_generation.log"
        with open(transcript_path, "w") as transcript:
            try:
                with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
                    main()
                transcript.write("GENERATION OK\n")
            except Exception:
                traceback.print_exc(file=transcript)
                raise
