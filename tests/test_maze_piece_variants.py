import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SCRIPT_DIR = os.path.join(ROOT_DIR, "scripts")
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from generate_maze_piece_variants import (
    BASE_HEIGHT,
    EXPECTED_TOTAL_HEIGHT,
    EXPECTED_SOURCE_SHA256,
    OUTPUT_DIR,
    SOURCE_PATH,
    TILE_SIZE,
    VARIANTS,
    _audit_triangle_topology,
    _read_binary_stl,
    _sha256,
    check_generated_outputs,
    inspect_source_with_rhino3dm,
)


class MazePieceSourceSelectionTest(unittest.TestCase):
    def test_source_file_matches_reviewed_fingerprint(self):
        self.assertEqual(EXPECTED_SOURCE_SHA256, _sha256(SOURCE_PATH))

    def test_source_geometry_is_identified_by_shape(self):
        selection = inspect_source_with_rhino3dm(SOURCE_PATH)
        full = selection["full"]
        walls = selection["walls"]
        self.assertTrue(full["is_solid"])
        self.assertAlmostEqual(TILE_SIZE, full["x_span"], delta=0.06 * TILE_SIZE)
        self.assertAlmostEqual(TILE_SIZE, full["y_span"], delta=0.06 * TILE_SIZE)
        self.assertAlmostEqual(EXPECTED_TOTAL_HEIGHT, full["z_span"], delta=0.2)
        self.assertEqual(2, len(walls))
        self.assertEqual(walls[0]["long_axis"], walls[1]["long_axis"])
        self.assertAlmostEqual(walls[0]["z_span"], walls[1]["z_span"], delta=0.1)

    def test_canonical_openings_cover_starter_set(self):
        openings = {variant["key"]: variant["open_sides"] for variant in VARIANTS}
        self.assertEqual(("east", "west"), openings["straight"])
        self.assertEqual(("north", "east"), openings["corner"])
        self.assertEqual(("north", "east", "south"), openings["t_junction"])
        self.assertEqual(("north", "east", "south", "west"), openings["cross_junction"])
        self.assertEqual(("north",), openings["end"])

    def test_closed_sides_are_exact_complements(self):
        all_sides = {"north", "east", "south", "west"}
        for variant in VARIANTS:
            self.assertEqual(all_sides - set(variant["open_sides"]), set(variant["closed_sides"]))


class MazePieceArtifactTest(unittest.TestCase):
    def test_topology_audit_accepts_one_closed_positive_tetrahedron(self):
        origin = (0.0, 0.0, 0.0)
        x_axis = (1.0, 0.0, 0.0)
        y_axis = (0.0, 1.0, 0.0)
        z_axis = (0.0, 0.0, 1.0)
        audit = _audit_triangle_topology(
            [
                (origin, y_axis, x_axis),
                (origin, x_axis, z_axis),
                (origin, z_axis, y_axis),
                (x_axis, y_axis, z_axis),
            ],
            "closed fixture",
        )
        self.assertEqual(1, audit["component_count"])
        self.assertAlmostEqual(1.0 / 6.0, audit["signed_volume"])

    def test_topology_audit_rejects_an_open_triangle_soup(self):
        with self.assertRaisesRegex(ValueError, "not a closed manifold"):
            _audit_triangle_topology(
                [((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))],
                "open fixture",
            )

    def test_topology_audit_rejects_a_duplicate_triangle(self):
        triangle = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        with self.assertRaisesRegex(ValueError, "duplicate triangle"):
            _audit_triangle_topology([triangle, triangle], "duplicate fixture")

    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "Rhino variant outputs have not been generated")
    def test_generated_output_set_passes_external_check(self):
        check_generated_outputs(OUTPUT_DIR, require_outputs=True)

    @unittest.skipUnless(os.path.isdir(OUTPUT_DIR), "Rhino variant outputs have not been generated")
    def test_each_stl_uses_canonical_module_coordinates(self):
        for variant in VARIANTS:
            triangles, bounds = _read_binary_stl(os.path.join(OUTPUT_DIR, variant["filename"]))
            self.assertGreater(triangles, 0)
            self.assertAlmostEqual(0.0, bounds[0], delta=0.15)
            self.assertAlmostEqual(0.0, bounds[1], delta=0.15)
            self.assertAlmostEqual(0.0, bounds[2], delta=0.15)
            self.assertAlmostEqual(TILE_SIZE, bounds[3], delta=0.15)
            self.assertAlmostEqual(TILE_SIZE, bounds[4], delta=0.15)
            expected_height = BASE_HEIGHT if not variant["closed_sides"] else EXPECTED_TOTAL_HEIGHT
            self.assertAlmostEqual(expected_height, bounds[5], delta=0.15)


if __name__ == "__main__":
    unittest.main()
