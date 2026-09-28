import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_h2d_maze_variants import (
    ALL_OUTPUT_SPECS,
    EXTENSION_AMOUNT,
    EXTENSION_METHOD,
    HUB_FUSION_KEY_INWARD,
    HUB_FUSION_KEY_LENGTH,
    HUB_FUSION_KEY_Z,
    HUB_PANEL_PROFILE_AREA,
    HUB_PANEL_THICKNESS,
    HUB_PANEL_Z,
    HUB_PLATFORM,
    HUB_PROFILE_DESCRIPTION,
    HUB_SOURCE_TERMINAL_EXTENT,
    HUB_SPEC,
    HUB_WALL_METHOD,
    HUB_WALL_PATHS,
    OUTPUT_DIR,
    OUTPUT_SPECS,
    SECTION_STATIONS,
    STL_MESH_MAXIMUM_EDGE,
    STL_MESH_RECEIPT,
    STL_MESH_TOLERANCE,
    STL_TRIANGLE_LIMIT,
    TRANSITION_FOOTPRINT,
    TRANSITION_JOINT_SECTION_STATIONS,
    TRANSITION_JOINT_TOLERANCE,
    TRANSITION_JOINT_VOLUME_TOLERANCE,
    TRANSITION_PLATFORM,
    TRANSITION_SPLICE_OVERLAP,
    TRANSITION_SPEC,
    TRANSITION_TERMINAL_PRESERVE_LENGTH,
    TRANSITION_WALL_PATHS,
    TRANSITION_WALL_METHOD,
    VARIANT_TYPES,
    check_generated_outputs,
    combined_position,
    inspect_source_walls_external,
    load_reviewed_spec,
    transition_footprint_area,
    source_terminal_feature_extent_external,
    validate_hub_layout,
    validate_transition_layout,
    _validate_hub_fusion_key_text,
    _validate_hub_source_panel_text,
    _validate_hub_wall_quality_text,
    _point_in_hub_wall_envelope,
    _validate_transition_joint_text,
)


class H2DMazeVariantContractTest(unittest.TestCase):
    def test_ten_rectangular_transition_and_four_way_hub_stl_names(self):
        rectangular_filenames = [output_spec["filename"] for output_spec in OUTPUT_SPECS]
        filenames = [output_spec["filename"] for output_spec in ALL_OUTPUT_SPECS]
        self.assertEqual(10, len(rectangular_filenames))
        self.assertEqual(12, len(filenames))
        self.assertEqual(12, len(set(filenames)))
        for size in ("200x300", "300x300"):
            for variant in ("straight", "corner", "t_junction", "cross_junction", "end"):
                self.assertIn("maze_piece_h2d_%s_%s_v1.stl" % (size, variant), filenames)
        self.assertEqual("maze_piece_h2d_45deg_transition_v1.stl", TRANSITION_SPEC["filename"])
        self.assertEqual(
            "maze_piece_h2d_300x300_45deg_four_way_v1.stl",
            HUB_SPEC["filename"],
        )

    def test_variant_open_and_closed_side_contracts(self):
        by_key = {variant["key"]: variant for variant in VARIANT_TYPES}
        self.assertEqual(("east", "west"), by_key["straight"]["closed_sides"])
        self.assertEqual(("south", "west"), by_key["corner"]["closed_sides"])
        self.assertEqual(("west",), by_key["t_junction"]["closed_sides"])
        self.assertEqual((), by_key["cross_junction"]["closed_sides"])
        self.assertEqual(("east", "south", "west"), by_key["end"]["closed_sides"])
        all_sides = {"north", "east", "south", "west"}
        for variant in VARIANT_TYPES:
            self.assertEqual(all_sides - set(variant["open_sides"]), set(variant["closed_sides"]))

    def test_corrected_base_has_four_centered_pockets(self):
        platform_receipts = {
            output_spec["platform_key"]: output_spec["platform"]["pockets"] for output_spec in OUTPUT_SPECS
        }
        self.assertEqual(
            {"north": (100.0,), "east": (150.0,), "south": (100.0,), "west": (150.0,)},
            platform_receipts["200x300"],
        )
        self.assertEqual(
            {"north": (150.0,), "east": (150.0,), "south": (150.0,), "west": (150.0,)},
            platform_receipts["300x300"],
        )

    def test_source_wall_pair_and_terminal_topology_are_pinned(self):
        walls = inspect_source_walls_external()
        self.assertEqual(2, len(walls))
        self.assertEqual((13, 14), tuple(wall["index"] for wall in walls))
        for wall in walls:
            self.assertEqual(10, wall["faces"])
            self.assertEqual(15, wall["vertices"])
            self.assertAlmostEqual(200.0, wall["bounds"][4] - wall["bounds"][1])
            self.assertAlmostEqual(72.0, wall["bounds"][5] - wall["bounds"][2])
            self.assertEqual((0.0, 1.2, 200.0), wall["longitudinal_stations"])
        self.assertEqual(1.2, source_terminal_feature_extent_external())

    def test_extension_contract_is_central_and_rigid(self):
        self.assertEqual((50.0, 100.0, 150.0), SECTION_STATIONS)
        self.assertEqual(100.0, EXTENSION_AMOUNT)
        self.assertIn("rigid source termini", EXTENSION_METHOD)
        self.assertIn("translate far source half +100 mm", EXTENSION_METHOD)
        self.assertIn("extrude exact verified-uniform", EXTENSION_METHOD)

    def test_transition_footprint_pockets_and_shoulders_are_exact(self):
        receipt = validate_transition_layout(load_reviewed_spec())
        self.assertEqual(2, receipt["pocket_count"])
        self.assertEqual((-50.0, 50.0), receipt["left_vector"])
        self.assertEqual((50.0, 50.0), receipt["right_vector"])
        self.assertEqual(75.0, receipt["south_run"])
        self.assertEqual(75.0, receipt["north_run"])
        self.assertGreater(receipt["south_wall_clearance"], 50.0)
        self.assertGreater(receipt["north_wall_clearance"], 100.0)
        self.assertEqual(50000.0, transition_footprint_area())
        self.assertEqual(
            {
                "north": (150.0,),
                "east": (),
                "south": (150.0,),
                "west": (),
            },
            TRANSITION_PLATFORM["pockets"],
        )
        self.assertEqual((50.0, 0.0), TRANSITION_FOOTPRINT[0])
        self.assertEqual((250.0, 0.0), TRANSITION_FOOTPRINT[1])
        self.assertEqual((300.0, 200.0), TRANSITION_FOOTPRINT[4])
        self.assertEqual((0.0, 200.0), TRANSITION_FOOTPRINT[5])
        self.assertEqual(
            ((50.0, 0.0), (50.0, 75.0), (0.0, 125.0), (0.0, 200.0)),
            TRANSITION_WALL_PATHS["left"],
        )
        self.assertEqual(
            ((250.0, 0.0), (250.0, 75.0), (300.0, 125.0), (300.0, 200.0)),
            TRANSITION_WALL_PATHS["right"],
        )
        self.assertIn("rotated +45/-45 degree", TRANSITION_WALL_METHOD)

    def test_transition_uses_sharp_miter_sweep_without_broad_joint_overlap(self):
        self.assertEqual(50.0, TRANSITION_TERMINAL_PRESERVE_LENGTH)
        self.assertEqual(0.10, TRANSITION_SPLICE_OVERLAP)
        self.assertEqual((74.9, 75.1, 90.0, 110.0, 124.9, 125.1), TRANSITION_JOINT_SECTION_STATIONS)
        self.assertLessEqual(TRANSITION_JOINT_TOLERANCE, 1.0e-5)
        self.assertLessEqual(TRANSITION_JOINT_VOLUME_TOLERANCE, 0.05)
        self.assertIn("SweepOneRail MiterType=1", TRANSITION_WALL_METHOD)
        self.assertIn("sharp surface-intersection miters", TRANSITION_WALL_METHOD)
        self.assertIn("0.10 mm collinear terminal splices", TRANSITION_WALL_METHOD)
        self.assertNotIn("20 mm miter-overlap", TRANSITION_WALL_METHOD)

    def test_transition_joint_receipt_rejects_a_rib_or_sliver(self):
        stations = "74.9/75.1/90.0/110.0/124.9/125.1"
        good_side = (
            "{side}:stations=%s,max_section_deviation=0.000000000mm,"
            "central_volume_error=0.000000000mm3" % stations
        )
        _validate_transition_joint_text(
            good_side.format(side="left") + "|" + good_side.format(side="right")
        )
        bad_side = (
            "left:stations=%s,max_section_deviation=0.100000000mm,"
            "central_volume_error=0.000000000mm3" % stations
        )
        with self.assertRaisesRegex(ValueError, "rib or sliver"):
            _validate_transition_joint_text(
                bad_side + "|" + good_side.format(side="right")
            )

    def test_four_way_hub_layout_and_source_panel_contract(self):
        receipt = validate_hub_layout(load_reviewed_spec())
        self.assertEqual(4, receipt["pocket_count"])
        self.assertEqual(4, receipt["wall_count"])
        self.assertEqual(200.0, receipt["opening_width"])
        self.assertAlmostEqual(70.71067811865476, receipt["wall_length"])
        self.assertEqual(
            {"north": (150.0,), "east": (150.0,), "south": (150.0,), "west": (150.0,)},
            HUB_PLATFORM["pockets"],
        )
        expected_paths = {
            frozenset(((50.0, 0.0), (0.0, 50.0))),
            frozenset(((250.0, 0.0), (300.0, 50.0))),
            frozenset(((300.0, 250.0), (250.0, 300.0))),
            frozenset(((50.0, 300.0), (0.0, 250.0))),
        }
        self.assertEqual(expected_paths, {frozenset(path) for path in HUB_WALL_PATHS.values()})
        self.assertEqual(1.2, HUB_SOURCE_TERMINAL_EXTENT)
        self.assertEqual(1.2, HUB_PANEL_THICKNESS)
        self.assertEqual((10.0, 82.0), HUB_PANEL_Z)
        self.assertAlmostEqual(86.4, HUB_PANEL_PROFILE_AREA)
        self.assertIn("sloped reinforcement foot intentionally omitted", HUB_WALL_METHOD)
        self.assertIn("sloped reinforcement foot removed", HUB_PROFILE_DESCRIPTION)
        self.assertEqual(10.0, HUB_FUSION_KEY_LENGTH)
        self.assertEqual((0.10, 1.00), HUB_FUSION_KEY_INWARD)
        self.assertEqual((9.90, 10.10), HUB_FUSION_KEY_Z)
        self.assertIn("within the 1.2 mm panel", HUB_WALL_METHOD)
        self.assertIn("no scaling", HUB_WALL_METHOD)

    def test_four_way_hub_source_panel_receipt_requires_the_foot_to_be_removed(self):
        good = (
            "source=reviewed_west_wall_intersection,bounds=0.000,0.000,10.000,1.200,200.000,82.000,"
            "profile_area=86.400000000mm2,volume=17280.000000000mm3,sloped_foot_removed=1"
        )
        _validate_hub_source_panel_text(good)
        with self.assertRaisesRegex(ValueError, "malformed"):
            _validate_hub_source_panel_text(good.replace("sloped_foot_removed=1", "sloped_foot_removed=0"))

    def test_four_way_hub_hidden_fusion_key_receipt_is_bounded_and_volume_neutral(self):
        good = (
            "count=4,length=10.000mm,inward=0.100..1.000mm,z=9.900..10.100mm,"
            "source_vertical_panel=0.000..1.200mm,underlap_z=9.900..10.001mm,"
            "max_exposed_deviation=0.000mm,volume_growth=0.000000000mm3"
        )
        _validate_hub_fusion_key_text(good)
        with self.assertRaisesRegex(ValueError, "hidden fusion key"):
            _validate_hub_fusion_key_text(good.replace("1.000mm", "1.300mm"))
        with self.assertRaisesRegex(ValueError, "exposed deviation"):
            _validate_hub_fusion_key_text(
                good.replace("max_exposed_deviation=0.000mm", "max_exposed_deviation=0.001mm")
            )
        with self.assertRaisesRegex(ValueError, "visible solid volume"):
            _validate_hub_fusion_key_text(good.replace("0.000000000mm3", "0.200000000mm3"))

    def test_four_way_hub_receipt_rejects_profile_protrusion(self):
        good = (
            "{corner}:length=70.710678119mm,panel=1.200000000mm,"
            "z=10.000000000..82.000000000mm,inward=0.000000000..1.200000000mm,"
            "profile_area=86.400000000mm2,volume_deviation=0.000000000mm3,foot_removed=1"
        )
        corners = ("southwest", "southeast", "northeast", "northwest")
        _validate_hub_wall_quality_text("|".join(good.format(corner=corner) for corner in corners))
        bad = good.format(corner="southwest").replace(
            "inward=0.000000000..1.200000000mm",
            "inward=0.000000000..19.200000000mm",
        )
        with self.assertRaisesRegex(ValueError, "reinforcement-foot protrusion"):
            _validate_hub_wall_quality_text(
                "|".join([bad] + [good.format(corner=corner) for corner in corners[1:]])
            )

    def test_four_way_hub_corner_envelopes_exclude_the_central_junction(self):
        self.assertTrue(_point_in_hub_wall_envelope(25.0, 25.0))
        self.assertTrue(_point_in_hub_wall_envelope(275.0, 25.0))
        self.assertTrue(_point_in_hub_wall_envelope(275.0, 275.0))
        self.assertTrue(_point_in_hub_wall_envelope(25.0, 275.0))
        self.assertTrue(_point_in_hub_wall_envelope(25.5, 25.5))
        self.assertFalse(_point_in_hub_wall_envelope(26.0, 26.0))
        self.assertFalse(_point_in_hub_wall_envelope(150.0, 150.0))
        self.assertFalse(_point_in_hub_wall_envelope(50.0, 50.0))

    def test_stl_meshing_is_tolerance_bound_and_density_limited(self):
        self.assertLessEqual(STL_MESH_TOLERANCE, 0.05)
        self.assertEqual(8.0, STL_MESH_MAXIMUM_EDGE)
        self.assertLessEqual(STL_TRIANGLE_LIMIT, 50000)
        self.assertIn("tolerance=0.040 mm", STL_MESH_RECEIPT)
        self.assertIn("hub-only Rhino degenerate-face cull", STL_MESH_RECEIPT)
        self.assertIn("volume relative error<=0.000500", STL_MESH_RECEIPT)

    def test_combined_layout_positions_do_not_overlap(self):
        rectangles = []
        for output_spec in ALL_OUTPUT_SPECS:
            x, y = combined_position(output_spec)
            rectangles.append(
                (
                    output_spec["object_name"],
                    x,
                    y,
                    x + output_spec["platform"]["width"],
                    y + output_spec["platform"]["height"],
                )
            )
        for index, first in enumerate(rectangles):
            for second in rectangles[index + 1 :]:
                overlap_x = min(first[3], second[3]) - max(first[1], second[1])
                overlap_y = min(first[4], second[4]) - max(first[2], second[2])
                self.assertFalse(overlap_x > 0.0 and overlap_y > 0.0, (first[0], second[0]))


class H2DMazeVariantArtifactTest(unittest.TestCase):
    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "H2D wall-variant outputs have not been generated")
    def test_generated_artifacts_pass_external_readback(self):
        summaries = check_generated_outputs(OUTPUT_DIR, require_outputs=True)
        self.assertEqual(12, len(summaries))


if __name__ == "__main__":
    unittest.main()
