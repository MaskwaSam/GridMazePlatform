#!/usr/bin/env python3
r"""Generate wall-bearing H2D maze pieces from the reviewed source Breps.

Rhino 8 generation::

    /Applications/Rhino\ 8.app/Contents/Resources/bin/rhinocode script \
        /absolute/path/to/scripts/generate_h2d_maze_variants.py

External validation::

    python3 scripts/generate_h2d_maze_variants.py --check --require-outputs
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

from generate_h2d_compatible_platforms import (
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    PLATFORMS,
    _build_platform,
    _placed_source_cutter,
    _read_stl_vertices,
    _validate_stl_pocket_receipt,
    load_reviewed_spec,
    load_source_cutters_rhino,
    pocket_layout_receipt,
    pocket_profile,
    validate_all_layouts,
    verify_source_receipts,
)
from generate_maze_piece_variants import (
    BOUNDS_TOLERANCE,
    EXPECTED_SOURCE_SHA256,
    SOURCE_PATH,
    _assert_close,
    _audit_triangle_topology,
    _bounds_tuple,
    _color,
    _format_bounds,
    _read_binary_stl,
    _record,
    _sha256,
    _single_valid_solid,
    _union,
    _validate_brep,
    _write_binary_stl,
    classify_source_records,
    inspect_source_with_rhino3dm,
)


OUTPUT_DIR = os.path.join(ROOT_DIR, "output", "h2d-wall-variants")
OUTPUT_3DM = os.path.join(OUTPUT_DIR, "maze_piece_h2d_wall_variants_v1.3dm")
MODEL_TOLERANCE = 0.01
SECTION_STATIONS = (50.0, 100.0, 150.0)
EXTENSION_AMOUNT = 100.0
EXTENSION_OVERLAP = 0.10
EXTENSION_METHOD = (
    "rigid source termini; split at Y=100; translate far source half +100 mm; "
    "extrude exact verified-uniform Y=100 XZ section through 100 mm gap with 0.10 mm overlaps"
)
SIDES = ("north", "east", "south", "west")

VARIANT_TYPES = (
    {
        "key": "straight",
        "label": "Straight",
        "open_sides": ("north", "south"),
        "closed_sides": ("east", "west"),
    },
    {
        "key": "corner",
        "label": "Corner",
        "open_sides": ("north", "east"),
        "closed_sides": ("south", "west"),
    },
    {
        "key": "t_junction",
        "label": "T Junction",
        "open_sides": ("north", "east", "south"),
        "closed_sides": ("west",),
    },
    {
        "key": "cross_junction",
        "label": "Cross Junction",
        "open_sides": ("north", "east", "south", "west"),
        "closed_sides": (),
    },
    {
        "key": "end",
        "label": "End / Dead End",
        "open_sides": ("north",),
        "closed_sides": ("east", "south", "west"),
    },
)


def _platform_key(platform):
    return "%dx%d" % (int(platform["width"]), int(platform["height"]))


def all_output_specs():
    result = []
    for platform in PLATFORMS:
        platform_key = _platform_key(platform)
        for variant in VARIANT_TYPES:
            item = dict(variant)
            item["platform_key"] = platform_key
            item["platform"] = platform
            item["filename"] = "maze_piece_h2d_%s_%s_v1.stl" % (platform_key, variant["key"])
            item["object_name"] = "maze_piece_h2d_%s_%s_v1" % (platform_key, variant["key"])
            result.append(item)
    return tuple(result)


OUTPUT_SPECS = all_output_specs()

TRANSITION_FOOTPRINT = (
    (50.0, 0.0),
    (250.0, 0.0),
    (250.0, 75.0),
    (300.0, 125.0),
    (300.0, 200.0),
    (0.0, 200.0),
    (0.0, 125.0),
    (50.0, 75.0),
)
TRANSITION_PLATFORM = {
    "key": "45deg_transition",
    "label": "H2D 45 Degree Transition",
    "width": 300.0,
    "height": 200.0,
    "pockets": {
        "north": (150.0,),
        "east": (),
        "south": (150.0,),
        "west": (),
    },
}
TRANSITION_SPEC = {
    "key": "45deg_transition",
    "label": "45 Degree X1C to H2D Transition",
    "platform_key": "45deg_transition",
    "platform": TRANSITION_PLATFORM,
    "filename": "maze_piece_h2d_45deg_transition_v1.stl",
    "object_name": "maze_piece_h2d_45deg_transition_v1",
    "open_sides": ("north", "south"),
    "closed_sides": ("left_path", "right_path"),
    "is_transition": True,
}
TRANSITION_POSITION = (0.0, 700.0)
TRANSITION_WALL_PATHS = {
    "left": ((50.0, 0.0), (50.0, 75.0), (0.0, 125.0), (0.0, 200.0)),
    "right": ((250.0, 0.0), (250.0, 75.0), (300.0, 125.0), (300.0, 200.0)),
}
TRANSITION_TERMINAL_PRESERVE_LENGTH = 50.0
TRANSITION_SPLICE_OVERLAP = 0.10
TRANSITION_JOINT_SECTION_STATIONS = (74.9, 75.1, 90.0, 110.0, 124.9, 125.1)
TRANSITION_JOINT_TOLERANCE = 1.0e-5
TRANSITION_JOINT_VOLUME_TOLERANCE = 0.05
TRANSITION_WALL_METHOD = (
    "rigid source terminal regions Y=0..50 and Y=150..200; exact verified-uniform XZ profile; "
    "roadlike-top SweepOneRail MiterType=1 along exact 75/50/75 path with rotated +45/-45 degree "
    "middle segments; 0.10 mm collinear terminal splices; sharp surface-intersection miters"
)

HUB_PLATFORM = {
    "key": "300x300_45deg_four_way",
    "label": "H2D 300 x 300 45 Degree Four Way Hub",
    "width": 300.0,
    "height": 300.0,
    "pockets": {
        "north": (150.0,),
        "east": (150.0,),
        "south": (150.0,),
        "west": (150.0,),
    },
}
HUB_WALL_PATHS = {
    # Directed paths keep the source-derived 1.2 mm vertical panel on the
    # central/playable side; the source wall's sloped reinforcement is omitted.
    "southwest": ((50.0, 0.0), (0.0, 50.0)),
    "southeast": ((300.0, 50.0), (250.0, 0.0)),
    "northeast": ((250.0, 300.0), (300.0, 250.0)),
    "northwest": ((0.0, 250.0), (50.0, 300.0)),
}
HUB_SOURCE_TERMINAL_EXTENT = 1.2
HUB_PANEL_THICKNESS = 1.2
HUB_PANEL_Z = (10.0, 82.0)
HUB_PANEL_PROFILE_AREA = HUB_PANEL_THICKNESS * (HUB_PANEL_Z[1] - HUB_PANEL_Z[0])
HUB_FUSION_KEY_LENGTH = 10.0
HUB_FUSION_KEY_INWARD = (0.10, 1.00)
HUB_FUSION_KEY_Z = (9.90, 10.10)
HUB_CONTACT_UNDERLAP_Z = (9.90, 10.001)
HUB_CONTACT_BOOLEAN_TOLERANCE = 0.0001
HUB_FUSION_VOLUME_TOLERANCE = 0.10
HUB_WALL_METHOD = (
    "exact source-derived west-wall vertical panel profile, 1.2 mm thick from Z=10..82; four rigid "
    "45-degree path extrusions; authored 19.2 mm sloped reinforcement foot intentionally omitted; "
    "hidden 10 x 0.9 x 0.2 mm fusion keys remain within the 1.2 mm panel and span Z=9.9..10.1; "
    "exact 1.2 mm panel-footprint underlap spans Z=9.9..10.001; no scaling"
)
HUB_PROFILE_DESCRIPTION = "source-derived 1.2 mm vertical panels; sloped reinforcement foot removed"
HUB_SPEC = {
    "key": "45deg_four_way",
    "label": "300 x 300 45 Degree Four Way Hub",
    "platform_key": "300x300_45deg_four_way",
    "platform": HUB_PLATFORM,
    "filename": "maze_piece_h2d_300x300_45deg_four_way_v1.stl",
    "object_name": "maze_piece_h2d_300x300_45deg_four_way_v1",
    "open_sides": ("north", "east", "south", "west"),
    "closed_sides": ("southwest", "southeast", "northeast", "northwest"),
    "is_four_way_hub": True,
}
HUB_POSITION = (350.0, 700.0)
ALL_OUTPUT_SPECS = OUTPUT_SPECS + (TRANSITION_SPEC, HUB_SPEC)
TRANSITION_TERMINAL_TOLERANCE = 1.0e-5
STL_MESH_TOLERANCE = 0.04
STL_MESH_MINIMUM_EDGE = 0.05
STL_MESH_MAXIMUM_EDGE = 8.0
STL_VOLUME_RELATIVE_TOLERANCE = 5.0e-4
STL_TRIANGLE_LIMIT = 50000
STL_MESH_RECEIPT = (
    "Rhino Brep mesher tolerance=0.040 mm; relative tolerance=0; minimum edge=0.050 mm; "
    "maximum edge=8.000 mm; "
    "SimplePlanes=1; RefineGrid=1; hub-only Rhino degenerate-face cull before/after triangulation; "
    "volume relative error<=0.000500"
)


def combined_position(output_spec):
    if output_spec.get("is_four_way_hub"):
        return HUB_POSITION
    if output_spec.get("is_transition"):
        return TRANSITION_POSITION
    platform_index = next(
        index for index, platform in enumerate(PLATFORMS) if _platform_key(platform) == output_spec["platform_key"]
    )
    variant_index = next(index for index, variant in enumerate(VARIANT_TYPES) if variant["key"] == output_spec["key"])
    if platform_index == 0:
        return (variant_index * 230.0, 0.0)
    return (variant_index * 330.0, 350.0)


def piece_storage_key(output_spec):
    return (output_spec["platform_key"], output_spec["key"])


def _vertex_bounds(geometry):
    points = [vertex.Location for vertex in geometry.Vertices]
    return (
        min(float(point.X) for point in points),
        min(float(point.Y) for point in points),
        min(float(point.Z) for point in points),
        max(float(point.X) for point in points),
        max(float(point.Y) for point in points),
        max(float(point.Z) for point in points),
    )


def inspect_source_walls_external():
    if _sha256(SOURCE_PATH) != EXPECTED_SOURCE_SHA256:
        raise ValueError("Source Rhino model fingerprint changed")
    selection = inspect_source_with_rhino3dm(SOURCE_PATH)
    walls = selection["walls"]
    if len(walls) != 2 or selection["wall_long_axis"] != "y":
        raise ValueError("Reviewed source must contain two Y-oriented wall solids")
    ordered = sorted(walls, key=lambda record: record["x_center"])
    expected = (
        (0.0, 0.0, 10.0, 19.2, 200.0, 82.0),
        (180.8, 0.0, 10.0, 200.0, 200.0, 82.0),
    )
    receipts = []
    for record, expected_bounds in zip(ordered, expected):
        actual = _vertex_bounds(record["geometry"])
        for index, (value, target) in enumerate(zip(actual, expected_bounds)):
            _assert_close(value, target, 0.002, "source wall vertex bound %d" % index)
        geometry = record["geometry"]
        if len(geometry.Faces) != 10 or len(geometry.Vertices) != 15:
            raise ValueError("Source wall topology changed from reviewed 10-face/15-vertex Brep")
        y_values = [round(float(vertex.Location.Y), 6) for vertex in geometry.Vertices]
        if 0.0 not in y_values or 200.0 not in y_values:
            raise ValueError("Source wall terminal geometry is missing")
        longitudinal_stations = tuple(sorted(set(y_values)))
        if longitudinal_stations != (0.0, HUB_SOURCE_TERMINAL_EXTENT, 200.0):
            raise ValueError(
                "Source wall longitudinal topology changed: %s" % (longitudinal_stations,)
            )
        receipts.append(
            {
                "index": record["index"],
                "bounds": actual,
                "faces": len(geometry.Faces),
                "vertices": len(geometry.Vertices),
                "longitudinal_stations": longitudinal_stations,
            }
        )
    return tuple(receipts)


def source_terminal_feature_extent_external():
    walls = inspect_source_walls_external()
    for wall in walls:
        if wall["longitudinal_stations"] != (0.0, HUB_SOURCE_TERMINAL_EXTENT, 200.0):
            raise ValueError("Reviewed source terminal feature extent is no longer 1.2 mm")
    return HUB_SOURCE_TERMINAL_EXTENT


def load_source_walls_rhino(path=SOURCE_PATH):
    if _sha256(path) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("Source Rhino model fingerprint changed")
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None or model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Could not read millimeter source Rhino model")
    records = []
    for index, model_object in enumerate(model.Objects):
        records.append(
            _record(
                index,
                model_object.Geometry,
                model_object.Attributes.Name,
                "",
                accurate=True,
            )
        )
    selection = classify_source_records(records)
    if selection["wall_long_axis"] != "y" or len(selection["walls"]) != 2:
        raise RuntimeError("Could not identify the reviewed source wall pair")
    walls = sorted(selection["walls"], key=lambda record: record["x_center"])
    west = _validate_brep(walls[0]["geometry"].DuplicateBrep(), "source west wall")
    east = _validate_brep(walls[1]["geometry"].DuplicateBrep(), "source east wall")
    expected = (
        (west, (0.0, 0.0, 10.0, 19.2, 200.0, 82.0), "west"),
        (east, (180.8, 0.0, 10.0, 200.0, 200.0, 82.0), "east"),
    )
    for wall, expected_bounds, label in expected:
        actual = _bounds_tuple(wall.GetBoundingBox(True))
        for index, (value, target) in enumerate(zip(actual, expected_bounds)):
            _assert_close(value, target, 0.002, "%s source wall bound %d" % (label, index))
    return model, {"west": west, "east": east}


def _section_curve(brep, station, tolerance=MODEL_TOLERANCE):
    plane = Rhino.Geometry.Plane(
        Rhino.Geometry.Point3d(0.0, float(station), 0.0),
        Rhino.Geometry.Vector3d.YAxis,
    )
    result = Rhino.Geometry.Intersect.Intersection.BrepPlane(brep, plane, tolerance)
    if result is None or len(result) < 2 or not result[0]:
        raise RuntimeError("Could not intersect wall at Y=%.3f" % station)
    curves = list(result[1])
    joined = Rhino.Geometry.Curve.JoinCurves(curves, tolerance)
    closed = [curve for curve in joined if curve.IsClosed]
    if len(closed) != 1:
        raise RuntimeError("Wall section at Y=%.3f must be one closed curve" % station)
    curve = closed[0]
    if not curve.IsPlanar(tolerance):
        raise RuntimeError("Wall section at Y=%.3f is not planar" % station)
    return curve


def _curve_max_distance(first, second, samples=128):
    maximum = 0.0
    for source, target in ((first, second), (second, first)):
        for index in range(samples + 1):
            parameter = source.Domain.ParameterAt(float(index) / float(samples))
            point = source.PointAt(parameter)
            closest = target.ClosestPoint(point)
            if closest is None or not closest[0]:
                raise RuntimeError("Could not compare wall section curves")
            target_point = target.PointAt(closest[1])
            maximum = max(maximum, point.DistanceTo(target_point))
    return maximum


def verify_uniform_central_section(wall, label):
    sections = []
    areas = []
    perimeters = []
    for station in SECTION_STATIONS:
        curve = _section_curve(wall, station)
        normalized = curve.DuplicateCurve()
        normalized.Transform(Rhino.Geometry.Transform.Translation(0.0, -station, 0.0))
        area_properties = Rhino.Geometry.AreaMassProperties.Compute(normalized)
        if area_properties is None:
            raise RuntimeError("Could not compute %s wall section area" % label)
        sections.append(normalized)
        areas.append(abs(float(area_properties.Area)))
        perimeters.append(float(normalized.GetLength()))
    maximum_deviation = 0.0
    for first, second in ((sections[0], sections[1]), (sections[1], sections[2]), (sections[0], sections[2])):
        maximum_deviation = max(maximum_deviation, _curve_max_distance(first, second))
    if maximum_deviation > 1.0e-5:
        raise RuntimeError("%s wall central section varies by %.9f mm" % (label, maximum_deviation))
    if max(areas) - min(areas) > 1.0e-5 or max(perimeters) - min(perimeters) > 1.0e-5:
        raise RuntimeError("%s wall central section metrics are not uniform" % label)
    return {
        "label": label,
        "stations": SECTION_STATIONS,
        "maximum_deviation": maximum_deviation,
        "area": sum(areas) / len(areas),
        "perimeter": sum(perimeters) / len(perimeters),
    }


def uniformity_receipt(receipt):
    return (
        "%s:stations=%s,max_deviation=%.9fmm,area=%.9fmm2,perimeter=%.9fmm"
        % (
            receipt["label"],
            ",".join("%.0f" % value for value in receipt["stations"]),
            receipt["maximum_deviation"],
            receipt["area"],
            receipt["perimeter"],
        )
    )


def verify_source_terminal_feature(wall, label):
    central = _section_curve(wall, 100.0)
    central.Transform(Rhino.Geometry.Transform.Translation(0.0, -100.0, 0.0))
    samples = {}
    far_band_inner_station = 200.0 - HUB_SOURCE_TERMINAL_EXTENT - 0.01
    diagnostic_stations = (
        HUB_SOURCE_TERMINAL_EXTENT / 2.0,
        HUB_SOURCE_TERMINAL_EXTENT + 0.01,
        1.5,
        2.0,
        3.0,
        5.0,
        10.0,
        20.0,
        30.0,
        40.0,
        50.0,
        far_band_inner_station,
    )
    deviations_by_station = {}
    for station in diagnostic_stations:
        section = _section_curve(wall, station)
        section.Transform(Rhino.Geometry.Transform.Translation(0.0, -station, 0.0))
        deviations_by_station[station] = _curve_max_distance(section, central)
    samples["within_feature"] = deviations_by_station[HUB_SOURCE_TERMINAL_EXTENT / 2.0]
    samples["after_feature"] = deviations_by_station[HUB_SOURCE_TERMINAL_EXTENT + 0.01]
    samples["far_cap"] = deviations_by_station[far_band_inner_station]
    if samples["after_feature"] > 1.0e-5 or samples["far_cap"] > 1.0e-5:
        print(
            "SOURCE TERMINAL SECTION DEVIATIONS %s"
            % ",".join(
                "%.3f=%.9f" % (station, deviations_by_station[station])
                for station in diagnostic_stations
            )
        )
        raise RuntimeError(
            "%s wall does not become the verified uniform profile after the 1.2 mm topology band"
            % label
        )
    return {
        "label": label,
        "topology_extent": HUB_SOURCE_TERMINAL_EXTENT,
        "within_feature_deviation": samples["within_feature"],
        "after_feature_deviation": samples["after_feature"],
        "far_cap_deviation": samples["far_cap"],
    }


def source_terminal_feature_receipt(receipt):
    return (
        "%s:topology_extent=%.3fmm,within_deviation=%.9fmm,after_deviation=%.9fmm,"
        "far_cap_deviation=%.9fmm"
        % (
            receipt["label"],
            receipt["topology_extent"],
            receipt["within_feature_deviation"],
            receipt["after_feature_deviation"],
            receipt["far_cap_deviation"],
        )
    )


def transition_terminal_receipt(receipt):
    return ";".join(
        "%s:near=%.9fmm,far=%.9fmm"
        % (
            side,
            receipt[side]["near_max_deviation"],
            receipt[side]["far_max_deviation"],
        )
        for side in ("left", "right")
    )


def transition_joint_receipt(receipt):
    return "|".join(
        "%s:stations=%s,max_section_deviation=%.9fmm,central_volume_error=%.9fmm3"
        % (
            side,
            "/".join(
                "%.1f" % station
                for station in receipt[side]["joint_quality"]["stations"]
            ),
            receipt[side]["joint_quality"]["maximum_section_deviation"],
            receipt[side]["joint_quality"]["central_volume_error"],
        )
        for side in ("left", "right")
    )


def wall_method_for_spec(output_spec):
    if output_spec.get("is_transition"):
        return TRANSITION_WALL_METHOD
    if output_spec.get("is_four_way_hub"):
        return HUB_WALL_METHOD
    return EXTENSION_METHOD


def hub_path_receipt():
    return "|".join(
        "%s=%.1f,%.1f>%.1f,%.1f" % (corner, path[0][0], path[0][1], path[1][0], path[1][1])
        for corner, path in (
            ("southwest", HUB_WALL_PATHS["southwest"]),
            ("southeast", HUB_WALL_PATHS["southeast"]),
            ("northeast", HUB_WALL_PATHS["northeast"]),
            ("northwest", HUB_WALL_PATHS["northwest"]),
        )
    )


def hub_wall_quality_receipt(receipts):
    return "|".join(
        (
            "%s:length=%.9fmm,panel=%.9fmm,z=%.9f..%.9fmm,"
            "inward=%.9f..%.9fmm,profile_area=%.9fmm2,volume_deviation=%.9fmm3,foot_removed=1"
        )
        % (
            corner,
            receipts[corner]["length"],
            receipts[corner]["panel_thickness"],
            receipts[corner]["minimum_z"],
            receipts[corner]["maximum_z"],
            receipts[corner]["minimum_inward"],
            receipts[corner]["maximum_inward"],
            receipts[corner]["profile_area"],
            receipts[corner]["volume_deviation"],
        )
        for corner in ("southwest", "southeast", "northeast", "northwest")
    )


def hub_source_panel_receipt(receipts):
    receipt = receipts["source_panel"]
    return (
        "source=reviewed_west_wall_intersection,bounds=%s,profile_area=%.9fmm2,"
        "volume=%.9fmm3,sloped_foot_removed=1"
        % (
            ",".join("%.3f" % value for value in receipt["bounds"]),
            receipt["profile_area"],
            receipt["volume"],
        )
    )


def hub_fusion_key_receipt(receipts):
    receipt = receipts["fusion_key"]
    return (
        "count=%d,length=%.3fmm,inward=%.3f..%.3fmm,z=%.3f..%.3fmm,"
        "source_vertical_panel=0.000..1.200mm,underlap_z=%.3f..%.3fmm,"
        "max_exposed_deviation=%.3fmm,volume_growth=%.9fmm3"
        % (
            receipt["count"],
            receipt["length"],
            receipt["minimum_inward"],
            receipt["maximum_inward"],
            receipt["minimum_z"],
            receipt["maximum_z"],
            receipt["underlap_minimum_z"],
            receipt["underlap_maximum_z"],
            receipt["maximum_exposed_deviation"],
            receipt["volume_growth"],
        )
    )


def _validate_source_terminal_feature_text(value):
    pattern = re.compile(
        r"^west:topology_extent=([0-9.]+)mm,within_deviation=([0-9.]+)mm,"
        r"after_deviation=([0-9.]+)mm,far_cap_deviation=([0-9.]+)mm$"
    )
    match = pattern.match(value or "")
    if match is None:
        raise ValueError("Source terminal-feature receipt is malformed")
    _assert_close(float(match.group(1)), HUB_SOURCE_TERMINAL_EXTENT, 1.0e-9, "source terminal extent")
    if float(match.group(3)) > 1.0e-5 or float(match.group(4)) > 1.0e-5:
        raise ValueError("Source wall is not uniform immediately after its topology feature band")


def _validate_hub_wall_quality_text(value):
    pattern = re.compile(
        r"^(southwest|southeast|northeast|northwest):length=([0-9.]+)mm,"
        r"panel=([0-9.]+)mm,z=([-0-9.]+)\.\.([-0-9.]+)mm,"
        r"inward=([-0-9.]+)\.\.([-0-9.]+)mm,profile_area=([0-9.]+)mm2,"
        r"volume_deviation=([-0-9.]+)mm3,foot_removed=1$"
    )
    chunks = value.split("|") if value else []
    if len(chunks) != 4:
        raise ValueError("Four-way hub wall-quality receipt is incomplete")
    seen = set()
    for chunk in chunks:
        match = pattern.match(chunk)
        if match is None:
            raise ValueError("Four-way hub wall-quality receipt is malformed")
        seen.add(match.group(1))
        _assert_close(float(match.group(2)), math.sqrt(5000.0), 1.0e-6, "hub diagonal length")
        _assert_close(float(match.group(3)), HUB_PANEL_THICKNESS, 1.0e-6, "hub panel thickness")
        _assert_close(float(match.group(4)), HUB_PANEL_Z[0], 1.0e-6, "hub panel bottom")
        _assert_close(float(match.group(5)), HUB_PANEL_Z[1], 1.0e-6, "hub panel top")
        minimum_inward = float(match.group(6))
        maximum_inward = float(match.group(7))
        if (
            minimum_inward < -0.002
            or maximum_inward > HUB_PANEL_THICKNESS + 0.002
            or maximum_inward < HUB_PANEL_THICKNESS - 0.01
        ):
            raise ValueError("Four-way hub panel receipt includes a reinforcement-foot protrusion")
        _assert_close(float(match.group(8)), HUB_PANEL_PROFILE_AREA, 1.0e-5, "hub panel profile area")
        if abs(float(match.group(9))) > 0.01:
            raise ValueError("Four-way hub panel volume does not match its source-derived profile")
    if seen != {"southwest", "southeast", "northeast", "northwest"}:
        raise ValueError("Four-way hub receipt lacks all four corner walls")


def _validate_hub_source_panel_text(value):
    pattern = re.compile(
        r"^source=reviewed_west_wall_intersection,bounds=([-0-9.,]+),"
        r"profile_area=([0-9.]+)mm2,volume=([0-9.]+)mm3,sloped_foot_removed=1$"
    )
    match = pattern.match(value or "")
    if match is None:
        raise ValueError("Four-way hub source-panel receipt is malformed")
    bounds = tuple(float(item) for item in match.group(1).split(","))
    expected_bounds = (0.0, 0.0, HUB_PANEL_Z[0], HUB_PANEL_THICKNESS, 200.0, HUB_PANEL_Z[1])
    if len(bounds) != len(expected_bounds):
        raise ValueError("Four-way hub source-panel bounds are incomplete")
    for actual, expected in zip(bounds, expected_bounds):
        _assert_close(actual, expected, 1.0e-6, "hub source-panel bound")
    _assert_close(float(match.group(2)), HUB_PANEL_PROFILE_AREA, 1.0e-5, "hub source-panel area")
    _assert_close(
        float(match.group(3)),
        HUB_PANEL_PROFILE_AREA * 200.0,
        0.01,
        "hub source-panel volume",
    )


def _validate_hub_fusion_key_text(value):
    pattern = re.compile(
        r"^count=([0-9]+),length=([0-9.]+)mm,inward=([0-9.]+)\.\.([0-9.]+)mm,"
        r"z=([0-9.]+)\.\.([0-9.]+)mm,source_vertical_panel=0\.000\.\.1\.200mm,"
        r"underlap_z=([0-9.]+)\.\.([0-9.]+)mm,max_exposed_deviation=([0-9.]+)mm,"
        r"volume_growth=([-0-9.]+)mm3$"
    )
    match = pattern.match(value or "")
    if match is None:
        raise ValueError("Four-way hub hidden-fusion-key receipt is malformed")
    if int(match.group(1)) != 4:
        raise ValueError("Four-way hub must contain four hidden fusion keys")
    expected = (
        HUB_FUSION_KEY_LENGTH,
        HUB_FUSION_KEY_INWARD[0],
        HUB_FUSION_KEY_INWARD[1],
        HUB_FUSION_KEY_Z[0],
        HUB_FUSION_KEY_Z[1],
    )
    for actual, target in zip((float(match.group(index)) for index in range(2, 7)), expected):
        _assert_close(actual, target, 1.0e-9, "hub hidden fusion key")
    if float(match.group(4)) > HUB_PANEL_THICKNESS:
        raise ValueError("Four-way hub fusion key exceeds the source vertical panel")
    _assert_close(float(match.group(7)), HUB_CONTACT_UNDERLAP_Z[0], 1.0e-9, "hub underlap bottom")
    _assert_close(float(match.group(8)), HUB_CONTACT_UNDERLAP_Z[1], 1.0e-9, "hub underlap top")
    _assert_close(float(match.group(9)), 0.0, 1.0e-9, "hub panel underlap exposed deviation")
    if abs(float(match.group(10))) > HUB_FUSION_VOLUME_TOLERANCE:
        raise ValueError("Four-way hub fusion key changes the visible solid volume")


def _box(min_x, min_y, min_z, max_x, max_y, max_z):
    return Rhino.Geometry.Brep.CreateFromBox(
        Rhino.Geometry.BoundingBox(
            Rhino.Geometry.Point3d(min_x, min_y, min_z),
            Rhino.Geometry.Point3d(max_x, max_y, max_z),
        )
    )


def _polygon_prism(points_xy, z_min, z_max, name):
    polyline = Rhino.Geometry.Polyline()
    for x, y in points_xy:
        polyline.Add(Rhino.Geometry.Point3d(float(x), float(y), float(z_min)))
    polyline.Add(Rhino.Geometry.Point3d(float(points_xy[0][0]), float(points_xy[0][1]), float(z_min)))
    curve = Rhino.Geometry.PolylineCurve(polyline)
    extrusion = Rhino.Geometry.Extrusion.Create(curve, float(z_max - z_min), True)
    if extrusion is None:
        raise RuntimeError("Could not create %s" % name)
    brep = extrusion.ToBrep()
    bbox = brep.GetBoundingBox(True)
    brep.Transform(Rhino.Geometry.Transform.Translation(0.0, 0.0, z_min - bbox.Min.Z))
    return _validate_brep(brep, name)


def transition_footprint_area():
    doubled = 0.0
    for index, (x1, y1) in enumerate(TRANSITION_FOOTPRINT):
        x2, y2 = TRANSITION_FOOTPRINT[(index + 1) % len(TRANSITION_FOOTPRINT)]
        doubled += x1 * y2 - x2 * y1
    return abs(doubled) / 2.0


def _point_in_transition_footprint(x, y, tolerance=1.0e-5):
    # The footprint is a width-varying corridor with exact 45-degree shoulders.
    if y < -tolerance or y > 200.0 + tolerance:
        return False
    if y <= 75.0:
        minimum_x, maximum_x = 50.0, 250.0
    elif y < 125.0:
        shift = y - 75.0
        minimum_x, maximum_x = 50.0 - shift, 250.0 + shift
    else:
        minimum_x, maximum_x = 0.0, 300.0
    return minimum_x - tolerance <= x <= maximum_x + tolerance


def validate_transition_layout(spec):
    pockets = TRANSITION_PLATFORM["pockets"]
    if pockets != {
        "north": (150.0,),
        "east": (),
        "south": (150.0,),
        "west": (),
    }:
        raise ValueError("Transition must retain exactly one centered north and south pocket")
    if sum(len(pockets[side]) for side in SIDES) != 2:
        raise ValueError("Transition must contain exactly two connector pockets")
    left_vector = (
        TRANSITION_FOOTPRINT[6][0] - TRANSITION_FOOTPRINT[7][0],
        TRANSITION_FOOTPRINT[6][1] - TRANSITION_FOOTPRINT[7][1],
    )
    right_vector = (
        TRANSITION_FOOTPRINT[3][0] - TRANSITION_FOOTPRINT[2][0],
        TRANSITION_FOOTPRINT[3][1] - TRANSITION_FOOTPRINT[2][1],
    )
    if left_vector != (-50.0, 50.0) or right_vector != (50.0, 50.0):
        raise ValueError("Transition shoulder vectors changed from the exact 45-degree layout")
    for vector in (left_vector, right_vector):
        angle = math.degrees(math.atan2(abs(vector[1]), abs(vector[0])))
        _assert_close(angle, 45.0, 1.0e-9, "transition shoulder angle")
    if TRANSITION_FOOTPRINT[1][0] - TRANSITION_FOOTPRINT[0][0] != spec.tile_size:
        raise ValueError("Transition south X1C opening must be exactly 200 mm")
    if TRANSITION_FOOTPRINT[4][0] - TRANSITION_FOOTPRINT[5][0] != 300.0:
        raise ValueError("Transition north H2D opening must be exactly 300 mm")
    south_run = TRANSITION_FOOTPRINT[7][1] - TRANSITION_FOOTPRINT[0][1]
    north_run = TRANSITION_FOOTPRINT[5][1] - TRANSITION_FOOTPRINT[6][1]
    if south_run != 75.0 or north_run != 75.0:
        raise ValueError("Transition straight terminal runs must both remain exactly 75 mm")
    profile = pocket_profile(spec)
    pocket_half_width = profile["inner_width"] / 2.0
    south_wall_clearance = (150.0 - pocket_half_width) - (50.0 + 19.2)
    north_wall_clearance = (150.0 - pocket_half_width) - 19.2
    if south_wall_clearance <= 0.0 or north_wall_clearance <= 0.0:
        raise ValueError("Transition connector pockets overlap the source-profile side walls")
    _assert_close(transition_footprint_area(), 50000.0, 1.0e-6, "transition footprint area")
    return {
        "pocket_count": 2,
        "left_vector": left_vector,
        "right_vector": right_vector,
        "south_run": south_run,
        "north_run": north_run,
        "south_wall_clearance": south_wall_clearance,
        "north_wall_clearance": north_wall_clearance,
    }


def validate_hub_layout(spec):
    if HUB_PLATFORM["pockets"] != {
        "north": (150.0,),
        "east": (150.0,),
        "south": (150.0,),
        "west": (150.0,),
    }:
        raise ValueError("Four-way hub must have one exact centered pocket per side")
    requested_undirected = {
        frozenset(((50.0, 0.0), (0.0, 50.0))),
        frozenset(((250.0, 0.0), (300.0, 50.0))),
        frozenset(((300.0, 250.0), (250.0, 300.0))),
        frozenset(((50.0, 300.0), (0.0, 250.0))),
    }
    actual_undirected = {frozenset(path) for path in HUB_WALL_PATHS.values()}
    if actual_undirected != requested_undirected:
        raise ValueError("Four-way hub diagonal paths changed")
    for corner, path in HUB_WALL_PATHS.items():
        length, direction = _path_frame(path)
        _assert_close(length, math.sqrt(5000.0), 1.0e-9, "%s hub wall length" % corner)
        _assert_close(abs(direction[0]), math.sqrt(0.5), 1.0e-9, "%s hub wall angle" % corner)
        midpoint = ((path[0][0] + path[1][0]) / 2.0, (path[0][1] + path[1][1]) / 2.0)
        clockwise_normal = (direction[1], -direction[0])
        center_vector = (150.0 - midpoint[0], 150.0 - midpoint[1])
        if clockwise_normal[0] * center_vector[0] + clockwise_normal[1] * center_vector[1] <= 0.0:
            raise ValueError("%s hub wall profile does not face the playable center" % corner)
    if spec.tile_size != 200.0:
        raise ValueError("Hub openings require the reviewed 200 mm X1C tile interface")
    return {
        "pocket_count": 4,
        "opening_width": 200.0,
        "wall_count": 4,
        "wall_length": math.sqrt(5000.0),
    }


def _point_in_hub_wall_envelope(x, y, tolerance=0.003):
    for path in HUB_WALL_PATHS.values():
        length, direction = _path_frame(path)
        normal = (direction[1], -direction[0])
        offset = (float(x) - path[0][0], float(y) - path[0][1])
        station = offset[0] * direction[0] + offset[1] * direction[1]
        inward = offset[0] * normal[0] + offset[1] * normal[1]
        if (
            -tolerance <= station <= length + tolerance
            and -tolerance <= inward <= HUB_PANEL_THICKNESS + tolerance
        ):
            return True
    return False


def _validate_hub_stl_clearance(path):
    for x, y, z in _read_stl_vertices(path):
        if z > 10.0 + 1.0e-5 and not _point_in_hub_wall_envelope(x, y):
            raise ValueError(
                "%s protrudes outside the four exact corner-wall envelopes at %.6f, %.6f, %.6f"
                % (os.path.basename(path), x, y, z)
            )


def _validate_transition_stl_footprint(path):
    vertices = _read_stl_vertices(path)
    for x, y, _z in vertices:
        if not _point_in_transition_footprint(x, y, tolerance=0.002):
            raise ValueError(
                "%s contains a vertex outside the exact transition footprint at %.4f, %.4f"
                % (os.path.basename(path), x, y)
            )
    for x, y in TRANSITION_FOOTPRINT:
        if not any(
            abs(vertex[0] - x) <= 0.002
            and abs(vertex[1] - y) <= 0.002
            and abs(vertex[2]) <= 0.002
            for vertex in vertices
        ):
            raise ValueError(
                "%s is missing footprint vertex %.1f, %.1f at Z=0"
                % (os.path.basename(path), x, y)
            )


def _validate_terminal_preservation_text(value):
    pattern = re.compile(r"^(left|right):near=([0-9.]+)mm,far=([0-9.]+)mm$")
    chunks = value.split(";") if value else []
    if len(chunks) != 2:
        raise ValueError("Transition terminal-preservation receipt is incomplete")
    seen = set()
    for chunk in chunks:
        match = pattern.match(chunk)
        if match is None:
            raise ValueError("Transition terminal-preservation receipt is malformed")
        seen.add(match.group(1))
        for text_value in match.groups()[1:]:
            if float(text_value) > TRANSITION_TERMINAL_TOLERANCE:
                raise ValueError("Transition terminal deviation exceeds the reviewed tolerance")
    if seen != {"left", "right"}:
        raise ValueError("Transition terminal-preservation receipt lacks both walls")


def _validate_transition_joint_text(value):
    pattern = re.compile(
        r"^(left|right):stations=([0-9./]+),max_section_deviation=([0-9.]+)mm,"
        r"central_volume_error=([0-9.]+)mm3$"
    )
    chunks = value.split("|") if value else []
    if len(chunks) != 2:
        raise ValueError("Transition sharp-miter joint receipt is incomplete")
    expected_stations = "/".join(
        "%.1f" % station for station in TRANSITION_JOINT_SECTION_STATIONS
    )
    seen = set()
    for chunk in chunks:
        match = pattern.match(chunk)
        if match is None:
            raise ValueError("Transition sharp-miter joint receipt is malformed")
        seen.add(match.group(1))
        if match.group(2) != expected_stations:
            raise ValueError("Transition sharp-miter receipt has wrong audit stations")
        if float(match.group(3)) > TRANSITION_JOINT_TOLERANCE:
            raise ValueError("Transition joint section contains a rib or sliver")
        if float(match.group(4)) > TRANSITION_JOINT_VOLUME_TOLERANCE:
            raise ValueError("Transition joint protrudes beyond its clean sweep envelope")
    if seen != {"left", "right"}:
        raise ValueError("Transition sharp-miter receipt lacks both side walls")


def _build_transition_base(spec, source_cutters):
    base = _polygon_prism(TRANSITION_FOOTPRINT, 0.0, spec.tile_height, "transition footprint base")
    for side in ("south", "north"):
        cutter = _placed_source_cutter(source_cutters[side], TRANSITION_PLATFORM, side, 150.0, spec)
        base = _single_valid_solid(
            Rhino.Geometry.Brep.CreateBooleanDifference(base, cutter, MODEL_TOLERANCE),
            "transition after %s source pocket" % side,
        )
    bounds = _bounds_tuple(base.GetBoundingBox(True))
    expected = (0.0, 0.0, 0.0, 300.0, 200.0, spec.tile_height)
    for index, (actual, target) in enumerate(zip(bounds, expected)):
        _assert_close(actual, target, BOUNDS_TOLERANCE, "transition base bound %d" % index)
    expected_area = 50000.0
    _assert_close(transition_footprint_area(), expected_area, 1.0e-6, "transition footprint area")
    return base


def _trim_wall_to_transition_footprint(wall, name):
    envelope = _polygon_prism(TRANSITION_FOOTPRINT, 9.0, 83.0, "%s footprint envelope" % name)
    pieces = Rhino.Geometry.Brep.CreateBooleanIntersection(wall, envelope, MODEL_TOLERANCE)
    return _single_valid_solid(pieces, "%s footprint-trimmed wall" % name)


def _sweep_transition_middle(source_wall, side):
    if side not in TRANSITION_WALL_PATHS:
        raise ValueError("Unknown transition wall side: %s" % side)
    overlap_half = TRANSITION_SPLICE_OVERLAP / 2.0
    start_y = TRANSITION_TERMINAL_PRESERVE_LENGTH - overlap_half
    end_y = 200.0 - TRANSITION_TERMINAL_PRESERVE_LENGTH + overlap_half
    source_station = TRANSITION_TERMINAL_PRESERVE_LENGTH
    path = TRANSITION_WALL_PATHS[side]
    rail_points = (
        (path[0][0], start_y),
        path[1],
        path[2],
        (path[3][0], end_y),
    )
    section = _section_curve(source_wall, source_station)
    source_outer_x = 0.0 if side == "left" else 200.0
    section.Transform(
        Rhino.Geometry.Transform.Translation(
            rail_points[0][0] - source_outer_x,
            start_y - source_station,
            0.0,
        )
    )
    rail_z = section.GetBoundingBox(True).Min.Z
    polyline = Rhino.Geometry.Polyline()
    for x, y in rail_points:
        polyline.Add(Rhino.Geometry.Point3d(x, y, rail_z))
    rail = Rhino.Geometry.PolylineCurve(polyline)
    sweep = Rhino.Geometry.SweepOneRail()
    sweep.SetToRoadlikeTop()
    sweep.SweepTolerance = MODEL_TOLERANCE
    sweep.AngleToleranceRadians = math.radians(0.10)
    sweep.MiterType = 1
    sweep.ClosedSweep = False
    swept_parts = list(sweep.PerformSweep(rail, section) or ())
    if not swept_parts:
        raise RuntimeError("SweepOneRail failed for transition %s wall" % side)
    joined = Rhino.Geometry.Brep.JoinBreps(swept_parts, MODEL_TOLERANCE)
    if joined is None or len(joined) != 1:
        raise RuntimeError(
            "Transition %s SweepOneRail must join to exactly one middle Brep" % side
        )
    middle = joined[0]
    if not middle.IsSolid:
        middle = middle.CapPlanarHoles(MODEL_TOLERANCE)
    return _validate_brep(middle, "transition %s sharp-miter middle sweep" % side)


def _validate_transition_joint_quality(wall, middle, side):
    maximum_deviation = 0.0
    for station in TRANSITION_JOINT_SECTION_STATIONS:
        actual = _section_curve(wall, station)
        expected = _section_curve(middle, station)
        maximum_deviation = max(maximum_deviation, _curve_max_distance(actual, expected))
    if maximum_deviation > TRANSITION_JOINT_TOLERANCE:
        raise RuntimeError(
            "Transition %s wall has an internal joint rib/sliver (section deviation %.9f mm)"
            % (side, maximum_deviation)
        )
    actual_central = _clip_wall_y(wall, 55.0, 145.0, "transition %s central audit" % side)
    expected_central = _clip_wall_y(
        middle,
        55.0,
        145.0,
        "transition %s expected clean central sweep" % side,
    )
    central_volume_error = abs(abs(actual_central.GetVolume()) - abs(expected_central.GetVolume()))
    if central_volume_error > TRANSITION_JOINT_VOLUME_TOLERANCE:
        raise RuntimeError(
            "Transition %s wall protrudes beyond its clean sweep by %.6f mm3"
            % (side, central_volume_error)
        )
    return {
        "stations": TRANSITION_JOINT_SECTION_STATIONS,
        "maximum_section_deviation": maximum_deviation,
        "central_volume_error": central_volume_error,
    }


def _build_transition_side_wall(source_wall, side, uniformity):
    overlap_half = TRANSITION_SPLICE_OVERLAP / 2.0
    near_limit = TRANSITION_TERMINAL_PRESERVE_LENGTH + overlap_half
    far_limit = 200.0 - TRANSITION_TERMINAL_PRESERVE_LENGTH - overlap_half
    middle = _sweep_transition_middle(source_wall, side)
    if side == "left":
        near = _clip_wall_y(source_wall, -1.0, near_limit, "transition left near terminal")
        near.Transform(Rhino.Geometry.Transform.Translation(50.0, 0.0, 0.0))
        far = _clip_wall_y(source_wall, far_limit, 201.0, "transition left far terminal")
        unioned = _union((near, middle, far), "transition left sharp-miter wall", MODEL_TOLERANCE)
        wall = _trim_wall_to_transition_footprint(unioned, "transition left")
        expected_bounds = (0.0, 0.0, 10.0, 69.2, 200.0, 82.0)
        near_reference = _section_curve(source_wall, 0.001)
        near_target = _section_curve(wall, 0.001)
        near_target.Transform(Rhino.Geometry.Transform.Translation(-50.0, 0.0, 0.0))
        far_reference = _section_curve(source_wall, 199.999)
        far_target = _section_curve(wall, 199.999)
    elif side == "right":
        near = _clip_wall_y(source_wall, -1.0, near_limit, "transition right near terminal")
        near.Transform(Rhino.Geometry.Transform.Translation(50.0, 0.0, 0.0))
        far = _clip_wall_y(source_wall, far_limit, 201.0, "transition right far terminal")
        far.Transform(Rhino.Geometry.Transform.Translation(100.0, 0.0, 0.0))
        unioned = _union((near, middle, far), "transition right sharp-miter wall", MODEL_TOLERANCE)
        wall = _trim_wall_to_transition_footprint(unioned, "transition right")
        expected_bounds = (230.8, 0.0, 10.0, 300.0, 200.0, 82.0)
        near_reference = _section_curve(source_wall, 0.001)
        near_target = _section_curve(wall, 0.001)
        near_target.Transform(Rhino.Geometry.Transform.Translation(-50.0, 0.0, 0.0))
        far_reference = _section_curve(source_wall, 199.999)
        far_target = _section_curve(wall, 199.999)
        far_target.Transform(Rhino.Geometry.Transform.Translation(-100.0, 0.0, 0.0))
    else:
        raise ValueError("Unknown transition wall side: %s" % side)
    bounds = _bounds_tuple(wall.GetBoundingBox(True))
    for index, (actual, target) in enumerate(zip(bounds, expected_bounds)):
        _assert_close(actual, target, 0.01, "transition %s wall bound %d" % (side, index))
    near_deviation = _curve_max_distance(near_target, near_reference)
    far_deviation = _curve_max_distance(far_target, far_reference)
    if near_deviation > TRANSITION_TERMINAL_TOLERANCE:
        raise RuntimeError("Transition %s near source terminal was not preserved" % side)
    if far_deviation > TRANSITION_TERMINAL_TOLERANCE:
        raise RuntimeError("Transition %s far source terminal was not preserved" % side)
    if uniformity["maximum_deviation"] > 1.0e-5:
        raise RuntimeError("Transition %s diagonal used an unverified profile" % side)
    joint_quality = _validate_transition_joint_quality(wall, middle, side)
    return wall, {
        "near_max_deviation": near_deviation,
        "far_max_deviation": far_deviation,
        "joint_quality": joint_quality,
    }


def build_transition_piece(spec, source_cutters, source_walls, uniformity):
    base = _build_transition_base(spec, source_cutters)
    left, left_receipt = _build_transition_side_wall(
        source_walls["west"], "left", uniformity["west"]
    )
    right, right_receipt = _build_transition_side_wall(
        source_walls["east"], "right", uniformity["east"]
    )
    piece = _union((base, left, right), TRANSITION_SPEC["object_name"], MODEL_TOLERANCE)
    _validate_piece(piece, TRANSITION_SPEC, spec)
    return piece, {"left": left_receipt, "right": right_receipt}


def _clip_wall_y(wall, minimum_y, maximum_y, name):
    bbox = wall.GetBoundingBox(True)
    cutter = _box(
        bbox.Min.X - 1.0,
        minimum_y,
        bbox.Min.Z - 1.0,
        bbox.Max.X + 1.0,
        maximum_y,
        bbox.Max.Z + 1.0,
    )
    pieces = Rhino.Geometry.Brep.CreateBooleanIntersection(wall, cutter, MODEL_TOLERANCE)
    return _single_valid_solid(pieces, name)


def _extrude_section(section, start_y, end_y, name):
    curve = section.DuplicateCurve()
    bbox = curve.GetBoundingBox(True)
    curve.Transform(Rhino.Geometry.Transform.Translation(0.0, start_y - bbox.Center.Y, 0.0))
    vector = Rhino.Geometry.Vector3d(0.0, end_y - start_y, 0.0)
    surface = Rhino.Geometry.Surface.CreateExtrusion(curve, vector)
    if surface is None:
        raise RuntimeError("Could not extrude %s" % name)
    brep = surface.ToBrep()
    capped = brep.CapPlanarHoles(MODEL_TOLERANCE)
    return _validate_brep(capped, name)


def _path_frame(path):
    start, end = path
    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)
    if length <= 0.0:
        raise ValueError("Wall path has zero length")
    return length, (delta_x / length, delta_y / length)


def _map_west_wall_geometry_to_path(geometry, path, source_anchor_y, target_distance):
    length, direction = _path_frame(path)
    if target_distance < -MODEL_TOLERANCE or target_distance > length + MODEL_TOLERANCE:
        raise ValueError("Target distance is outside wall path")
    angle = math.atan2(direction[1], direction[0]) - math.pi / 2.0
    rotation = Rhino.Geometry.Transform.Rotation(
        angle,
        Rhino.Geometry.Vector3d.ZAxis,
        Rhino.Geometry.Point3d.Origin,
    )
    if not geometry.Transform(rotation):
        raise RuntimeError("Could not rotate source wall geometry onto hub path")
    anchor = Rhino.Geometry.Point3d(0.0, source_anchor_y, 0.0)
    anchor.Transform(rotation)
    target = Rhino.Geometry.Point3d(
        path[0][0] + direction[0] * target_distance,
        path[0][1] + direction[1] * target_distance,
        0.0,
    )
    if not geometry.Transform(
        Rhino.Geometry.Transform.Translation(
            target.X - anchor.X,
            target.Y - anchor.Y,
            0.0,
        )
    ):
        raise RuntimeError("Could not translate source wall geometry onto hub path")
    return geometry


def _path_section_curve(brep, path, station):
    length, direction = _path_frame(path)
    if station <= 0.0 or station >= length:
        raise ValueError("Path section station must be inside the wall")
    origin = Rhino.Geometry.Point3d(
        path[0][0] + direction[0] * station,
        path[0][1] + direction[1] * station,
        0.0,
    )
    plane = Rhino.Geometry.Plane(
        origin,
        Rhino.Geometry.Vector3d(direction[0], direction[1], 0.0),
    )
    result = Rhino.Geometry.Intersect.Intersection.BrepPlane(brep, plane, MODEL_TOLERANCE)
    if result is None or len(result) < 2 or not result[0]:
        raise RuntimeError("Could not section hub wall at %.6f mm" % station)
    joined = Rhino.Geometry.Curve.JoinCurves(list(result[1]), MODEL_TOLERANCE)
    closed = [curve for curve in joined if curve.IsClosed]
    if len(closed) != 1:
        raise RuntimeError("Hub wall section at %.6f mm must be one closed curve" % station)
    return closed[0]


def _extract_hub_vertical_panel(source_wall):
    source_bounds = source_wall.GetBoundingBox(True)
    cutter = _box(
        source_bounds.Min.X - 1.0,
        source_bounds.Min.Y - 1.0,
        source_bounds.Min.Z - 1.0,
        source_bounds.Min.X + HUB_PANEL_THICKNESS,
        source_bounds.Max.Y + 1.0,
        source_bounds.Max.Z + 1.0,
    )
    panel = _single_valid_solid(
        Rhino.Geometry.Brep.CreateBooleanIntersection(source_wall, cutter, MODEL_TOLERANCE),
        "source-derived hub vertical panel",
    )
    expected_bounds = (
        0.0,
        0.0,
        HUB_PANEL_Z[0],
        HUB_PANEL_THICKNESS,
        200.0,
        HUB_PANEL_Z[1],
    )
    actual_bounds = _bounds_tuple(panel.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, 0.002, "source hub panel bound %d" % index)
    section = _section_curve(panel, 100.0)
    properties = Rhino.Geometry.AreaMassProperties.Compute(section)
    if properties is None:
        raise RuntimeError("Could not measure the source-derived hub panel profile")
    profile_area = abs(properties.Area)
    _assert_close(profile_area, HUB_PANEL_PROFILE_AREA, 1.0e-5, "source hub panel area")
    expected_volume = HUB_PANEL_PROFILE_AREA * 200.0
    volume = abs(panel.GetVolume())
    _assert_close(volume, expected_volume, 0.01, "source hub panel volume")
    return panel, {
        "bounds": actual_bounds,
        "profile_area": profile_area,
        "volume": volume,
    }


def _build_hub_corner_wall(source_panel, corner, panel_proof):
    path = HUB_WALL_PATHS[corner]
    length, direction = _path_frame(path)
    section = _section_curve(source_panel, 100.0)
    _map_west_wall_geometry_to_path(section, path, 100.0, 0.0)
    vector = Rhino.Geometry.Vector3d(
        direction[0] * length,
        direction[1] * length,
        0.0,
    )
    surface = Rhino.Geometry.Surface.CreateExtrusion(section, vector)
    if surface is None:
        raise RuntimeError("Could not extrude source-derived panel for %s hub wall" % corner)
    wall = _validate_brep(
        surface.ToBrep().CapPlanarHoles(MODEL_TOLERANCE),
        "%s hub source-derived vertical panel" % corner,
    )
    inward_distances = []
    for vertex in wall.Vertices:
        point = vertex.Location
        offset_x = point.X - path[0][0]
        offset_y = point.Y - path[0][1]
        inward_distances.append(
            -(direction[0] * offset_y - direction[1] * offset_x)
        )
    minimum_inward = min(inward_distances)
    maximum_inward = max(inward_distances)
    if minimum_inward < -0.002 or maximum_inward > HUB_PANEL_THICKNESS + 0.002:
        raise RuntimeError(
            "%s hub wall retains a sloped reinforcement-foot protrusion" % corner
        )
    bounds = _bounds_tuple(wall.GetBoundingBox(True))
    _assert_close(bounds[2], HUB_PANEL_Z[0], 0.002, "%s hub panel bottom" % corner)
    _assert_close(bounds[5], HUB_PANEL_Z[1], 0.002, "%s hub panel top" % corner)
    actual_profile = _path_section_curve(wall, path, length / 2.0)
    properties = Rhino.Geometry.AreaMassProperties.Compute(actual_profile)
    if properties is None:
        raise RuntimeError("Could not measure %s hub panel profile" % corner)
    profile_area = abs(properties.Area)
    _assert_close(
        profile_area,
        panel_proof["profile_area"],
        1.0e-5,
        "%s source-derived panel area" % corner,
    )
    expected_volume = panel_proof["profile_area"] * length
    volume_deviation = abs(wall.GetVolume()) - expected_volume
    if abs(volume_deviation) > 0.01:
        raise RuntimeError("%s hub panel volume changed from its source profile" % corner)
    return wall, {
        "path": path,
        "length": length,
        "panel_thickness": HUB_PANEL_THICKNESS,
        "minimum_z": bounds[2],
        "maximum_z": bounds[5],
        "minimum_inward": minimum_inward,
        "maximum_inward": maximum_inward,
        "profile_area": profile_area,
        "volume_deviation": volume_deviation,
    }


def _build_hub_fusion_key(path, corner):
    length, direction = _path_frame(path)
    normal = (direction[1], -direction[0])
    station_min = (length - HUB_FUSION_KEY_LENGTH) / 2.0
    station_max = station_min + HUB_FUSION_KEY_LENGTH

    def point(station, inward):
        return (
            path[0][0] + direction[0] * station + normal[0] * inward,
            path[0][1] + direction[1] * station + normal[1] * inward,
        )

    points = (
        point(station_min, HUB_FUSION_KEY_INWARD[0]),
        point(station_max, HUB_FUSION_KEY_INWARD[0]),
        point(station_max, HUB_FUSION_KEY_INWARD[1]),
        point(station_min, HUB_FUSION_KEY_INWARD[1]),
    )
    key = _polygon_prism(
        points,
        HUB_FUSION_KEY_Z[0],
        HUB_FUSION_KEY_Z[1],
        "%s hidden base-wall fusion key" % corner,
    )
    expected_volume = (
        HUB_FUSION_KEY_LENGTH
        * (HUB_FUSION_KEY_INWARD[1] - HUB_FUSION_KEY_INWARD[0])
        * (HUB_FUSION_KEY_Z[1] - HUB_FUSION_KEY_Z[0])
    )
    _assert_close(abs(key.GetVolume()), expected_volume, 1.0e-5, "%s fusion-key volume" % corner)
    return key


def _build_hub_contact_underlap(path, corner):
    length, direction = _path_frame(path)
    normal = (direction[1], -direction[0])

    def point(station, inward):
        return (
            path[0][0] + direction[0] * station + normal[0] * inward,
            path[0][1] + direction[1] * station + normal[1] * inward,
        )

    points = (
        point(0.0, 0.0),
        point(length, 0.0),
        point(length, HUB_PANEL_THICKNESS),
        point(0.0, HUB_PANEL_THICKNESS),
    )
    return _polygon_prism(
        points,
        HUB_CONTACT_UNDERLAP_Z[0],
        HUB_CONTACT_UNDERLAP_Z[1],
        "%s full-footprint hidden contact underlap" % corner,
    )


def build_four_way_hub(spec, source_cutters, source_walls):
    base = _build_platform(HUB_PLATFORM, spec, source_cutters)
    source_panel, panel_proof = _extract_hub_vertical_panel(source_walls["west"])
    piece = base
    wall_receipts = {"source_panel": panel_proof}
    wall_volume = 0.0
    for corner in ("southwest", "southeast", "northeast", "northwest"):
        wall, receipt = _build_hub_corner_wall(source_panel, corner, panel_proof)
        key = _build_hub_fusion_key(HUB_WALL_PATHS[corner], corner)
        key_wall_overlap = list(
            Rhino.Geometry.Brep.CreateBooleanIntersection(wall, key, MODEL_TOLERANCE) or ()
        )
        overlap_volume = sum(
            abs(candidate.GetVolume()) for candidate in key_wall_overlap if candidate.IsSolid
        )
        if overlap_volume <= 0.01:
            raise RuntimeError("%s hidden fusion key does not overlap its source wall" % corner)
        wall_with_key = _union(
            (wall, key),
            "%s %s wall-key fusion" % (HUB_SPEC["object_name"], corner),
            MODEL_TOLERANCE,
        )
        underlap = _build_hub_contact_underlap(HUB_WALL_PATHS[corner], corner)
        wall_with_contact = _union(
            (wall_with_key, underlap),
            "%s %s full-footprint underlap fusion" % (HUB_SPEC["object_name"], corner),
            HUB_CONTACT_BOOLEAN_TOLERANCE,
        )
        piece = _union(
            (piece, wall_with_contact),
            "%s %s wall fusion" % (HUB_SPEC["object_name"], corner),
            HUB_CONTACT_BOOLEAN_TOLERANCE,
        )
        wall_volume += abs(wall.GetVolume())
        wall_receipts[corner] = receipt
    volume_growth = abs(piece.GetVolume()) - (abs(base.GetVolume()) + wall_volume)
    if abs(volume_growth) > HUB_FUSION_VOLUME_TOLERANCE:
        raise RuntimeError("Hub hidden fusion keys change the exterior volume")
    wall_receipts["fusion_key"] = {
        "count": 4,
        "length": HUB_FUSION_KEY_LENGTH,
        "minimum_inward": HUB_FUSION_KEY_INWARD[0],
        "maximum_inward": HUB_FUSION_KEY_INWARD[1],
        "minimum_z": HUB_FUSION_KEY_Z[0],
        "maximum_z": HUB_FUSION_KEY_Z[1],
        "underlap_minimum_z": HUB_CONTACT_UNDERLAP_Z[0],
        "underlap_maximum_z": HUB_CONTACT_UNDERLAP_Z[1],
        "maximum_exposed_deviation": 0.0,
        "volume_growth": volume_growth,
    }
    _validate_piece(piece, HUB_SPEC, spec)
    return piece, wall_receipts


def extend_wall_central_section(source_wall, label, section_receipt):
    split_station = 100.0
    overlap = EXTENSION_OVERLAP
    near = _clip_wall_y(source_wall, -1.0, split_station + overlap, "%s near rigid end" % label)
    far = _clip_wall_y(source_wall, split_station - overlap, 201.0, "%s far rigid end" % label)
    far.Transform(Rhino.Geometry.Transform.Translation(0.0, EXTENSION_AMOUNT, 0.0))
    section = _section_curve(source_wall, split_station)
    filler = _extrude_section(
        section,
        split_station - overlap,
        split_station + EXTENSION_AMOUNT + overlap,
        "%s uniform central extension" % label,
    )
    extended = _union((near, filler, far), "%s 300 mm extended wall" % label, MODEL_TOLERANCE)
    envelope_bbox = source_wall.GetBoundingBox(True)
    envelope = _box(
        envelope_bbox.Min.X,
        0.0,
        envelope_bbox.Min.Z,
        envelope_bbox.Max.X,
        300.0,
        envelope_bbox.Max.Z,
    )
    extended = _single_valid_solid(
        Rhino.Geometry.Brep.CreateBooleanIntersection(extended, envelope, MODEL_TOLERANCE),
        "%s trimmed 300 mm wall" % label,
    )
    expected_bounds = (
        envelope_bbox.Min.X,
        0.0,
        envelope_bbox.Min.Z,
        envelope_bbox.Max.X,
        300.0,
        envelope_bbox.Max.Z,
    )
    actual_bounds = _bounds_tuple(extended.GetBoundingBox(True))
    for index, (actual, expected) in enumerate(zip(actual_bounds, expected_bounds)):
        _assert_close(actual, expected, 0.002, "%s extended bound %d" % (label, index))

    expected_added_volume = section_receipt["area"] * EXTENSION_AMOUNT
    actual_added_volume = abs(extended.GetVolume()) - abs(source_wall.GetVolume())
    _assert_close(
        actual_added_volume,
        expected_added_volume,
        0.10,
        "%s central-extension added volume" % label,
    )
    end_start = _section_curve(extended, 0.001)
    source_start = _section_curve(source_wall, 0.001)
    if _curve_max_distance(end_start, source_start) > 1.0e-5:
        raise RuntimeError("%s near terminal section was not preserved" % label)
    end_far = _section_curve(extended, 299.999)
    end_far.Transform(Rhino.Geometry.Transform.Translation(0.0, -100.0, 0.0))
    source_far = _section_curve(source_wall, 199.999)
    if _curve_max_distance(end_far, source_far) > 1.0e-5:
        raise RuntimeError("%s far terminal section was not rigidly preserved" % label)
    return extended


def _wall_length_set(source_walls, uniformity, length):
    if abs(length - 200.0) <= 1.0e-9:
        return {
            "west": source_walls["west"].DuplicateBrep(),
            "east": source_walls["east"].DuplicateBrep(),
        }
    if abs(length - 300.0) <= 1.0e-9:
        return {
            "west": extend_wall_central_section(source_walls["west"], "west", uniformity["west"]),
            "east": extend_wall_central_section(source_walls["east"], "east", uniformity["east"]),
        }
    raise ValueError("Only reviewed 200 mm and 300 mm wall spans are supported")


def _transform_wall_to_side(source_walls, uniformity, platform, side):
    if side in ("west", "east"):
        walls = _wall_length_set(source_walls, uniformity, platform["height"])
        wall = walls[side]
        if side == "east":
            wall.Transform(Rhino.Geometry.Transform.Translation(platform["width"] - 200.0, 0.0, 0.0))
    elif side == "south":
        walls = _wall_length_set(source_walls, uniformity, platform["width"])
        wall = walls["east"]
        wall.Transform(
            Rhino.Geometry.Transform.Rotation(
                -math.pi / 2.0,
                Rhino.Geometry.Vector3d.ZAxis,
                Rhino.Geometry.Point3d.Origin,
            )
        )
        wall.Transform(Rhino.Geometry.Transform.Translation(0.0, 200.0, 0.0))
    elif side == "north":
        walls = _wall_length_set(source_walls, uniformity, platform["width"])
        wall = walls["west"]
        wall.Transform(
            Rhino.Geometry.Transform.Rotation(
                -math.pi / 2.0,
                Rhino.Geometry.Vector3d.ZAxis,
                Rhino.Geometry.Point3d.Origin,
            )
        )
        wall.Transform(Rhino.Geometry.Transform.Translation(0.0, platform["height"], 0.0))
    else:
        raise ValueError("Unknown side: %s" % side)
    return _validate_oriented_wall(wall, platform, side)


def _validate_oriented_wall(wall, platform, side):
    bounds = _bounds_tuple(wall.GetBoundingBox(True))
    if side == "west":
        expected = (0.0, 0.0, 10.0, 19.2, platform["height"], 82.0)
    elif side == "east":
        expected = (platform["width"] - 19.2, 0.0, 10.0, platform["width"], platform["height"], 82.0)
    elif side == "south":
        expected = (0.0, 0.0, 10.0, platform["width"], 19.2, 82.0)
    else:
        expected = (0.0, platform["height"] - 19.2, 10.0, platform["width"], platform["height"], 82.0)
    for index, (actual, target) in enumerate(zip(bounds, expected)):
        _assert_close(actual, target, 0.002, "%s oriented wall bound %d" % (side, index))
    return _validate_brep(wall, "%s oriented wall" % side)


def build_wall_variants():
    spec = load_reviewed_spec()
    verify_source_receipts()
    validate_all_layouts(spec)
    source_model, source_walls = load_source_walls_rhino()
    _cutter_model, source_cutters = load_source_cutters_rhino()
    uniformity = {
        "west": verify_uniform_central_section(source_walls["west"], "west"),
        "east": verify_uniform_central_section(source_walls["east"], "east"),
    }
    bases = {}
    for platform in PLATFORMS:
        bases[_platform_key(platform)] = _build_platform(platform, spec, source_cutters)
    pieces = {}
    for output_spec in OUTPUT_SPECS:
        platform = output_spec["platform"]
        base = bases[output_spec["platform_key"]].DuplicateBrep()
        if output_spec["closed_sides"]:
            parts = [base]
            for side in output_spec["closed_sides"]:
                parts.append(_transform_wall_to_side(source_walls, uniformity, platform, side))
            piece = _union(parts, output_spec["object_name"], MODEL_TOLERANCE)
        else:
            piece = base
        _validate_piece(piece, output_spec, spec)
        pieces[piece_storage_key(output_spec)] = piece
    transition_piece, transition_receipt = build_transition_piece(
        spec,
        source_cutters,
        source_walls,
        uniformity,
    )
    pieces[piece_storage_key(TRANSITION_SPEC)] = transition_piece
    uniformity["transition"] = transition_receipt
    hub_piece, hub_receipt = build_four_way_hub(
        spec,
        source_cutters,
        source_walls,
    )
    pieces[piece_storage_key(HUB_SPEC)] = hub_piece
    uniformity["hub"] = hub_receipt
    return source_model, pieces, uniformity


def _validate_piece(piece, output_spec, spec):
    _validate_brep(piece, output_spec["object_name"])
    platform = output_spec["platform"]
    expected_height = 82.0 if output_spec["closed_sides"] else spec.tile_height
    expected = (0.0, 0.0, 0.0, platform["width"], platform["height"], expected_height)
    actual = _bounds_tuple(piece.GetBoundingBox(True))
    for index, (value, target) in enumerate(zip(actual, expected)):
        _assert_close(value, target, BOUNDS_TOLERANCE, "%s bound %d" % (output_spec["object_name"], index))
    volume = abs(piece.GetVolume())
    base_area = transition_footprint_area() if output_spec.get("is_transition") else platform["width"] * platform["height"]
    base_max = base_area * spec.tile_height
    # The hub's four intentionally thin panels do not exceed the uncut-base
    # volume after its four connector pockets. build_four_way_hub instead
    # proves fusion against the actual pocketed-base plus panel volumes.
    if output_spec["closed_sides"] and not output_spec.get("is_four_way_hub") and volume <= base_max:
        raise RuntimeError("%s walls are not joined to the base" % output_spec["object_name"])
    if not math.isfinite(volume) or volume <= 0.0:
        raise RuntimeError("%s has invalid volume" % output_spec["object_name"])


def _add_layer(doc, parent_index, name, color):
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    layer.ParentLayerId = doc.Layers[parent_index].Id
    layer.Color = color
    index = doc.Layers.Add(layer)
    if index < 0:
        raise RuntimeError("Could not add Rhino layer %s" % name)
    return index


def _translated_copy(brep, x, y):
    duplicate = brep.DuplicateBrep()
    duplicate.Transform(Rhino.Geometry.Transform.Translation(x, y, 0.0))
    return duplicate


def _add_piece_object(doc, brep, output_spec, layer_index, receipts, uniformity):
    object_id = doc.Objects.AddBrep(brep)
    rhino_object = doc.Objects.FindId(object_id)
    if rhino_object is None:
        raise RuntimeError("Could not add %s to combined Rhino file" % output_spec["object_name"])
    attributes = rhino_object.Attributes
    attributes.Name = output_spec["object_name"]
    attributes.LayerIndex = layer_index
    attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromLayer
    platform = output_spec["platform"]
    attributes.SetUserString("dimensions_mm", "%.1f x %.1f" % (platform["width"], platform["height"]))
    attributes.SetUserString("open_sides", ",".join(output_spec["open_sides"]))
    attributes.SetUserString("closed_wall_sides", ",".join(output_spec["closed_sides"]))
    attributes.SetUserString("pocket_centers_mm", pocket_layout_receipt(platform))
    attributes.SetUserString("source_3dm_sha256", EXPECTED_SOURCE_SHA256)
    attributes.SetUserString("source_params_sha256", receipts["params"])
    attributes.SetUserString("source_bridge_sha256", receipts["source_bridge"])
    attributes.SetUserString("current_connector_sha256", receipts["current_connector"])
    wall_method = wall_method_for_spec(output_spec)
    attributes.SetUserString("wall_extension_method", wall_method)
    attributes.SetUserString("stl_mesh_receipt", STL_MESH_RECEIPT)
    if output_spec.get("is_transition"):
        attributes.SetUserString(
            "footprint_polygon_mm",
            ";".join("%.1f,%.1f" % point for point in TRANSITION_FOOTPRINT),
        )
        attributes.SetUserString("shoulder_vectors_mm", "left=-50,50;right=50,50")
        attributes.SetUserString("shoulder_angles_degrees", "left=45;right=45")
        attributes.SetUserString("terminal_runs_mm", "south=75;north=75")
        attributes.SetUserString(
            "terminal_preservation_receipt",
            transition_terminal_receipt(uniformity["transition"]),
        )
        attributes.SetUserString(
            "joint_quality_receipt",
            transition_joint_receipt(uniformity["transition"]),
        )
    elif output_spec.get("is_four_way_hub"):
        attributes.SetUserString("hub_wall_paths_mm", hub_path_receipt())
        attributes.SetUserString(
            "hub_openings_mm",
            "north=50..250;east=50..250;south=50..250;west=50..250",
        )
        attributes.SetUserString("profile_orientation", HUB_PROFILE_DESCRIPTION)
        attributes.SetUserString(
            "hub_wall_quality_receipt",
            hub_wall_quality_receipt(uniformity["hub"]),
        )
        attributes.SetUserString(
            "hub_source_panel_receipt",
            hub_source_panel_receipt(uniformity["hub"]),
        )
        attributes.SetUserString(
            "hub_hidden_fusion_key_receipt",
            hub_fusion_key_receipt(uniformity["hub"]),
        )
    attributes.SetUserString(
        "wall_uniformity_receipt",
        uniformity_receipt(uniformity["west"]) + ";" + uniformity_receipt(uniformity["east"]),
    )
    bounds = _bounds_tuple(brep.GetBoundingBox(True))
    attributes.SetUserString("verified_trimmed_bounds_mm", ",".join("%.4f" % value for value in bounds))
    if not doc.Objects.ModifyAttributes(object_id, attributes, True):
        raise RuntimeError("Could not set attributes for %s" % output_spec["object_name"])


def _validate_saved_3dm(path, spec, uniformity):
    model = Rhino.FileIO.File3dm.Read(path)
    if model is None or model.Settings.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        raise RuntimeError("Could not reopen combined wall-variant 3dm")
    by_name = {model_object.Attributes.Name: model_object for model_object in model.Objects}
    if len(by_name) != len(ALL_OUTPUT_SPECS):
        raise RuntimeError("Combined wall-variant 3dm must contain exactly twelve objects")
    for output_spec in ALL_OUTPUT_SPECS:
        name = output_spec["object_name"]
        if name not in by_name:
            raise RuntimeError("Combined wall-variant 3dm is missing %s" % name)
        geometry = _validate_brep(by_name[name].Geometry, "saved %s" % name)
        position = combined_position(output_spec)
        platform = output_spec["platform"]
        height = 82.0 if output_spec["closed_sides"] else spec.tile_height
        expected = (
            position[0],
            position[1],
            0.0,
            position[0] + platform["width"],
            position[1] + platform["height"],
            height,
        )
        actual = _bounds_tuple(geometry.GetBoundingBox(True))
        for index, (value, target) in enumerate(zip(actual, expected)):
            _assert_close(value, target, BOUNDS_TOLERANCE, "saved %s bound %d" % (name, index))
        attributes = by_name[name].Attributes
        if attributes.GetUserString("open_sides") != ",".join(output_spec["open_sides"]):
            raise RuntimeError("Saved %s open-side receipt is wrong" % name)
        if (attributes.GetUserString("closed_wall_sides") or "") != ",".join(output_spec["closed_sides"]):
            raise RuntimeError("Saved %s closed-side receipt is wrong" % name)
        expected_method = wall_method_for_spec(output_spec)
        if attributes.GetUserString("wall_extension_method") != expected_method:
            raise RuntimeError("Saved %s extension-method receipt is wrong" % name)
        if attributes.GetUserString("stl_mesh_receipt") != STL_MESH_RECEIPT:
            raise RuntimeError("Saved %s mesh receipt is wrong" % name)
        if output_spec.get("is_transition"):
            expected_transition_receipts = {
                "footprint_polygon_mm": ";".join(
                    "%.1f,%.1f" % point for point in TRANSITION_FOOTPRINT
                ),
                "shoulder_vectors_mm": "left=-50,50;right=50,50",
                "shoulder_angles_degrees": "left=45;right=45",
                "terminal_runs_mm": "south=75;north=75",
                "terminal_preservation_receipt": transition_terminal_receipt(
                    uniformity["transition"]
                ),
                "joint_quality_receipt": transition_joint_receipt(
                    uniformity["transition"]
                ),
            }
            for key, expected_value in expected_transition_receipts.items():
                if attributes.GetUserString(key) != expected_value:
                    raise RuntimeError("Saved transition receipt %s is wrong" % key)
        elif output_spec.get("is_four_way_hub"):
            expected_hub_receipts = {
                "hub_wall_paths_mm": hub_path_receipt(),
                "hub_openings_mm": "north=50..250;east=50..250;south=50..250;west=50..250",
                "profile_orientation": HUB_PROFILE_DESCRIPTION,
                "hub_wall_quality_receipt": hub_wall_quality_receipt(uniformity["hub"]),
                "hub_source_panel_receipt": hub_source_panel_receipt(uniformity["hub"]),
                "hub_hidden_fusion_key_receipt": hub_fusion_key_receipt(uniformity["hub"]),
            }
            for key, expected_value in expected_hub_receipts.items():
                if attributes.GetUserString(key) != expected_value:
                    raise RuntimeError("Saved four-way hub receipt %s is wrong" % key)
    print("REOPENED %s: twelve closed solids with accurate trimmed bounds and receipts" % os.path.basename(path))


def _save_combined(pieces, path, spec, receipts, uniformity):
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is None:
        raise RuntimeError("Could not create headless Rhino output document")
    doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    doc.ModelAbsoluteTolerance = MODEL_TOLERANCE
    doc.ModelAngleToleranceRadians = math.radians(0.25)
    root = Rhino.DocObjects.Layer()
    root.Name = "H2DWallVariants"
    root.Color = _color(95, 105, 120)
    root_index = doc.Layers.Add(root)
    platform_layers = {}
    for platform in PLATFORMS:
        layer = Rhino.DocObjects.Layer()
        layer.Name = _platform_key(platform)
        layer.ParentLayerId = doc.Layers[root_index].Id
        layer.Color = _color(100, 120, 145)
        platform_layers[_platform_key(platform)] = doc.Layers.Add(layer)
    colors = (
        _color(68, 116, 188),
        _color(231, 142, 55),
        _color(76, 156, 109),
        _color(145, 99, 188),
        _color(196, 76, 90),
    )
    for output_spec in OUTPUT_SPECS:
        color = colors[next(index for index, item in enumerate(VARIANT_TYPES) if item["key"] == output_spec["key"])]
        layer_index = _add_layer(
            doc,
            platform_layers[output_spec["platform_key"]],
            output_spec["label"],
            color,
        )
        position = combined_position(output_spec)
        preview = _translated_copy(pieces[piece_storage_key(output_spec)], position[0], position[1])
        _add_piece_object(doc, preview, output_spec, layer_index, receipts, uniformity)
    transition_layer = _add_layer(
        doc,
        root_index,
        TRANSITION_SPEC["label"],
        _color(55, 155, 165),
    )
    transition_position = combined_position(TRANSITION_SPEC)
    transition_preview = _translated_copy(
        pieces[piece_storage_key(TRANSITION_SPEC)],
        transition_position[0],
        transition_position[1],
    )
    _add_piece_object(doc, transition_preview, TRANSITION_SPEC, transition_layer, receipts, uniformity)
    hub_layer = _add_layer(
        doc,
        root_index,
        HUB_SPEC["label"],
        _color(176, 112, 52),
    )
    hub_position = combined_position(HUB_SPEC)
    hub_preview = _translated_copy(
        pieces[piece_storage_key(HUB_SPEC)],
        hub_position[0],
        hub_position[1],
    )
    _add_piece_object(doc, hub_preview, HUB_SPEC, hub_layer, receipts, uniformity)
    doc.Strings.SetString("generator", "scripts/generate_h2d_maze_variants.py")
    doc.Strings.SetString("source_3dm_sha256", EXPECTED_SOURCE_SHA256)
    doc.Strings.SetString("wall_extension_method", EXTENSION_METHOD)
    doc.Strings.SetString("transition_wall_method", TRANSITION_WALL_METHOD)
    doc.Strings.SetString(
        "transition_terminal_preservation_receipt",
        transition_terminal_receipt(uniformity["transition"]),
    )
    doc.Strings.SetString(
        "transition_joint_quality_receipt",
        transition_joint_receipt(uniformity["transition"]),
    )
    doc.Strings.SetString("hub_wall_method", HUB_WALL_METHOD)
    doc.Strings.SetString("hub_wall_paths_mm", hub_path_receipt())
    doc.Strings.SetString(
        "hub_wall_quality_receipt",
        hub_wall_quality_receipt(uniformity["hub"]),
    )
    doc.Strings.SetString(
        "hub_source_panel_receipt",
        hub_source_panel_receipt(uniformity["hub"]),
    )
    doc.Strings.SetString(
        "hub_hidden_fusion_key_receipt",
        hub_fusion_key_receipt(uniformity["hub"]),
    )
    doc.Strings.SetString("stl_mesh_receipt", STL_MESH_RECEIPT)
    doc.Strings.SetString(
        "wall_uniformity_receipt",
        uniformity_receipt(uniformity["west"]) + ";" + uniformity_receipt(uniformity["east"]),
    )
    options = Rhino.FileIO.FileWriteOptions()
    options.SuppressDialogBoxes = True
    options.WriteSelectedObjectsOnly = False
    options.WriteGeometryOnly = False
    if not doc.WriteFile(path, options):
        raise RuntimeError("Could not write combined wall-variant 3dm")
    doc.Dispose()
    _validate_saved_3dm(path, spec, uniformity)


def check_generated_outputs(output_dir=OUTPUT_DIR, require_outputs=False):
    expected_names = {output_spec["filename"] for output_spec in ALL_OUTPUT_SPECS}
    expected_names.add(os.path.basename(OUTPUT_3DM))
    actual_names = set()
    if os.path.isdir(output_dir):
        actual_names = {name for name in os.listdir(output_dir) if not name.startswith(".")}
    missing = expected_names - actual_names
    unexpected = actual_names - expected_names
    if missing:
        if require_outputs or actual_names:
            raise ValueError("Wall-variant output set is incomplete; missing: %s" % ", ".join(sorted(missing)))
        print("OUTPUTS not generated yet; run this script through Rhino 8")
        return []
    if unexpected:
        raise ValueError("Wall-variant output folder has unexpected files: %s" % ", ".join(sorted(unexpected)))
    spec = load_reviewed_spec()
    summaries = []
    for output_spec in ALL_OUTPUT_SPECS:
        path = os.path.join(output_dir, output_spec["filename"])
        triangles, bounds = _read_binary_stl(path)
        if triangles > STL_TRIANGLE_LIMIT:
            raise ValueError(
                "%s has avoidable mesh density: %d triangles exceeds %d"
                % (output_spec["object_name"], triangles, STL_TRIANGLE_LIMIT)
            )
        platform = output_spec["platform"]
        height = 82.0 if output_spec["closed_sides"] else spec.tile_height
        expected = (0.0, 0.0, 0.0, platform["width"], platform["height"], height)
        for index, (value, target) in enumerate(zip(bounds, expected)):
            _assert_close(value, target, BOUNDS_TOLERANCE, "%s STL bound %d" % (output_spec["object_name"], index))
        _validate_stl_pocket_receipt(path, platform, spec)
        if output_spec.get("is_transition"):
            _validate_transition_stl_footprint(path)
        elif output_spec.get("is_four_way_hub"):
            _validate_hub_stl_clearance(path)
        summaries.append((output_spec["object_name"], triangles, bounds))

    try:
        import rhino3dm
    except ImportError as exc:
        raise RuntimeError("Checking combined wall-variant 3dm requires rhino3dm") from exc
    combined_path = os.path.join(output_dir, os.path.basename(OUTPUT_3DM))
    model = rhino3dm.File3dm.Read(combined_path)
    if model is None or model.Settings.ModelUnitSystem != rhino3dm.UnitSystem.Millimeters:
        raise ValueError("Combined wall-variant 3dm is unreadable or not in millimeters")
    document_receipts = dict(model.Strings)
    if document_receipts.get("transition_wall_method") != TRANSITION_WALL_METHOD:
        raise ValueError("Combined wall-variant 3dm document has the wrong transition method")
    _validate_terminal_preservation_text(
        document_receipts.get("transition_terminal_preservation_receipt", "")
    )
    _validate_transition_joint_text(
        document_receipts.get("transition_joint_quality_receipt", "")
    )
    if document_receipts.get("hub_wall_method") != HUB_WALL_METHOD:
        raise ValueError("Combined wall-variant 3dm document has the wrong hub wall method")
    if document_receipts.get("hub_wall_paths_mm") != hub_path_receipt():
        raise ValueError("Combined wall-variant 3dm document has the wrong hub paths")
    _validate_hub_wall_quality_text(
        document_receipts.get("hub_wall_quality_receipt", "")
    )
    _validate_hub_source_panel_text(
        document_receipts.get("hub_source_panel_receipt", "")
    )
    _validate_hub_fusion_key_text(
        document_receipts.get("hub_hidden_fusion_key_receipt", "")
    )
    solids = [model_object for model_object in model.Objects if bool(getattr(model_object.Geometry, "IsSolid", False))]
    if len(solids) != len(ALL_OUTPUT_SPECS):
        raise ValueError("Combined wall-variant 3dm must contain twelve closed solids")
    by_name = {model_object.Attributes.Name: model_object for model_object in solids}
    for output_spec in ALL_OUTPUT_SPECS:
        name = output_spec["object_name"]
        if name not in by_name:
            raise ValueError("Combined wall-variant 3dm is missing %s" % name)
        attributes = by_name[name].Attributes
        expected_receipts = {
            "dimensions_mm": "%.1f x %.1f" % (
                output_spec["platform"]["width"],
                output_spec["platform"]["height"],
            ),
            "open_sides": ",".join(output_spec["open_sides"]),
            "closed_wall_sides": ",".join(output_spec["closed_sides"]),
            "pocket_centers_mm": pocket_layout_receipt(output_spec["platform"]),
            "source_3dm_sha256": EXPECTED_SOURCE_SHA256,
            "source_params_sha256": EXPECTED_PARAMS_SHA256,
            "source_bridge_sha256": EXPECTED_BRIDGE_SHA256,
            "current_connector_sha256": EXPECTED_CURRENT_CONNECTOR_SHA256,
            "wall_extension_method": wall_method_for_spec(output_spec),
            "stl_mesh_receipt": STL_MESH_RECEIPT,
        }
        for key, expected in expected_receipts.items():
            actual_receipt = attributes.GetUserString(key)
            if key == "closed_wall_sides":
                actual_receipt = actual_receipt or ""
            if actual_receipt != expected:
                raise ValueError("Combined wall-variant %s receipt %s is wrong" % (name, key))
        if output_spec.get("is_transition"):
            transition_receipts = {
                "footprint_polygon_mm": ";".join(
                    "%.1f,%.1f" % point for point in TRANSITION_FOOTPRINT
                ),
                "shoulder_vectors_mm": "left=-50,50;right=50,50",
                "shoulder_angles_degrees": "left=45;right=45",
                "terminal_runs_mm": "south=75;north=75",
            }
            for key, expected in transition_receipts.items():
                if attributes.GetUserString(key) != expected:
                    raise ValueError("Combined transition receipt %s is wrong" % key)
            _validate_terminal_preservation_text(
                attributes.GetUserString("terminal_preservation_receipt") or ""
            )
            _validate_transition_joint_text(
                attributes.GetUserString("joint_quality_receipt") or ""
            )
        elif output_spec.get("is_four_way_hub"):
            expected_hub_receipts = {
                "hub_wall_paths_mm": hub_path_receipt(),
                "hub_openings_mm": "north=50..250;east=50..250;south=50..250;west=50..250",
                "profile_orientation": HUB_PROFILE_DESCRIPTION,
            }
            for key, expected in expected_hub_receipts.items():
                if attributes.GetUserString(key) != expected:
                    raise ValueError("Combined four-way hub receipt %s is wrong" % key)
            _validate_hub_wall_quality_text(
                attributes.GetUserString("hub_wall_quality_receipt") or ""
            )
            _validate_hub_source_panel_text(
                attributes.GetUserString("hub_source_panel_receipt") or ""
            )
            _validate_hub_fusion_key_text(
                attributes.GetUserString("hub_hidden_fusion_key_receipt") or ""
            )
        uniformity = attributes.GetUserString("wall_uniformity_receipt") or ""
        if "stations=50,100,150" not in uniformity or "max_deviation=" not in uniformity:
            raise ValueError("Combined wall-variant %s lacks uniformity proof" % name)
        recorded = tuple(float(value) for value in attributes.GetUserString("verified_trimmed_bounds_mm").split(","))
        position = combined_position(output_spec)
        height = 82.0 if output_spec["closed_sides"] else spec.tile_height
        expected = (
            position[0],
            position[1],
            0.0,
            position[0] + output_spec["platform"]["width"],
            position[1] + output_spec["platform"]["height"],
            height,
        )
        for index, (value, target) in enumerate(zip(recorded, expected)):
            _assert_close(value, target, BOUNDS_TOLERANCE, "%s recorded bound %d" % (name, index))
    for name, triangles, bounds in summaries:
        print("OUTPUT OK %-43s triangles=%d bounds=%s" % (name, triangles, _format_bounds(bounds)))
    print("OUTPUT OK %s solids=%d" % (os.path.basename(combined_path), len(solids)))
    return summaries


def check_only(output_dir=OUTPUT_DIR, require_outputs=False):
    receipts = verify_source_receipts()
    walls = inspect_source_walls_external()
    spec = load_reviewed_spec()
    layouts = validate_all_layouts(spec)
    print("SOURCE OK sha256=%s wall_objects=%s" % (EXPECTED_SOURCE_SHA256, ",".join(str(item["index"]) for item in walls)))
    print(
        "INTERFACE OK params=%s tracked_bridge=%s current_connector=%s"
        % (receipts["params"], receipts["source_bridge"], receipts["current_connector"])
    )
    for platform in PLATFORMS:
        key = _platform_key(platform)
        print(
            "BASE OK %s pockets=%d centers=%s"
            % (key, layouts[key]["pocket_count"], pocket_layout_receipt(platform))
        )
    transition_layout = validate_transition_layout(spec)
    print(
        "TRANSITION BASE OK pockets=%d south/north=150 vectors=%s/%s"
        % (
            transition_layout["pocket_count"],
            transition_layout["left_vector"],
            transition_layout["right_vector"],
        )
    )
    hub_layout = validate_hub_layout(spec)
    print(
        "FOUR-WAY HUB OK pockets=%d openings=%.1f walls=%d diagonal=%.9f panel=%.3f z=%.1f..%.1f foot_removed=1"
        % (
            hub_layout["pocket_count"],
            hub_layout["opening_width"],
            hub_layout["wall_count"],
            hub_layout["wall_length"],
            HUB_PANEL_THICKNESS,
            HUB_PANEL_Z[0],
            HUB_PANEL_Z[1],
        )
    )
    print("WALL METHOD %s" % EXTENSION_METHOD)
    print("TRANSITION WALL METHOD %s" % TRANSITION_WALL_METHOD)
    print("FOUR-WAY HUB METHOD %s" % HUB_WALL_METHOD)
    print("STL MESH %s" % STL_MESH_RECEIPT)
    check_generated_outputs(output_dir, require_outputs=require_outputs)


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
        if name == HUB_SPEC["object_name"]:
            mesh.Faces.CullDegenerateFaces()
        mesh.Faces.ConvertQuadsToTriangles()
        if name == HUB_SPEC["object_name"]:
            mesh.Faces.CullDegenerateFaces()
        mesh.Normals.ComputeNormals()
        mesh.Compact()
        for face in mesh.Faces:
            if not face.IsTriangle:
                raise RuntimeError("A non-triangle face remained in %s" % name)
            triangles.append((mesh.Vertices[face.A], mesh.Vertices[face.B], mesh.Vertices[face.C]))
    if not triangles:
        raise RuntimeError("%s mesh contains no triangles" % name)
    if name == HUB_SPEC["object_name"]:
        filtered = []
        culled = 0
        for triangle in triangles:
            quantized = {
                (
                    int(round(float(vertex.X) / 1.0e-5)),
                    int(round(float(vertex.Y) / 1.0e-5)),
                    int(round(float(vertex.Z) / 1.0e-5)),
                )
                for vertex in triangle
            }
            if len(quantized) != 3:
                culled += 1
            else:
                filtered.append(triangle)
        if culled:
            print(
                "MESH CLEANUP %s removed=%d weld-collapsed triangles before strict topology audit"
                % (name, culled)
            )
        triangles = filtered
    return triangles


def generate(output_dir=OUTPUT_DIR):
    if Rhino is None or System is None:
        raise RuntimeError("CAD generation must be run through Rhino 8")
    receipts = verify_source_receipts()
    spec = load_reviewed_spec()
    _source_model, pieces, uniformity = build_wall_variants()
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    validate_transition_layout(spec)
    validate_hub_layout(spec)
    for output_spec in ALL_OUTPUT_SPECS:
        piece = pieces[piece_storage_key(output_spec)]
        triangles = _mesh_stl_triangles(piece, output_spec["object_name"])
        numeric = [
            tuple((float(vertex.X), float(vertex.Y), float(vertex.Z)) for vertex in triangle)
            for triangle in triangles
        ]
        topology = _audit_triangle_topology(numeric, output_spec["object_name"])
        if len(triangles) > STL_TRIANGLE_LIMIT:
            raise RuntimeError(
                "%s meshing produced %d triangles, exceeding the audited limit %d"
                % (output_spec["object_name"], len(triangles), STL_TRIANGLE_LIMIT)
            )
        brep_volume = abs(piece.GetVolume())
        relative_volume_error = abs(topology["signed_volume"] - brep_volume) / brep_volume
        if relative_volume_error > STL_VOLUME_RELATIVE_TOLERANCE:
            raise RuntimeError(
                "%s mesh volume differs from its exact Brep by %.8f relative"
                % (output_spec["object_name"], relative_volume_error)
            )
        path = os.path.join(output_dir, output_spec["filename"])
        _write_binary_stl(path, output_spec["object_name"], triangles)
        _validate_stl_pocket_receipt(path, output_spec["platform"], spec)
        if output_spec.get("is_four_way_hub"):
            _validate_hub_stl_clearance(path)
        print(
            "WROTE %-58s triangles=%d volume=%.1f mm3 volume_error=%.8f bounds=%s"
            % (
                os.path.relpath(path, ROOT_DIR),
                len(triangles),
                topology["signed_volume"],
                relative_volume_error,
                _format_bounds(_bounds_tuple(piece.GetBoundingBox(True))),
            )
        )
    combined_path = os.path.join(output_dir, os.path.basename(OUTPUT_3DM))
    _save_combined(pieces, combined_path, spec, receipts, uniformity)
    print("WROTE %s" % os.path.relpath(combined_path, ROOT_DIR))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate H2D wall-bearing maze variants")
    parser.add_argument("--check", action="store_true", help="verify source receipts and outputs without Rhino")
    parser.add_argument("--require-outputs", action="store_true", help="make --check fail if outputs are missing")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="wall-variant output folder")
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
        transcript_path = "/tmp/gridmaze_h2d_wall_variant_generation.log"
        with open(transcript_path, "w") as transcript:
            try:
                with contextlib.redirect_stdout(transcript), contextlib.redirect_stderr(transcript):
                    main()
                transcript.write("GENERATION OK\n")
            except Exception:
                traceback.print_exc(file=transcript)
                raise
