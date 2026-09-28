import math
import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_challenge_ramp_variants import (
    BASE_TOP_Z,
    CENTRAL_PLATFORM_APPROACH,
    CENTRAL_PLATFORM_NORTH_EDGE,
    CENTRAL_PLATFORM_SOUTH_EDGE,
    CENTRAL_PLATFORM_Z,
    CHALLENGE_PLATFORM,
    DOUBLE_HUMP_APPROACH,
    DOUBLE_HUMP_RUN,
    DOUBLE_HUMP_SLOPE_LENGTH,
    FLAT_TOP_APPROACH,
    FLAT_TOP_NORTH_EDGE,
    FLAT_TOP_SOUTH_EDGE,
    NORTH_RIB_CENTERS,
    OFFSET_NORTH_ANGLE,
    OFFSET_SOUTH_ANGLE,
    OUTPUT_3DM_FILENAME,
    OUTPUT_DIR,
    RAMP_PROFILE_METHOD,
    RAMP_UNDERLAP,
    RAMP_WIDTH,
    RAMP_X_MAX,
    RAMP_X_MIN,
    RIB_COUNT_PER_SLOPE,
    RIB_HEIGHT,
    RIB_METHOD,
    RIB_TRAVEL_WIDTH,
    RIDGE_Z,
    ROUNDED_APPROACH,
    ROUNDED_ARC_LENGTH,
    ROUNDED_CENTER_Y,
    ROUNDED_CENTER_Z,
    ROUNDED_MAX_CHORD_DEVIATION,
    ROUNDED_MAX_FACET_AREA_DEFICIT,
    ROUNDED_METHOD,
    ROUNDED_NORTH_TOE,
    ROUNDED_RADIUS,
    ROUNDED_SOUTH_TOE,
    ROUNDED_TANGENT_NORTH_Y,
    ROUNDED_TANGENT_SOUTH_Y,
    ROUNDED_TANGENT_Z,
    SOUTH_RIB_CENTERS,
    STEP_COUNT,
    STEP_DROP,
    STEP_METHOD,
    STEP_TREAD_RUN,
    VARIANTS,
    VARIANT_BY_KEY,
    WALL_TOP_Z,
    check_generated_outputs,
    combined_position,
    expected_output_names,
    profile_points_receipt,
    surface_contract_receipt,
    validate_common_receipts,
    validate_serialized_profile,
    validate_static_contracts,
)
from generate_30deg_up_down_ramp import (
    EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
    STL_MESH_RECEIPT,
)
from generate_h2d_compatible_platforms import (
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    pocket_layout_receipt,
    verify_source_receipts,
)
from generate_h2d_maze_variants import EXTENSION_METHOD
from generate_maze_piece_variants import EXPECTED_SOURCE_SHA256


class ChallengeRampVariantContractTest(unittest.TestCase):
    def test_exact_twelve_canonical_outputs_and_combined_name(self):
        validate_static_contracts()
        expected_stls = (
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
        self.assertEqual(expected_stls, tuple(variant["filename"] for variant in VARIANTS))
        self.assertEqual("maze_piece_h2d_200x300_challenge_variants_v1.3dm", OUTPUT_3DM_FILENAME)
        self.assertEqual(set(expected_stls) | {OUTPUT_3DM_FILENAME}, expected_output_names())

    def test_reviewed_base_pockets_underlap_and_ramp_corridor_are_exact(self):
        self.assertEqual((200.0, 300.0), (CHALLENGE_PLATFORM["width"], CHALLENGE_PLATFORM["height"]))
        self.assertEqual(
            {"north": (100.0,), "east": (150.0,), "south": (100.0,), "west": (150.0,)},
            CHALLENGE_PLATFORM["pockets"],
        )
        self.assertEqual(
            "north:100.0;east:150.0;south:100.0;west:150.0",
            pocket_layout_receipt(CHALLENGE_PLATFORM),
        )
        self.assertEqual((19.2, 180.8), (RAMP_X_MIN, RAMP_X_MAX))
        self.assertAlmostEqual(161.6, RAMP_WIDTH, places=12)
        self.assertAlmostEqual(0.05, RAMP_UNDERLAP, places=12)
        self.assertEqual((10.0, 82.0, 84.0), (BASE_TOP_Z, WALL_TOP_Z, RIDGE_Z))
        self.assertIn("closed slicer-infill YZ profile", RAMP_PROFILE_METHOD)

    def test_flat_top_double_hump_and_central_platform_contracts(self):
        flat = VARIANT_BY_KEY["flat_top_30mm"]
        self.assertEqual(
            (FLAT_TOP_APPROACH, FLAT_TOP_SOUTH_EDGE, FLAT_TOP_NORTH_EDGE, 300.0 - FLAT_TOP_APPROACH),
            tuple(point[0] for point in flat["points"]),
        )
        self.assertEqual((10.0, 84.0, 84.0, 10.0), tuple(point[1] for point in flat["points"]))
        self.assertAlmostEqual(6.8282402399031, FLAT_TOP_APPROACH, places=12)

        double = VARIANT_BY_KEY["double_hump_30mm_rise"]
        self.assertEqual(6, len(double["points"]))
        self.assertEqual((40.0, 40.0), (double["points"][1][1], double["points"][4][1]))
        self.assertAlmostEqual(51.9615242270663, DOUBLE_HUMP_RUN, places=12)
        self.assertAlmostEqual(60.0, DOUBLE_HUMP_SLOPE_LENGTH, places=12)
        self.assertAlmostEqual(36.0769515458674, DOUBLE_HUMP_APPROACH, places=12)
        self.assertAlmostEqual(20.0, double["points"][3][0] - double["points"][2][0], places=12)

        platform = VARIANT_BY_KEY["central_platform_80mm"]
        self.assertEqual((CENTRAL_PLATFORM_SOUTH_EDGE, CENTRAL_PLATFORM_NORTH_EDGE), (110.0, 190.0))
        self.assertEqual((60.0, 60.0), (platform["points"][1][1], platform["points"][2][1]))
        self.assertAlmostEqual(23.3974596215561, CENTRAL_PLATFORM_APPROACH, places=12)
        self.assertEqual(60.0, CENTRAL_PLATFORM_Z)

    def test_low_hills_have_exact_rises_30_degree_faces_and_symmetric_toes(self):
        for rise in (20.0, 40.0, 60.0):
            variant = VARIANT_BY_KEY["low_hill_%dmm_rise" % int(rise)]
            south, peak, north = variant["points"]
            self.assertEqual((150.0, BASE_TOP_Z + rise), peak)
            self.assertAlmostEqual(south[0], 300.0 - north[0], places=12)
            self.assertAlmostEqual(30.0, math.degrees(math.atan2(rise, peak[0] - south[0])), places=12)
            self.assertEqual(82.0, variant["expected_max_z"])

    def test_offset_ridge_angles_and_wall_modes_are_exact(self):
        offset = VARIANT_BY_KEY["offset_ridge"]
        self.assertEqual(((20.0, 10.0), (100.0, 84.0), (280.0, 10.0)), offset["points"])
        self.assertAlmostEqual(42.76882539196875, OFFSET_SOUTH_ANGLE, places=12)
        self.assertAlmostEqual(22.34810834790941, OFFSET_NORTH_ANGLE, places=12)
        self.assertEqual("west", VARIANT_BY_KEY["single_wall_ridge"]["wall_mode"])
        self.assertEqual("none", VARIANT_BY_KEY["open_sides_ridge"]["wall_mode"])
        for variant in VARIANTS:
            if variant["key"] not in ("single_wall_ridge", "open_sides_ridge"):
                self.assertEqual("full", variant["wall_mode"])

    def test_traction_ribs_are_twelve_exact_symmetric_pinned_stations(self):
        self.assertEqual(6, RIB_COUNT_PER_SLOPE)
        self.assertEqual(6, len(SOUTH_RIB_CENTERS))
        self.assertEqual(6, len(NORTH_RIB_CENTERS))
        for south, north in zip(SOUTH_RIB_CENTERS, reversed(NORTH_RIB_CENTERS)):
            self.assertAlmostEqual(300.0, south + north, places=12)
        self.assertEqual((3.0, 1.5), (RIB_TRAVEL_WIDTH, RIB_HEIGHT))
        self.assertIn("1/7 stations", RIB_METHOD)
        self.assertIn("rib_count_per_slope=6", VARIANT_BY_KEY["traction_ribs"]["profile_receipt"])

    def test_rounded_crest_is_a_true_r15_tangent_contract_without_plateau(self):
        self.assertEqual((150.0, 69.0), (ROUNDED_CENTER_Y, ROUNDED_CENTER_Z))
        self.assertEqual(15.0, ROUNDED_RADIUS)
        self.assertEqual((142.5, 157.5), (ROUNDED_TANGENT_SOUTH_Y, ROUNDED_TANGENT_NORTH_Y))
        self.assertAlmostEqual(81.99038105676658, ROUNDED_TANGENT_Z, places=12)
        self.assertAlmostEqual(17.809002353436213, ROUNDED_SOUTH_TOE, places=12)
        self.assertAlmostEqual(282.1909976465638, ROUNDED_NORTH_TOE, places=12)
        self.assertAlmostEqual(ROUNDED_SOUTH_TOE, ROUNDED_APPROACH, places=12)
        self.assertAlmostEqual(5.0 * math.pi, ROUNDED_ARC_LENGTH, places=12)
        self.assertEqual(0.04, ROUNDED_MAX_CHORD_DEVIATION)
        self.assertLess(ROUNDED_MAX_FACET_AREA_DEFICIT, 2.21)
        self.assertIn("genuine Rhino circular Arc R15", ROUNDED_METHOD)
        self.assertIn("no plateau", ROUNDED_METHOD)

    def test_ten_step_descent_has_exact_treads_drops_and_orientation(self):
        variant = VARIANT_BY_KEY["ramp_up_steps_down"]
        self.assertEqual(10, STEP_COUNT)
        self.assertAlmostEqual(7.4, STEP_DROP, places=12)
        self.assertAlmostEqual(12.81717597600969, STEP_TREAD_RUN, places=12)
        self.assertAlmostEqual(74.0, STEP_COUNT * STEP_DROP, places=12)
        self.assertAlmostEqual(128.1717597600969, STEP_COUNT * STEP_TREAD_RUN, places=12)
        self.assertEqual(22, len(variant["points"]))
        self.assertEqual(21, len(variant["surfaces"]))
        self.assertIn("south exact 30-degree climb", STEP_METHOD)
        self.assertIn("north ten horizontal treads", STEP_METHOD)
        self.assertIn("orientation=smooth_up_south_steps_down_north", variant["profile_receipt"])

    def test_combined_layout_is_nonoverlapping_four_by_three(self):
        self.assertEqual((0.0, 0.0), combined_position(VARIANTS[0]))
        self.assertEqual((690.0, 0.0), combined_position(VARIANTS[3]))
        self.assertEqual((0.0, 330.0), combined_position(VARIANTS[4]))
        self.assertEqual((690.0, 660.0), combined_position(VARIANTS[11]))
        boxes = []
        for variant in VARIANTS:
            x, y = combined_position(variant)
            box = (x, y, x + 200.0, y + 300.0)
            for other in boxes:
                self.assertFalse(
                    min(box[2], other[2]) > max(box[0], other[0])
                    and min(box[3], other[3]) > max(box[1], other[1])
                )
            boxes.append(box)

    def test_source_interface_and_wall_methods_are_fingerprint_pinned(self):
        receipts = verify_source_receipts()
        self.assertEqual(EXPECTED_SOURCE_SHA256, receipts["source_3dm"])
        self.assertEqual(EXPECTED_PARAMS_SHA256, receipts["params"])
        self.assertEqual(EXPECTED_BRIDGE_SHA256, receipts["source_bridge"])
        self.assertEqual(EXPECTED_CURRENT_CONNECTOR_SHA256, receipts["current_connector"])
        self.assertIn("rigid source termini", EXTENSION_METHOD)
        self.assertIn("verified-uniform", EXTENSION_METHOD)

    def test_synthetic_flat_top_surfaces_prove_exact_serialized_areas(self):
        variant = VARIANT_BY_KEY["flat_top_30mm"]
        triangles = []
        for surface in variant["surfaces"]:
            y0, z0 = surface["first"]
            y1, z1 = surface["second"]
            a = (RAMP_X_MIN, y0, z0)
            b = (RAMP_X_MAX, y0, z0)
            c = (RAMP_X_MAX, y1, z1)
            d = (RAMP_X_MIN, y1, z1)
            triangles.extend(((a, b, c), (a, c, d)))
        proof = validate_serialized_profile(tuple(triangles), variant)
        self.assertEqual(3, proof["surface_count"])
        self.assertAlmostEqual(161.6 * 30.0, proof["surfaces"][1]["area"], places=6)
        with self.assertRaisesRegex(ValueError, "surface_01"):
            validate_serialized_profile(tuple(triangles[2:]), variant)

    def test_receipts_reject_profile_or_pocket_drift(self):
        variant = VARIANT_BY_KEY["traction_ribs"]
        receipts = {
            "variant_key": variant["key"],
            "dimensions_mm": "200.0 x 300.0 x 84.0",
            "wall_mode": "full",
            "profile_kind": "sharp",
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
            "wall_uniformity_receipt": (
                "west:stations=50,100,150,max_deviation=0.000000000mm,area=1.0mm2,perimeter=1.0mm;"
                "east:stations=50,100,150,max_deviation=0.000000000mm,area=1.0mm2,perimeter=1.0mm"
            ),
            "stl_mesh_receipt": STL_MESH_RECEIPT,
            "pocket_void_z_mm": "0.000000000..8.000000000",
            "ramp_underlap_z_mm": "9.950000000..10.000000000",
            "pocket_void_vertical_clearance_mm": "1.950000000",
            "pocket_void_boolean_receipt": EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
            "special_method": RIB_METHOD,
            "brep_volume_mm3": "1000.0",
            "stl_signed_volume_mm3": "1000.0",
        }
        validate_common_receipts(receipts, variant)
        drifted = dict(receipts, special_method="six approximate ribs")
        with self.assertRaisesRegex(ValueError, "special_method"):
            validate_common_receipts(drifted, variant)
        refilled = dict(
            receipts,
            pocket_void_boolean_receipt=(
                "north=0.000000000;east=0.100000000;south=0.000000000;west=0.000000000"
            ),
        )
        with self.assertRaisesRegex(ValueError, "pocket_void_boolean_receipt"):
            validate_common_receipts(refilled, variant)


class ChallengeRampVariantArtifactTest(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "challenge-ramp variant outputs have not been generated")
    def test_all_generated_artifacts_pass_external_geometry_topology_and_3dm_readback(self):
        summaries = check_generated_outputs(OUTPUT_DIR, require_outputs=True)
        self.assertEqual(12, len(summaries))
        by_key = {summary["variant"]["key"]: summary for summary in summaries}
        for variant in VARIANTS:
            summary = by_key[variant["key"]]
            self.assertEqual(1, summary["topology"]["component_count"])
            self.assertGreater(summary["topology"]["signed_volume"], 0.0)
            self.assertLessEqual(summary["triangle_count"], 50000)
            self.assertEqual(
                (0.0, 0.0, 0.0, 200.0, 300.0, variant["expected_max_z"]),
                tuple(round(value, 3) for value in summary["bounds"]),
            )
        self.assertEqual(12, by_key["traction_ribs"]["profile_proof"]["rib_count"])
        self.assertEqual(21, by_key["ramp_up_steps_down"]["profile_proof"]["surface_count"])
        rounded = by_key["rounded_crest_r15"]["profile_proof"]
        self.assertLessEqual(rounded["maximum_chord_deviation"], ROUNDED_MAX_CHORD_DEVIATION)
        self.assertGreaterEqual(rounded["station_count"], 5)


if __name__ == "__main__":
    unittest.main()
