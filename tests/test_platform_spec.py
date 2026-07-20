import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_grid_maze_platform import GridMazePlatformSpec, default_spec, normalize_sides, platform_metrics
from optimize_for_3d_printing import (
    audit_spec,
    build_report,
    generate_candidates,
    score_spec,
    spec_to_dict,
)


class GridMazePlatformSpecTest(unittest.TestCase):
    def test_default_dimensions_match_requested_platform(self):
        spec = default_spec()
        self.assertEqual(200.0, spec.tile_size)
        self.assertEqual(10.0, spec.tile_height)
        self.assertEqual(8.0, spec.pocket_depth)
        self.assertEqual(2.0, spec.top_skin)
        self.assertEqual(("north", "south", "east", "west"), spec.enabled_sides)

    def test_pocket_centers_are_symmetric(self):
        spec = default_spec()
        metrics = platform_metrics(spec)
        self.assertEqual((100.0, 25.0), metrics["south_pocket_center"])
        self.assertEqual((100.0, 175.0), metrics["north_pocket_center"])
        self.assertEqual((25.0, 100.0), metrics["west_pocket_center"])
        self.assertEqual((175.0, 100.0), metrics["east_pocket_center"])

    def test_bridge_spacing_matches_adjacent_tiles(self):
        spec = default_spec()
        metrics = platform_metrics(spec)
        self.assertEqual(100.0, metrics["bridge_length"])
        self.assertEqual(46.0, metrics["bridge_width"])
        self.assertEqual(6.0, spec.connector_thickness)

    def test_flat_dovetail_has_no_overhang_stack(self):
        spec = default_spec()
        metrics = platform_metrics(spec)
        self.assertEqual(50.0, metrics["dovetail_length"])
        self.assertLess(spec.connector_thickness, spec.pocket_depth)

    def test_board_cutter_includes_board_layout(self):
        spec = default_spec()
        metrics = platform_metrics(spec)
        self.assertEqual(200.4, metrics["board_cutter_width"])
        self.assertEqual(200.4, metrics["board_cutter_height"])
        self.assertEqual(8.0, metrics["board_cutter_depth"])
        self.assertEqual(("north", "south", "east", "west"), metrics["enabled_sides"])

    def test_side_selection_is_canonical_and_deduplicated(self):
        self.assertEqual(("north", "east"), normalize_sides("east,north,east"))
        spec = GridMazePlatformSpec(enabled_sides=["west", "south"]).validate()
        self.assertEqual(("south", "west"), spec.enabled_sides)

    def test_invalid_side_selection_is_rejected(self):
        with self.assertRaises(ValueError):
            GridMazePlatformSpec(enabled_sides=["north", "up"]).validate()

    def test_invalid_top_skin_is_rejected(self):
        with self.assertRaises(ValueError):
            GridMazePlatformSpec(top_skin=3.0).validate()

    def test_connector_too_thick_is_rejected(self):
        with self.assertRaises(ValueError):
            GridMazePlatformSpec(connector_thickness=8.1).validate()


class PrintOptimizationTest(unittest.TestCase):
    def test_tight_profile_keeps_requested_clearance(self):
        candidates = generate_candidates(default_spec(), "tight")
        self.assertGreater(len(candidates), 0)
        self.assertEqual(0.2, candidates[0].spec.pocket_clearance)

    def test_balanced_profile_prefers_more_forgiving_clearance(self):
        candidates = generate_candidates(default_spec(), "balanced")
        self.assertGreater(len(candidates), 0)
        self.assertEqual(0.25, candidates[0].spec.pocket_clearance)
        self.assertLessEqual(candidates[0].spec.dovetail_tail_width, default_spec().dovetail_tail_width)

    def test_audit_flags_current_clearance_for_review(self):
        checks = audit_spec(default_spec())
        self.assertIn(("review", "pocket clearance is 0.20 mm per side"), checks)

    def test_report_names_baseline_and_recommendation(self):
        spec = default_spec()
        candidates = generate_candidates(spec, "balanced")
        report = build_report(spec, "balanced", candidates, 3)
        self.assertIn("## Baseline", report)
        self.assertIn("## Recommended Variant", report)
        self.assertIn("0.25 mm", report)

    def test_scoring_warns_about_tight_clearance(self):
        _score, _summary, warnings = score_spec(default_spec(), "balanced")
        self.assertTrue(any("0.20 mm clearance" in warning for warning in warnings))

    def test_spec_to_dict_serializes_enabled_sides_as_list(self):
        data = spec_to_dict(default_spec())
        self.assertEqual(["north", "south", "east", "west"], data["enabled_sides"])


if __name__ == "__main__":
    unittest.main()
