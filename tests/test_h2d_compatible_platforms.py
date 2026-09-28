import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_h2d_compatible_platforms import (
    CURRENT_CONNECTOR_PATH,
    EXPECTED_BRIDGE_SHA256,
    EXPECTED_CURRENT_CONNECTOR_SHA256,
    EXPECTED_PARAMS_SHA256,
    OUTPUT_DIR,
    PLATFORMS,
    SOURCE_BRIDGE_PATH,
    check_generated_outputs,
    expected_inner_corners,
    load_reviewed_spec,
    load_source_cutters_external,
    pocket_layout_receipt,
    pocket_profile,
    tile_alignment_offsets,
    validate_connector_fit,
    validate_all_layouts,
    verify_source_receipts,
)


class H2DConnectorCompatibilityTest(unittest.TestCase):
    def test_reviewed_source_receipts_are_unchanged(self):
        receipts = verify_source_receipts()
        self.assertEqual(EXPECTED_PARAMS_SHA256, receipts["params"])
        self.assertEqual(EXPECTED_BRIDGE_SHA256, receipts["source_bridge"])
        self.assertEqual(EXPECTED_CURRENT_CONNECTOR_SHA256, receipts["current_connector"])

    def test_connector_profile_is_not_scaled(self):
        spec = load_reviewed_spec()
        profile = pocket_profile(spec)
        self.assertAlmostEqual(50.4, profile["full_span"])
        self.assertAlmostEqual(50.2, profile["inboard_depth"])
        self.assertAlmostEqual(0.2, profile["outer_overrun"])
        self.assertAlmostEqual(22.4, profile["opening_width"])
        self.assertAlmostEqual(46.4, profile["inner_width"])
        self.assertAlmostEqual(8.0, profile["depth"])
        self.assertEqual(2.0, spec.top_skin)
        self.assertEqual(6.0, spec.connector_thickness)

    def test_actual_source_has_one_reusable_cutter_per_side(self):
        cutters = load_source_cutters_external()
        self.assertEqual({"north", "east", "south", "west"}, set(cutters))
        for cutter in cutters.values():
            self.assertAlmostEqual(13870.08, 8.0 * 50.4 * (22.4 + 46.4) / 2.0)
            self.assertAlmostEqual(22.4, cutter["outer_width"])
            self.assertAlmostEqual(46.4, cutter["inner_width"])
            self.assertAlmostEqual(50.4, cutter["full_span"])
            self.assertAlmostEqual(8.0, cutter["depth"])

    def test_both_current_and_tracked_connectors_fit_actual_cutter_envelope(self):
        spec = load_reviewed_spec()
        cutters = load_source_cutters_external()
        tracked = validate_connector_fit(SOURCE_BRIDGE_PATH, "tracked", spec, cutters)
        current = validate_connector_fit(CURRENT_CONNECTOR_PATH, "current", spec, cutters)
        self.assertAlmostEqual(100.0, tracked["length"], places=3)
        self.assertAlmostEqual(46.0, tracked["width"], places=3)
        self.assertAlmostEqual(100.0, current["length"], places=3)
        self.assertAlmostEqual(44.3886, current["width"], places=3)
        self.assertGreaterEqual(tracked["minimum_planar_clearance"], -0.005)
        self.assertGreaterEqual(current["minimum_planar_clearance"], -0.005)
        self.assertAlmostEqual(2.0, current["vertical_clearance"], places=3)

    def test_200x300_layout_matches_requested_centers(self):
        platform = PLATFORMS[0]
        self.assertEqual((200.0, 300.0), (platform["width"], platform["height"]))
        self.assertEqual((100.0,), platform["pockets"]["north"])
        self.assertEqual((100.0,), platform["pockets"]["south"])
        self.assertEqual((150.0,), platform["pockets"]["east"])
        self.assertEqual((150.0,), platform["pockets"]["west"])

    def test_300x300_has_one_centered_pocket_per_side(self):
        platform = PLATFORMS[1]
        self.assertEqual((300.0, 300.0), (platform["width"], platform["height"]))
        for centers in platform["pockets"].values():
            self.assertEqual((150.0,), centers)

    def test_every_pocket_aligns_to_centered_200mm_tile_placements(self):
        spec = load_reviewed_spec()
        for platform in PLATFORMS:
            for side in ("north", "east", "south", "west"):
                edge = platform["width"] if side in ("north", "south") else platform["height"]
                expected = (0.0,) if edge == 200.0 else (50.0,)
                self.assertEqual(expected, tile_alignment_offsets(platform, side, spec))

    def test_pocket_footprints_do_not_overlap(self):
        results = validate_all_layouts(load_reviewed_spec())
        self.assertEqual(4, results["200x300"]["pocket_count"])
        self.assertEqual(4, results["300x300"]["pocket_count"])

    def test_receipts_are_human_readable_and_deterministic(self):
        self.assertEqual(
            "north:100.0;east:150.0;south:100.0;west:150.0",
            pocket_layout_receipt(PLATFORMS[0]),
        )
        self.assertEqual(
            "north:150.0;east:150.0;south:150.0;west:150.0",
            pocket_layout_receipt(PLATFORMS[1]),
        )
        self.assertEqual(8, len(expected_inner_corners(PLATFORMS[0], load_reviewed_spec())))
        self.assertEqual(8, len(expected_inner_corners(PLATFORMS[1], load_reviewed_spec())))


class H2DPlatformArtifactTest(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "H2D platform outputs have not been generated")
    def test_generated_h2d_artifacts_pass_external_readback(self):
        summaries = check_generated_outputs(OUTPUT_DIR, require_outputs=True)
        self.assertEqual(2, len(summaries))


if __name__ == "__main__":
    unittest.main()
