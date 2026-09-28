import math
import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_30deg_up_down_ramp import (
    ANGLE_DEGREES,
    BASE_TOP_Z,
    CHALLENGE_PLATFORM,
    EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
    EXTENDED_WALL_BOUNDS,
    FLAT_APPROACH_LENGTH,
    MAX_ALLOWED_UNDERLAP,
    NORTH_TOE_Y,
    OBJECT_NAME,
    OUTPUT_DIR,
    POCKET_VOID_TOP_Z,
    POCKET_VOID_VERTICAL_CLEARANCE,
    RAMP_METHOD,
    RAMP_RISE,
    RAMP_RUN,
    RAMP_SLOPE_LENGTH,
    RAMP_UNDERLAP,
    RAMP_WIDTH,
    RAMP_X_MAX,
    RAMP_X_MIN,
    RIDGE_Y,
    RIDGE_Z,
    SOURCE_WALL_BOUNDS,
    SOURCE_WALL_OBJECTS,
    SOUTH_TOE_Y,
    STL_FILENAME,
    STL_MESH_RECEIPT,
    THREEDM_FILENAME,
    WALL_TOP_Z,
    check_generated_outputs,
    exposed_ramp_volume,
    north_surface_z,
    ramp_contract_receipt,
    south_surface_z,
    validate_ramp_receipts,
    validate_ramp_surface_triangles,
    validate_source_wall_receipts,
    validate_static_contract,
)
from generate_h2d_compatible_platforms import (
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    pocket_layout_receipt,
    verify_source_receipts,
)
from generate_h2d_maze_variants import EXTENSION_METHOD, SECTION_STATIONS
from generate_maze_piece_variants import EXPECTED_SOURCE_SHA256


class ThirtyDegreeUpDownRampContractTest(unittest.TestCase):
    def test_output_names_are_canonical_and_share_one_stem(self):
        self.assertEqual("maze_piece_h2d_200x300_30deg_up_down_ramp_v1.stl", STL_FILENAME)
        self.assertEqual("maze_piece_h2d_200x300_30deg_up_down_ramp_v1.3dm", THREEDM_FILENAME)
        self.assertEqual("maze_piece_h2d_200x300_30deg_up_down_ramp_v1", OBJECT_NAME)

    def test_platform_is_reviewed_200x300_with_one_centered_pocket_per_side(self):
        self.assertEqual((200.0, 300.0), (CHALLENGE_PLATFORM["width"], CHALLENGE_PLATFORM["height"]))
        self.assertEqual(
            {
                "north": (100.0,),
                "east": (150.0,),
                "south": (100.0,),
                "west": (150.0,),
            },
            CHALLENGE_PLATFORM["pockets"],
        )
        self.assertEqual(
            "north:100.0;east:150.0;south:100.0;west:150.0",
            pocket_layout_receipt(CHALLENGE_PLATFORM),
        )

    def test_two_slopes_are_exact_and_symmetric_about_center_ridge(self):
        validate_static_contract()
        self.assertEqual(30.0, ANGLE_DEGREES)
        self.assertEqual(74.0, RAMP_RISE)
        self.assertAlmostEqual(128.1717597600969, RAMP_RUN, places=12)
        self.assertAlmostEqual(148.0, RAMP_SLOPE_LENGTH, places=12)
        self.assertAlmostEqual(21.8282402399031, SOUTH_TOE_Y, places=12)
        self.assertAlmostEqual(278.1717597600969, NORTH_TOE_Y, places=12)
        self.assertAlmostEqual(RIDGE_Y - SOUTH_TOE_Y, NORTH_TOE_Y - RIDGE_Y, places=12)
        self.assertAlmostEqual(30.0, math.degrees(math.atan2(RAMP_RISE, RAMP_RUN)), places=12)
        self.assertAlmostEqual(BASE_TOP_Z, south_surface_z(SOUTH_TOE_Y), places=12)
        self.assertAlmostEqual(RIDGE_Z, south_surface_z(RIDGE_Y), places=12)
        self.assertAlmostEqual(RIDGE_Z, north_surface_z(RIDGE_Y), places=12)
        self.assertAlmostEqual(BASE_TOP_Z, north_surface_z(NORTH_TOE_Y), places=12)

    def test_flat_approaches_width_height_and_underlap_are_exact(self):
        self.assertAlmostEqual(FLAT_APPROACH_LENGTH, SOUTH_TOE_Y, places=12)
        self.assertAlmostEqual(FLAT_APPROACH_LENGTH, 300.0 - NORTH_TOE_Y, places=12)
        self.assertEqual((19.2, 180.8), (RAMP_X_MIN, RAMP_X_MAX))
        self.assertAlmostEqual(161.6, RAMP_WIDTH)
        self.assertEqual((10.0, 82.0, 84.0), (BASE_TOP_Z, WALL_TOP_Z, RIDGE_Z))
        self.assertGreater(RAMP_UNDERLAP, 0.0)
        self.assertLessEqual(RAMP_UNDERLAP, MAX_ALLOWED_UNDERLAP)
        self.assertEqual(8.0, POCKET_VOID_TOP_Z)
        self.assertAlmostEqual(1.95, BASE_TOP_Z - RAMP_UNDERLAP - POCKET_VOID_TOP_Z, places=12)
        self.assertEqual(1.95, POCKET_VOID_VERTICAL_CLEARANCE)

    def test_analytic_slope_areas_and_closed_wedge_volume(self):
        self.assertAlmostEqual(23916.8, RAMP_WIDTH * RAMP_SLOPE_LENGTH, places=9)
        self.assertAlmostEqual(47833.6, 2.0 * RAMP_WIDTH * RAMP_SLOPE_LENGTH, places=9)
        self.assertAlmostEqual(1532729.1719151426, exposed_ramp_volume(), places=6)
        self.assertIn("split at every sharp profile kink", RAMP_METHOD)

    def test_source_walls_and_reviewed_central_extension_are_pinned(self):
        records = validate_source_wall_receipts()
        self.assertEqual((13, 14), SOURCE_WALL_OBJECTS)
        self.assertEqual(SOURCE_WALL_OBJECTS, tuple(record["index"] for record in records))
        self.assertEqual(SOURCE_WALL_BOUNDS["west"], tuple(round(value, 6) for value in records[0]["bounds"]))
        self.assertEqual(SOURCE_WALL_BOUNDS["east"], tuple(round(value, 6) for value in records[1]["bounds"]))
        self.assertEqual((0.0, 0.0, 10.0, 19.2, 300.0, 82.0), EXTENDED_WALL_BOUNDS["west"])
        self.assertEqual((180.8, 0.0, 10.0, 200.0, 300.0, 82.0), EXTENDED_WALL_BOUNDS["east"])
        self.assertEqual((50.0, 100.0, 150.0), SECTION_STATIONS)
        self.assertIn("rigid source termini", EXTENSION_METHOD)
        self.assertIn("verified-uniform", EXTENSION_METHOD)
        receipts = verify_source_receipts()
        self.assertEqual(EXPECTED_SOURCE_SHA256, receipts["source_3dm"])
        self.assertEqual(EXPECTED_PARAMS_SHA256, receipts["params"])
        self.assertEqual(EXPECTED_BRIDGE_SHA256, receipts["source_bridge"])
        self.assertEqual(EXPECTED_CURRENT_CONNECTOR_SHA256, receipts["current_connector"])

    def test_serialized_slope_validator_proves_both_full_faces(self):
        sw_toe = (RAMP_X_MIN, SOUTH_TOE_Y, BASE_TOP_Z)
        se_toe = (RAMP_X_MAX, SOUTH_TOE_Y, BASE_TOP_Z)
        west_ridge = (RAMP_X_MIN, RIDGE_Y, RIDGE_Z)
        east_ridge = (RAMP_X_MAX, RIDGE_Y, RIDGE_Z)
        nw_toe = (RAMP_X_MIN, NORTH_TOE_Y, BASE_TOP_Z)
        ne_toe = (RAMP_X_MAX, NORTH_TOE_Y, BASE_TOP_Z)
        proof = validate_ramp_surface_triangles(
            (
                (sw_toe, se_toe, east_ridge),
                (sw_toe, east_ridge, west_ridge),
                (west_ridge, east_ridge, ne_toe),
                (west_ridge, ne_toe, nw_toe),
            )
        )
        self.assertAlmostEqual(23916.8, proof["south"]["area"], places=6)
        self.assertAlmostEqual(23916.8, proof["north"]["area"], places=6)
        self.assertAlmostEqual(47833.6, proof["total_area"], places=6)
        clipped_y = NORTH_TOE_Y - 0.2
        clipped_z = north_surface_z(clipped_y)
        with self.assertRaisesRegex(ValueError, "north serialized slope area"):
            validate_ramp_surface_triangles(
                (
                    (sw_toe, se_toe, east_ridge),
                    (sw_toe, east_ridge, west_ridge),
                    (west_ridge, east_ridge, (RAMP_X_MAX, clipped_y, clipped_z)),
                    (
                        west_ridge,
                        (RAMP_X_MAX, clipped_y, clipped_z),
                        (RAMP_X_MIN, clipped_y, clipped_z),
                    ),
                )
            )

    def test_receipts_reject_slope_drift_and_refilled_pocket(self):
        uniformity = (
            "west:stations=50,100,150,max_deviation=0.000000000mm,area=1.000000000mm2,"
            "perimeter=1.000000000mm;east:stations=50,100,150,max_deviation=0.000000000mm,"
            "area=1.000000000mm2,perimeter=1.000000000mm"
        )
        receipts = dict(ramp_contract_receipt())
        receipts.update(
            {
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
                "wall_uniformity_receipt": uniformity,
                "stl_mesh_receipt": STL_MESH_RECEIPT,
                "pocket_void_boolean_receipt": EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
                "brep_volume_mm3": "2226548.0",
                "stl_signed_volume_mm3": "2226560.0",
            }
        )
        validate_ramp_receipts(receipts)
        drifted = dict(receipts)
        drifted["north_angle_degrees"] = "29.500000000"
        with self.assertRaisesRegex(ValueError, "north_angle_degrees"):
            validate_ramp_receipts(drifted)
        refilled = dict(receipts)
        refilled["pocket_void_boolean_receipt"] = (
            "north=0.000000000;east=1.000000000;south=0.000000000;west=0.000000000"
        )
        with self.assertRaisesRegex(ValueError, "pocket_void_boolean_receipt"):
            validate_ramp_receipts(refilled)


class ThirtyDegreeUpDownRampArtifactTest(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "challenge-ramp outputs have not been generated")
    def test_generated_artifacts_pass_external_geometry_and_topology_readback(self):
        summary = check_generated_outputs(OUTPUT_DIR, require_outputs=True)
        self.assertEqual(
            (0.0, 0.0, 0.0, 200.0, 300.0, 84.0),
            tuple(round(value, 3) for value in summary["bounds"]),
        )
        self.assertEqual(1, summary["topology"]["component_count"])
        self.assertGreater(summary["topology"]["signed_volume"], 0.0)
        self.assertAlmostEqual(23916.8, summary["slopes"]["south"]["area"], places=2)
        self.assertAlmostEqual(23916.8, summary["slopes"]["north"]["area"], places=2)
        self.assertAlmostEqual(47833.6, summary["slopes"]["total_area"], places=2)
        self.assertLessEqual(summary["relative_volume_error"], 5.0e-4)


if __name__ == "__main__":
    unittest.main()
