import math
import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_30deg_ramp import (
    ANGLE_DEGREES,
    BASE_TOP_Z,
    EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
    HIGH_SURFACE_Z,
    MAX_ALLOWED_UNDERLAP,
    OBJECT_NAME,
    OUTPUT_DIR,
    POCKET_VOID_TOP_Z,
    POCKET_VOID_VERTICAL_CLEARANCE,
    RAMP_METHOD,
    RAMP_PLATFORM,
    RAMP_RISE,
    RAMP_RUN,
    RAMP_SLOPE_LENGTH,
    RAMP_TOE_Y,
    RAMP_UNDERLAP,
    RAMP_WIDTH,
    RAMP_X_MAX,
    RAMP_X_MIN,
    SOURCE_WALL_BOUNDS,
    SOURCE_WALL_OBJECTS,
    STL_FILENAME,
    STL_MESH_RECEIPT,
    THREEDM_FILENAME,
    WALL_TOP_Z,
    check_generated_outputs,
    exposed_ramp_volume,
    ramp_contract_receipt,
    ramp_surface_z,
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
from generate_maze_piece_variants import EXPECTED_SOURCE_SHA256


class ThirtyDegreeRampContractTest(unittest.TestCase):
    def test_output_names_are_standalone_and_canonical(self):
        self.assertEqual("maze_piece_x1c_200x200_30deg_ramp_v1.stl", STL_FILENAME)
        self.assertEqual("maze_piece_x1c_30deg_ramp_v1.3dm", THREEDM_FILENAME)
        self.assertEqual("maze_piece_x1c_200x200_30deg_ramp_v1", OBJECT_NAME)

    def test_platform_is_exact_x1c_size_with_one_centered_pocket_per_side(self):
        self.assertEqual((200.0, 200.0), (RAMP_PLATFORM["width"], RAMP_PLATFORM["height"]))
        self.assertEqual(
            {
                "north": (100.0,),
                "east": (100.0,),
                "south": (100.0,),
                "west": (100.0,),
            },
            RAMP_PLATFORM["pockets"],
        )
        self.assertEqual(
            "north:100.0;east:100.0;south:100.0;west:100.0",
            pocket_layout_receipt(RAMP_PLATFORM),
        )

    def test_ramp_math_is_exact_and_low_to_high_runs_south_to_north(self):
        validate_static_contract()
        self.assertEqual(30.0, ANGLE_DEGREES)
        self.assertEqual(74.0, RAMP_RISE)
        self.assertAlmostEqual(128.1717597600969, RAMP_RUN, places=12)
        self.assertAlmostEqual(71.8282402399031, RAMP_TOE_Y, places=12)
        self.assertAlmostEqual(148.0, RAMP_SLOPE_LENGTH, places=12)
        self.assertAlmostEqual(30.0, math.degrees(math.atan2(RAMP_RISE, RAMP_RUN)), places=12)
        self.assertAlmostEqual(BASE_TOP_Z, ramp_surface_z(RAMP_TOE_Y), places=12)
        self.assertAlmostEqual(HIGH_SURFACE_Z, ramp_surface_z(200.0), places=12)
        self.assertLess(ramp_surface_z(RAMP_TOE_Y + 1.0), ramp_surface_z(200.0))

    def test_ramp_stays_inside_exact_authored_wall_foot_corridor(self):
        self.assertEqual((19.2, 180.8), (RAMP_X_MIN, RAMP_X_MAX))
        self.assertAlmostEqual(161.6, RAMP_WIDTH)
        self.assertEqual(RAMP_X_MIN, SOURCE_WALL_BOUNDS["west"][3])
        self.assertEqual(RAMP_X_MAX, SOURCE_WALL_BOUNDS["east"][0])
        self.assertEqual(10.0, BASE_TOP_Z)
        self.assertEqual(82.0, WALL_TOP_Z)
        self.assertEqual(84.0, HIGH_SURFACE_Z)
        self.assertGreater(RAMP_UNDERLAP, 0.0)
        self.assertLessEqual(RAMP_UNDERLAP, MAX_ALLOWED_UNDERLAP)
        self.assertEqual(8.0, POCKET_VOID_TOP_Z)
        self.assertAlmostEqual(
            1.95,
            BASE_TOP_Z - RAMP_UNDERLAP - POCKET_VOID_TOP_Z,
            places=12,
        )
        self.assertEqual(1.95, POCKET_VOID_VERTICAL_CLEARANCE)

    def test_exposed_ramp_volume_and_surface_area_are_analytic(self):
        self.assertAlmostEqual(766364.5859575713, exposed_ramp_volume(), places=6)
        self.assertAlmostEqual(23916.8, RAMP_WIDTH * RAMP_SLOPE_LENGTH, places=9)
        self.assertIn("split at sharp profile kinks", RAMP_METHOD)

    def test_source_wall_pair_is_geometry_and_fingerprint_pinned(self):
        records = validate_source_wall_receipts()
        self.assertEqual((13, 14), SOURCE_WALL_OBJECTS)
        self.assertEqual(SOURCE_WALL_OBJECTS, tuple(record["index"] for record in records))
        self.assertEqual(SOURCE_WALL_BOUNDS["west"], tuple(round(value, 6) for value in records[0]["bounds"]))
        self.assertEqual(SOURCE_WALL_BOUNDS["east"], tuple(round(value, 6) for value in records[1]["bounds"]))
        for record in records:
            self.assertEqual(10, record["faces"])
            self.assertEqual(15, record["vertices"])
        receipts = verify_source_receipts()
        self.assertEqual(EXPECTED_SOURCE_SHA256, receipts["source_3dm"])
        self.assertEqual(EXPECTED_PARAMS_SHA256, receipts["params"])
        self.assertEqual(EXPECTED_BRIDGE_SHA256, receipts["source_bridge"])
        self.assertEqual(EXPECTED_CURRENT_CONNECTOR_SHA256, receipts["current_connector"])

    def test_exact_plane_validator_accepts_full_rectangle_and_rejects_a_clipped_strip(self):
        low_west = (RAMP_X_MIN, RAMP_TOE_Y, BASE_TOP_Z)
        low_east = (RAMP_X_MAX, RAMP_TOE_Y, BASE_TOP_Z)
        high_west = (RAMP_X_MIN, 200.0, HIGH_SURFACE_Z)
        high_east = (RAMP_X_MAX, 200.0, HIGH_SURFACE_Z)
        proof = validate_ramp_surface_triangles(
            ((low_west, low_east, high_east), (low_west, high_east, high_west))
        )
        self.assertEqual(2, proof["triangle_count"])
        self.assertAlmostEqual(23916.8, proof["area"], places=6)
        clipped_y = 199.8
        clipped_z = ramp_surface_z(clipped_y)
        with self.assertRaisesRegex(ValueError, "surface area"):
            validate_ramp_surface_triangles(
                (
                    (low_west, low_east, (RAMP_X_MAX, clipped_y, clipped_z)),
                    (low_west, (RAMP_X_MAX, clipped_y, clipped_z), (RAMP_X_MIN, clipped_y, clipped_z)),
                )
            )

    def test_receipts_are_exact_and_reject_angle_drift(self):
        receipts = dict(ramp_contract_receipt())
        receipts.update(
            {
                "ramp_method": RAMP_METHOD,
                "pocket_centers_mm": pocket_layout_receipt(RAMP_PLATFORM),
                "source_3dm_sha256": EXPECTED_SOURCE_SHA256,
                "source_params_sha256": EXPECTED_PARAMS_SHA256,
                "source_bridge_sha256": EXPECTED_BRIDGE_SHA256,
                "current_connector_sha256": EXPECTED_CURRENT_CONNECTOR_SHA256,
                "source_wall_objects": "13,14",
                "source_wall_bounds_mm": "west=0,0,10,19.2,200,82;east=180.8,0,10,200,200,82",
                "stl_mesh_receipt": STL_MESH_RECEIPT,
                "pocket_void_boolean_receipt": EXPECTED_POCKET_VOID_BOOLEAN_RECEIPT,
                "brep_volume_mm3": "1210473.943",
                "stl_signed_volume_mm3": "1210473.940",
            }
        )
        volumes = validate_ramp_receipts(receipts)
        self.assertAlmostEqual(1210473.943, volumes["brep_volume"])
        drifted = dict(receipts)
        drifted["angle_degrees"] = "29.500000000"
        with self.assertRaisesRegex(ValueError, "angle_degrees"):
            validate_ramp_receipts(drifted)
        refilled = dict(receipts)
        refilled["pocket_void_boolean_receipt"] = (
            "north=1.000000000;east=0.000000000;south=0.000000000;west=0.000000000"
        )
        with self.assertRaisesRegex(ValueError, "pocket-void Boolean"):
            validate_ramp_receipts(refilled)


class ThirtyDegreeRampArtifactTest(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "30-degree ramp outputs have not been generated")
    def test_generated_artifacts_pass_external_geometry_and_topology_readback(self):
        summary = check_generated_outputs(OUTPUT_DIR, require_outputs=True)
        self.assertEqual((0.0, 0.0, 0.0, 200.0, 200.0, 84.0), tuple(round(value, 3) for value in summary["bounds"]))
        self.assertEqual(1, summary["topology"]["component_count"])
        self.assertGreater(summary["topology"]["signed_volume"], 0.0)
        self.assertAlmostEqual(23916.8, summary["slope"]["area"], places=2)
        self.assertLessEqual(summary["relative_volume_error"], 5.0e-4)


if __name__ == "__main__":
    unittest.main()
