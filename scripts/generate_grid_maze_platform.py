from __future__ import print_function

import argparse
import json
import math
import os
import struct
import sys
import tempfile


try:
    import Rhino
    import scriptcontext as sc
    import System
except ImportError:
    Rhino = None
    sc = None
    System = None


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
PARAMS_PATH = os.path.join(ROOT_DIR, "params", "maze_platform_v1.json")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output")
OUTPUT_3DM = os.path.join(OUTPUT_DIR, "grid_maze_platform_10mm_v1.3dm")
TILE_STL = os.path.join(OUTPUT_DIR, "grid_maze_platform_tile_v1.stl")
BRIDGE_STL = os.path.join(OUTPUT_DIR, "grid_maze_platform_bridge_v1.stl")
CUTTER_STL = os.path.join(OUTPUT_DIR, "grid_maze_platform_recess_cutter_v1.stl")
PROJECT_STATUS_PATH = os.path.join(OUTPUT_DIR, "grid_maze_platform_status.txt")
TEMP_STATUS_PATH = os.path.join(tempfile.gettempdir(), "grid_maze_platform_status.txt")
CANONICAL_SIDES = ("north", "south", "east", "west")


class GridMazePlatformSpec(object):
    def __init__(
        self,
        tile_size=200.0,
        tile_height=10.0,
        pocket_depth=8.0,
        top_skin=2.0,
        dovetail_length=50.0,
        dovetail_neck_width=22.0,
        dovetail_tail_width=46.0,
        connector_thickness=6.0,
        pocket_clearance=0.2,
        enabled_sides=None,
        fillet_radius=1.2,
        mesh_tolerance=0.05,
    ):
        self.tile_size = float(tile_size)
        self.tile_height = float(tile_height)
        self.pocket_depth = float(pocket_depth)
        self.top_skin = float(top_skin)
        self.dovetail_length = float(dovetail_length)
        self.dovetail_neck_width = float(dovetail_neck_width)
        self.dovetail_tail_width = float(dovetail_tail_width)
        self.connector_thickness = float(connector_thickness)
        self.pocket_clearance = float(pocket_clearance)
        self.enabled_sides = normalize_sides(enabled_sides)
        self.fillet_radius = float(fillet_radius)
        self.mesh_tolerance = float(mesh_tolerance)

    def validate(self):
        positive = (
            "tile_size",
            "tile_height",
            "pocket_depth",
            "top_skin",
            "dovetail_length",
            "dovetail_neck_width",
            "dovetail_tail_width",
            "connector_thickness",
            "pocket_clearance",
            "mesh_tolerance",
        )
        for field in positive:
            if getattr(self, field) <= 0.0:
                raise ValueError("%s must be positive" % field)
        if abs((self.pocket_depth + self.top_skin) - self.tile_height) > 0.0001:
            raise ValueError("pocket_depth plus top_skin must equal tile_height")
        if self.connector_thickness >= self.pocket_depth:
            raise ValueError("connector_thickness must be less than pocket_depth so the connector lays recessed")
        if self.dovetail_neck_width >= self.dovetail_tail_width:
            raise ValueError("dovetail_neck_width must be smaller than dovetail_tail_width")
        if self.dovetail_length >= self.tile_size / 2.0:
            raise ValueError("dovetail_length is too large for one side of the tile")
        if self.dovetail_tail_width >= self.tile_size / 2.0:
            raise ValueError("dovetail_tail_width is too large for the tile side")
        if platform_metrics(self)["bridge_length"] >= self.tile_size:
            raise ValueError("bridge dovetail is too long for a clean first prototype")
        return self


def normalize_sides(value):
    if value is None:
        return tuple(CANONICAL_SIDES)
    if isinstance(value, str):
        raw_sides = [part.strip().lower() for part in value.replace(";", ",").split(",")]
    else:
        raw_sides = [str(part).strip().lower() for part in value]
    result = []
    invalid = []
    for side in raw_sides:
        if not side:
            continue
        if side not in CANONICAL_SIDES:
            invalid.append(side)
            continue
        if side not in result:
            result.append(side)
    if invalid:
        raise ValueError("enabled_sides contains invalid side(s): %s" % ", ".join(invalid))
    if not result:
        raise ValueError("enabled_sides must include at least one of: %s" % ", ".join(CANONICAL_SIDES))
    return tuple(side for side in CANONICAL_SIDES if side in result)


def _coerce_spec(data):
    return GridMazePlatformSpec(**data).validate()


def load_spec(path=PARAMS_PATH):
    with open(path, "r") as handle:
        return _coerce_spec(json.load(handle))


def default_spec():
    return load_spec(PARAMS_PATH)


def platform_metrics(spec):
    half = spec.tile_size / 2.0
    bridge_length = spec.dovetail_length * 2.0
    bridge_width = spec.dovetail_tail_width
    cutter_neck_width = spec.dovetail_neck_width + 2.0 * spec.pocket_clearance
    cutter_tail_width = spec.dovetail_tail_width + 2.0 * spec.pocket_clearance
    cutter_length = spec.dovetail_length + spec.pocket_clearance
    return {
        "dovetail_length": spec.dovetail_length,
        "dovetail_neck_width": spec.dovetail_neck_width,
        "dovetail_tail_width": spec.dovetail_tail_width,
        "south_pocket_center": (half, spec.dovetail_length / 2.0),
        "north_pocket_center": (half, spec.tile_size - spec.dovetail_length / 2.0),
        "west_pocket_center": (spec.dovetail_length / 2.0, half),
        "east_pocket_center": (spec.tile_size - spec.dovetail_length / 2.0, half),
        "bridge_length": bridge_length,
        "bridge_width": bridge_width,
        "cutter_neck_width": cutter_neck_width,
        "cutter_tail_width": cutter_tail_width,
        "cutter_length": cutter_length,
        "board_cutter_width": spec.tile_size + 2.0 * spec.pocket_clearance,
        "board_cutter_height": spec.tile_size + 2.0 * spec.pocket_clearance,
        "board_cutter_depth": spec.pocket_depth,
        "enabled_sides": spec.enabled_sides,
    }


def _write_status(message):
    for path in (PROJECT_STATUS_PATH, TEMP_STATUS_PATH):
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, "w") as handle:
            handle.write(message)
            handle.write("\n")


def _require_rhino():
    if Rhino is None or sc is None or System is None:
        raise RuntimeError("Rhino generation must be run inside Rhino.")
    doc = Rhino.RhinoDoc.CreateHeadless(None)
    if doc is not None:
        sc.doc = doc
        if doc.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
            doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
        return doc
    doc = getattr(sc, "doc", None)
    if doc is None:
        doc = Rhino.RhinoDoc.ActiveDoc
        if doc is not None:
            sc.doc = doc
    if doc is None:
        doc = Rhino.RhinoDoc.CreateHeadless(None)
        sc.doc = doc
    if doc is None:
        raise RuntimeError("Could not create or find a Rhino document.")
    if doc.ModelUnitSystem != Rhino.UnitSystem.Millimeters:
        doc.ModelUnitSystem = Rhino.UnitSystem.Millimeters
    _clear_existing_grid_maze_objects(doc)
    return doc


def _clear_existing_grid_maze_objects(doc):
    for rhino_object in list(doc.Objects):
        layer = doc.Layers[rhino_object.Attributes.LayerIndex]
        layer_name = layer.FullPath if layer is not None else ""
        if layer_name.startswith("GridMazePlatform"):
            doc.Objects.Delete(rhino_object, True)


def _box_brep(min_x, min_y, min_z, max_x, max_y, max_z):
    bbox = Rhino.Geometry.BoundingBox(
        Rhino.Geometry.Point3d(min_x, min_y, min_z),
        Rhino.Geometry.Point3d(max_x, max_y, max_z),
    )
    return Rhino.Geometry.Brep.CreateFromBox(bbox)


def _polygon_prism(points_xy, z_min, z_max, name):
    polyline = Rhino.Geometry.Polyline()
    for x, y in points_xy:
        polyline.Add(Rhino.Geometry.Point3d(float(x), float(y), float(z_min)))
    first_x, first_y = points_xy[0]
    polyline.Add(Rhino.Geometry.Point3d(float(first_x), float(first_y), float(z_min)))
    curve = Rhino.Geometry.PolylineCurve(polyline)
    extrusion = Rhino.Geometry.Extrusion.Create(curve, float(z_max - z_min), True)
    if extrusion is None:
        raise RuntimeError("Could not create extrusion for %s" % name)
    brep = extrusion.ToBrep()
    bbox = brep.GetBoundingBox(True)
    brep.Transform(Rhino.Geometry.Transform.Translation(0.0, 0.0, float(z_min) - bbox.Min.Z))
    return _validate_brep(brep, name)


def _cylinder_brep(cx, cy, z_min, z_max, radius):
    circle = Rhino.Geometry.Circle(
        Rhino.Geometry.Plane(Rhino.Geometry.Point3d(cx, cy, z_min), Rhino.Geometry.Vector3d.ZAxis),
        radius,
    )
    cylinder = Rhino.Geometry.Cylinder(circle, z_max - z_min)
    return cylinder.ToBrep(True, True)


def _radial_slot_brep(cx, cy, z_min, z_max, inner_radius, outer_radius, width, angle_degrees):
    length = outer_radius - inner_radius
    center_r = inner_radius + length / 2.0
    base = _box_brep(-length / 2.0, -width / 2.0, z_min, length / 2.0, width / 2.0, z_max)
    angle = math.radians(angle_degrees)
    transform = Rhino.Geometry.Transform.Rotation(angle, Rhino.Geometry.Vector3d.ZAxis, Rhino.Geometry.Point3d(0, 0, 0))
    translate = Rhino.Geometry.Transform.Translation(math.cos(angle) * center_r + cx, math.sin(angle) * center_r + cy, 0.0)
    base.Transform(transform)
    base.Transform(translate)
    return base


def _validate_brep(brep, name, require_solid=True):
    if brep is None:
        raise RuntimeError("%s was not created" % name)
    if not brep.IsValid:
        raise RuntimeError("%s is not a valid Brep" % name)
    if require_solid and not brep.IsSolid:
        raise RuntimeError("%s is not a closed solid Brep" % name)
    if require_solid and brep.SolidOrientation == Rhino.Geometry.BrepSolidOrientation.Inward:
        brep.Flip()
    return brep


def _boolean_difference(base, cutters, name):
    result = base
    tolerance = sc.doc.ModelAbsoluteTolerance if sc.doc is not None else 0.01
    for index, cutter in enumerate(cutters):
        pieces = Rhino.Geometry.Brep.CreateBooleanDifference(result, cutter, tolerance)
        if pieces is None or len(pieces) == 0:
            raise RuntimeError("%s boolean difference failed at cutter %d" % (name, index))
        result = max(pieces, key=lambda brep: abs(brep.GetVolume()))
        _validate_brep(result, "%s_after_cutter_%d" % (name, index))
    return _validate_brep(result, name)


def _boolean_union(parts, name):
    tolerance = sc.doc.ModelAbsoluteTolerance if sc.doc is not None else 0.01
    current = list(parts)
    for part in current:
        _validate_brep(part, "%s_input" % name)
    result = Rhino.Geometry.Brep.CreateBooleanUnion(current, tolerance)
    if result is None or len(result) == 0:
        raise RuntimeError("%s boolean union failed" % name)
    return _validate_brep(max(result, key=lambda brep: abs(brep.GetVolume())), name)


def _edge_recess_cutter(spec, side, xy_overrun=0.05, z_overrun=0.05):
    metrics = platform_metrics(spec)
    z_min = -float(z_overrun)
    z_max = spec.pocket_depth + float(z_overrun)
    length = spec.dovetail_length + float(xy_overrun)
    neck = spec.dovetail_neck_width + 2.0 * spec.pocket_clearance
    tail = spec.dovetail_tail_width + 2.0 * spec.pocket_clearance
    half = spec.tile_size / 2.0
    if side == "south":
        points = (
            (half - neck / 2.0, -xy_overrun),
            (half + neck / 2.0, -xy_overrun),
            (half + tail / 2.0, length),
            (half - tail / 2.0, length),
        )
    elif side == "north":
        points = (
            (half + neck / 2.0, spec.tile_size + xy_overrun),
            (half - neck / 2.0, spec.tile_size + xy_overrun),
            (half - tail / 2.0, spec.tile_size - length),
            (half + tail / 2.0, spec.tile_size - length),
        )
    elif side == "west":
        points = (
            (-xy_overrun, half + neck / 2.0),
            (-xy_overrun, half - neck / 2.0),
            (length, half - tail / 2.0),
            (length, half + tail / 2.0),
        )
    elif side == "east":
        points = (
            (spec.tile_size + xy_overrun, half - neck / 2.0),
            (spec.tile_size + xy_overrun, half + neck / 2.0),
            (spec.tile_size - length, half + tail / 2.0),
            (spec.tile_size - length, half - tail / 2.0),
        )
    else:
        raise ValueError("unknown side: %s" % side)
    return _polygon_prism(points, z_min, z_max, "grid_maze_%s_dovetail_recess_cutter" % side)


def create_platform_tile(spec):
    tile = _box_brep(0.0, 0.0, 0.0, spec.tile_size, spec.tile_size, spec.tile_height)
    cutters = []
    for side in spec.enabled_sides:
        cutters.append(_edge_recess_cutter(spec, side))
    return _boolean_difference(tile, cutters, "grid_maze_platform_tile")


def create_board_recess_cutter(spec):
    cutters = []
    for side in spec.enabled_sides:
        cutters.append(_edge_recess_cutter(spec, side, xy_overrun=spec.pocket_clearance, z_overrun=0.0))
    return cutters


def create_bridge_connector(spec):
    length = spec.dovetail_length
    neck = spec.dovetail_neck_width
    tail = spec.dovetail_tail_width
    points = (
        (-length, -tail / 2.0),
        (-length, tail / 2.0),
        (0.0, neck / 2.0),
        (length, tail / 2.0),
        (length, -tail / 2.0),
        (0.0, -neck / 2.0),
    )
    return _polygon_prism(points, 0.0, spec.connector_thickness, "grid_maze_medium_dovetail_bridge_connector")


def _add_layer(name, color):
    index = sc.doc.Layers.FindByFullPath(name, -1)
    if index >= 0:
        return index
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    layer.Color = color
    return sc.doc.Layers.Add(layer)


def _color(r, g, b):
    return System.Drawing.Color.FromArgb(int(r), int(g), int(b))


def _add_brep(brep, name, layer_name, color):
    layer_index = _add_layer(layer_name, color)
    object_id = sc.doc.Objects.AddBrep(brep)
    rhino_object = sc.doc.Objects.FindId(object_id)
    attributes = rhino_object.Attributes
    attributes.Name = name
    attributes.LayerIndex = layer_index
    attributes.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
    attributes.ObjectColor = color
    sc.doc.Objects.ModifyAttributes(object_id, attributes, True)
    return object_id


def _translated_copy(brep, dx=0.0, dy=0.0, dz=0.0):
    copy = brep.DuplicateBrep()
    copy.Transform(Rhino.Geometry.Transform.Translation(dx, dy, dz))
    return copy


def _add_reference_curves(spec):
    metrics = platform_metrics(spec)
    layer = _add_layer("GridMazePlatform::reference", _color(170, 120, 60))
    for side in spec.enabled_sides:
        name = "%s dovetail pocket center" % side
        center = metrics["%s_pocket_center" % side]
        circle = Rhino.Geometry.Circle(
            Rhino.Geometry.Plane(Rhino.Geometry.Point3d(center[0], center[1], 0.05), Rhino.Geometry.Vector3d.ZAxis),
            2.0,
        )
        object_id = sc.doc.Objects.AddCurve(circle.ToNurbsCurve())
        rhino_object = sc.doc.Objects.FindId(object_id)
        attrs = rhino_object.Attributes
        attrs.Name = name
        attrs.LayerIndex = layer
        sc.doc.Objects.ModifyAttributes(object_id, attrs, True)


def _save_doc(doc, path):
    errors = []
    try:
        options = Rhino.FileIO.FileWriteOptions()
        for name, value in (
            ("SuppressDialogBoxes", True),
            ("WriteSelectedObjectsOnly", False),
            ("WriteGeometryOnly", False),
        ):
            try:
                setattr(options, name, value)
            except Exception:
                pass
        if doc.WriteFile(path, options):
            return
        errors.append("WriteFile returned False")
    except Exception as exc:
        errors.append("WriteFile failed: %s" % exc)
    try:
        if doc.Write3dmFile(path, 8):
            return
        errors.append("Write3dmFile returned False")
    except Exception as exc:
        errors.append("Write3dmFile failed: %s" % exc)
    try:
        if doc.SaveAs(path):
            return
        errors.append("SaveAs returned False")
    except Exception as exc:
        errors.append("SaveAs failed: %s" % exc)
    raise RuntimeError("Could not save %s. %s" % (path, "; ".join(errors)))


def _mesh_triangles_from_brep(brep, name, tolerance):
    parameters = Rhino.Geometry.MeshingParameters()
    parameters.JaggedSeams = False
    parameters.SimplePlanes = True
    parameters.RefineGrid = True
    parameters.Tolerance = tolerance
    parameters.MinimumEdgeLength = 0.05
    parameters.MaximumEdgeLength = 1.2
    breps = brep if isinstance(brep, (list, tuple)) else [brep]
    triangles = []
    for brep_index, part in enumerate(breps):
        meshes = Rhino.Geometry.Mesh.CreateFromBrep(part, parameters)
        if meshes is None or len(meshes) == 0:
            raise RuntimeError("Could not mesh %s part %d for STL export" % (name, brep_index))
        for mesh in meshes:
            mesh.Faces.ConvertQuadsToTriangles()
            mesh.Normals.ComputeNormals()
            mesh.Compact()
            for face in mesh.Faces:
                if not face.IsTriangle:
                    raise RuntimeError("Non-triangle face remained in %s" % name)
                triangles.append((mesh.Vertices[face.A], mesh.Vertices[face.B], mesh.Vertices[face.C]))
    if not triangles:
        raise RuntimeError("%s mesh has no triangles" % name)
    return triangles


def _normal_for_triangle(a, b, c):
    ux, uy, uz = b.X - a.X, b.Y - a.Y, b.Z - a.Z
    vx, vy, vz = c.X - a.X, c.Y - a.Y, c.Z - a.Z
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5
    if length <= 0.0:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def _write_binary_stl(path, title, triangles):
    header = title.encode("ascii", "ignore")[:80]
    header = header + (b" " * (80 - len(header)))
    with open(path, "wb") as handle:
        handle.write(header)
        handle.write(struct.pack("<I", len(triangles)))
        for a, b, c in triangles:
            handle.write(struct.pack("<3f", *_normal_for_triangle(a, b, c)))
            for vertex in (a, b, c):
                handle.write(struct.pack("<3f", float(vertex.X), float(vertex.Y), float(vertex.Z)))
            handle.write(struct.pack("<H", 0))


def _export_stl(path, title, brep, spec):
    triangles = _mesh_triangles_from_brep(brep, title, spec.mesh_tolerance)
    _write_binary_stl(path, title, triangles)
    size = os.path.getsize(path)
    if size <= 0:
        raise RuntimeError("STL output is empty: %s" % path)
    return size


def check_only(spec):
    spec.validate()
    metrics = platform_metrics(spec)
    print("OK tile=%.1fx%.1fx%.1f pocket_depth=%.1f top_skin=%.1f dovetail=%.1fx%.1f/%.1f clearance=%.1f bridge=%.1fx%.1fx%.1f sides=%s" % (
        spec.tile_size,
        spec.tile_size,
        spec.tile_height,
        spec.pocket_depth,
        spec.top_skin,
        spec.dovetail_length,
        spec.dovetail_neck_width,
        spec.dovetail_tail_width,
        spec.pocket_clearance,
        metrics["bridge_length"],
        metrics["bridge_width"],
        spec.connector_thickness,
        ",".join(spec.enabled_sides),
    ))


def generate(spec):
    if not os.path.isdir(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    doc = _require_rhino()
    doc.ModelAbsoluteTolerance = 0.01
    doc.ModelAngleToleranceRadians = math.radians(0.25)
    tile = create_platform_tile(spec)
    bridge = create_bridge_connector(spec)
    cutter = create_board_recess_cutter(spec)
    _add_brep(tile, "grid_maze_platform_tile_v1", "GridMazePlatform::tile", _color(80, 125, 210))
    _add_brep(
        _translated_copy(bridge, spec.tile_size + 70.0, spec.tile_size / 2.0, 0.0),
        "grid_maze_medium_dovetail_bridge_connector_v1_preview",
        "GridMazePlatform::bridge",
        _color(80, 170, 115),
    )
    for index, cutter_brep in enumerate(cutter):
        _add_brep(
            _translated_copy(cutter_brep, spec.tile_size + 70.0, -70.0, 0.0),
            "grid_maze_full_board_dovetail_recess_cutter_%d_v1_preview" % (index + 1),
            "GridMazePlatform::cutter",
            _color(215, 80, 70),
        )
    _add_reference_curves(spec)
    _save_doc(doc, OUTPUT_3DM)
    tile_size = _export_stl(TILE_STL, "grid maze platform tile v1", tile, spec)
    bridge_size = _export_stl(BRIDGE_STL, "grid maze bridge connector v1", bridge, spec)
    cutter_size = _export_stl(CUTTER_STL, "grid maze full board recess cutter v1", cutter, spec)
    public_3dm_path = os.path.relpath(OUTPUT_3DM, ROOT_DIR).replace(os.sep, "/")
    message = "OK 3dm=%s tile_stl=%d bridge_stl=%d cutter_stl=%d" % (public_3dm_path, tile_size, bridge_size, cutter_size)
    _write_status(message)
    print(message)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the grid maze platform Rhino CAD pack.")
    parser.add_argument("--check", action="store_true", help="validate dimensions without Rhino")
    parser.add_argument("--params", default=PARAMS_PATH, help="path to JSON parameter file")
    parser.add_argument("--sides", help="comma-separated dovetail sides to generate: north,south,east,west")
    args = parser.parse_args(argv)
    spec = load_spec(args.params)
    if args.sides:
        spec.enabled_sides = normalize_sides(args.sides)
        spec.validate()
    if args.check:
        check_only(spec)
        return
    if Rhino is None:
        check_only(spec)
        print("Rhino is unavailable, so CAD export was skipped.")
        return
    try:
        generate(spec)
    except Exception as exc:
        _write_status("FAIL %s" % exc)
        raise


if __name__ == "__main__":
    main()
