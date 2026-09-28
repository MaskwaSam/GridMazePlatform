#!/usr/bin/env python3

"""Render the generated maze-piece STL files as consistent catalog images."""

import argparse
import os
import struct
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
DEFAULT_INPUT_DIR = os.path.join(ROOT_DIR, "output", "variants")
DEFAULT_H2D_INPUT_DIR = os.path.join(ROOT_DIR, "output", "h2d-platforms")
DEFAULT_H2D_WALL_INPUT_DIR = os.path.join(ROOT_DIR, "output", "h2d-wall-variants")
DEFAULT_RAMP_INPUT_DIR = os.path.join(ROOT_DIR, "output", "ramp")
DEFAULT_CHALLENGE_RAMP_INPUT_DIR = os.path.join(ROOT_DIR, "output", "challenge-ramp")
DEFAULT_CHALLENGE_VARIANTS_INPUT_DIR = os.path.join(ROOT_DIR, "output", "challenge-ramp-variants")
DEFAULT_OUTPUT_DIR = os.path.join(ROOT_DIR, "docs", "images")

PIECE_RENDERS = (
    ("maze_piece_straight_v1.stl", "maze-piece-straight.png"),
    ("maze_piece_corner_v1.stl", "maze-piece-corner.png"),
    ("maze_piece_t_junction_v1.stl", "maze-piece-t-junction.png"),
    ("maze_piece_cross_junction_v1.stl", "maze-piece-cross-junction.png"),
    ("maze_piece_end_v1.stl", "maze-piece-end.png"),
)

H2D_RENDERS = (
    ("maze_platform_h2d_200x300_v1.stl", "h2d-platform-200x300.png"),
    ("maze_platform_h2d_300x300_v1.stl", "h2d-platform-300x300.png"),
)

H2D_WALL_RENDERS = tuple(
    (
        "maze_piece_h2d_%s_%s_v1.stl" % (size, key),
        "h2d-wall-%s-%s.png" % (size, key.replace("_", "-")),
    )
    for size in ("200x300", "300x300")
    for key in ("straight", "corner", "t_junction", "cross_junction", "end")
) + (
    ("maze_piece_h2d_45deg_transition_v1.stl", "h2d-wall-45deg-transition.png"),
    (
        "maze_piece_h2d_300x300_45deg_four_way_v1.stl",
        "h2d-wall-300x300-45deg-four-way-clean.png",
    ),
)

RAMP_RENDERS = (
    (
        "maze_piece_x1c_200x200_30deg_ramp_v1.stl",
        "maze-piece-x1c-200x200-30deg-ramp.png",
    ),
)

CHALLENGE_RAMP_RENDERS = (
    (
        "maze_piece_h2d_200x300_30deg_up_down_ramp_v1.stl",
        "maze-piece-h2d-200x300-30deg-up-down-ramp.png",
    ),
)

CHALLENGE_VARIANT_RENDERS = (
    (
        "maze_piece_h2d_200x300_flat_top_30mm_v1.stl",
        "maze-piece-h2d-200x300-flat-top-30mm.png",
    ),
    (
        "maze_piece_h2d_200x300_double_hump_30mm_rise_v1.stl",
        "maze-piece-h2d-200x300-double-hump-30mm-rise.png",
    ),
    (
        "maze_piece_h2d_200x300_traction_ribs_v1.stl",
        "maze-piece-h2d-200x300-traction-ribs.png",
    ),
    (
        "maze_piece_h2d_200x300_low_hill_20mm_rise_v1.stl",
        "maze-piece-h2d-200x300-low-hill-20mm-rise.png",
    ),
    (
        "maze_piece_h2d_200x300_low_hill_40mm_rise_v1.stl",
        "maze-piece-h2d-200x300-low-hill-40mm-rise.png",
    ),
    (
        "maze_piece_h2d_200x300_low_hill_60mm_rise_v1.stl",
        "maze-piece-h2d-200x300-low-hill-60mm-rise.png",
    ),
    (
        "maze_piece_h2d_200x300_offset_ridge_v1.stl",
        "maze-piece-h2d-200x300-offset-ridge.png",
    ),
    (
        "maze_piece_h2d_200x300_rounded_crest_r15_v1.stl",
        "maze-piece-h2d-200x300-rounded-crest-r15.png",
    ),
    (
        "maze_piece_h2d_200x300_central_platform_80mm_v1.stl",
        "maze-piece-h2d-200x300-central-platform-80mm.png",
    ),
    (
        "maze_piece_h2d_200x300_single_wall_ridge_v1.stl",
        "maze-piece-h2d-200x300-single-wall-ridge.png",
    ),
    (
        "maze_piece_h2d_200x300_open_sides_ridge_v1.stl",
        "maze-piece-h2d-200x300-open-sides-ridge.png",
    ),
    (
        "maze_piece_h2d_200x300_ramp_up_steps_down_v1.stl",
        "maze-piece-h2d-200x300-ramp-up-steps-down.png",
    ),
)

CHALLENGE_VARIANT_TITLES = (
    "Flat-top hill",
    "Double hump",
    "Traction ribs",
    "20 mm-rise hill",
    "40 mm-rise hill",
    "60 mm-rise hill",
    "Offset ridge",
    "Rounded R15 crest",
    "80 mm platform",
    "Single-wall ridge",
    "Open-sides ridge",
    "Ramp up / steps down",
)

CHALLENGE_VARIANT_OVERVIEW = "challenge-ramp-variants-overview.png"


def read_stl(path):
    """Return an ``(triangle, vertex, xyz)`` float array from binary or ASCII STL."""
    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        expected_length = 84 + triangle_count * 50
        if expected_length == len(data):
            triangles = np.empty((triangle_count, 3, 3), dtype=np.float64)
            for index in range(triangle_count):
                values = struct.unpack_from("<12fH", data, 84 + index * 50)
                triangles[index] = np.asarray(values[3:12], dtype=np.float64).reshape(3, 3)
            return triangles

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("STL is neither valid binary nor UTF-8 ASCII: %s" % path) from exc

    vertices = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            vertices.append(tuple(float(value) for value in parts[1:]))
    if not vertices or len(vertices) % 3:
        raise ValueError("ASCII STL has an invalid vertex count: %s" % path)
    return np.asarray(vertices, dtype=np.float64).reshape(-1, 3, 3)


def mesh_bounds(triangles):
    vertices = triangles.reshape(-1, 3)
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    return minimum, maximum


def shaded_face_colors(triangles):
    first_edges = triangles[:, 1] - triangles[:, 0]
    second_edges = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(first_edges, second_edges)
    lengths = np.linalg.norm(normals, axis=1)
    safe_lengths = np.where(lengths > 1e-12, lengths, 1.0)
    normals = normals / safe_lengths[:, np.newaxis]

    light = np.asarray((0.35, -0.45, 0.82), dtype=np.float64)
    light /= np.linalg.norm(light)
    # Rhino-exported STL files may contain mixed triangle winding. Absolute light
    # response keeps coplanar faces visually consistent without changing geometry.
    brightness = 0.68 + 0.31 * np.abs(normals @ light)

    base = np.asarray((239.0, 236.0, 222.0), dtype=np.float64)
    return np.clip(base[np.newaxis, :] * brightness[:, np.newaxis], 0.0, 255.0).astype(np.uint8)


def _camera_projection(triangles, width, height):
    vertices = triangles.reshape(-1, 3)
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    center = (minimum + maximum) / 2.0

    toward_camera = np.asarray((1.25, -1.55, 1.05), dtype=np.float64)
    toward_camera /= np.linalg.norm(toward_camera)
    world_up = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    screen_right = np.cross(toward_camera, world_up)
    screen_right /= np.linalg.norm(screen_right)
    screen_up = np.cross(screen_right, toward_camera)
    screen_up /= np.linalg.norm(screen_up)

    centered = vertices - center
    projected_x = centered @ screen_right
    projected_y = centered @ screen_up
    depth = centered @ toward_camera

    x_span = max(float(np.ptp(projected_x)), 1.0)
    y_span = max(float(np.ptp(projected_y)), 1.0)
    scale = min(width * 0.76 / x_span, height * 0.75 / y_span)

    screen_x = width * 0.50 + projected_x * scale
    screen_y = height * 0.51 - projected_y * scale
    screen = np.column_stack((screen_x, screen_y, depth)).reshape(-1, 3, 3)
    return screen, minimum, maximum


def _rasterize_triangle(canvas, depth_buffer, points, color):
    x0, y0, z0 = points[0]
    x1, y1, z1 = points[1]
    x2, y2, z2 = points[2]
    denominator = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(denominator) < 1e-9:
        return

    height, width = depth_buffer.shape
    min_x = max(0, int(np.floor(min(x0, x1, x2))))
    max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
    min_y = max(0, int(np.floor(min(y0, y1, y2))))
    max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
    if min_x > max_x or min_y > max_y:
        return

    grid_x, grid_y = np.meshgrid(
        np.arange(min_x, max_x + 1, dtype=np.float64) + 0.5,
        np.arange(min_y, max_y + 1, dtype=np.float64) + 0.5,
    )
    weight0 = ((y1 - y2) * (grid_x - x2) + (x2 - x1) * (grid_y - y2)) / denominator
    weight1 = ((y2 - y0) * (grid_x - x2) + (x0 - x2) * (grid_y - y2)) / denominator
    weight2 = 1.0 - weight0 - weight1
    inside = (weight0 >= -1e-7) & (weight1 >= -1e-7) & (weight2 >= -1e-7)
    if not np.any(inside):
        return

    depth = weight0 * z0 + weight1 * z1 + weight2 * z2
    local_depth = depth_buffer[min_y : max_y + 1, min_x : max_x + 1]
    visible = inside & (depth > local_depth)
    if not np.any(visible):
        return

    local_depth[visible] = depth[visible]
    local_canvas = canvas[min_y : max_y + 1, min_x : max_x + 1]
    local_canvas[visible] = color


def _compose_catalog_image(canvas, depth_buffer, width, height):
    background = Image.new("RGB", (width, height), "#eef1ef")

    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        (width * 0.24, height * 0.69, width * 0.78, height * 0.84),
        fill=(35, 45, 48, 42),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(10, width // 70)))
    background = Image.alpha_composite(background.convert("RGBA"), shadow)

    mask_data = np.where(np.isfinite(depth_buffer), 255, 0).astype(np.uint8)
    mask = Image.fromarray(mask_data, mode="L")
    expanded = mask.filter(ImageFilter.MaxFilter(5))
    outline = ImageChops.subtract(expanded, mask)
    outline_layer = Image.new("RGBA", (width, height), (42, 49, 51, 0))
    outline_layer.putalpha(outline.point(lambda value: int(value * 0.48)))
    background = Image.alpha_composite(background, outline_layer)

    mesh_layer = Image.fromarray(canvas, mode="RGB").convert("RGBA")
    mesh_layer.putalpha(mask)
    return Image.alpha_composite(background, mesh_layer).convert("RGB")


def render_stl(input_path, output_path):
    triangles = read_stl(input_path)
    width, height = 1200, 900
    screen_triangles, minimum, maximum = _camera_projection(triangles, width, height)
    size = maximum - minimum
    if np.any(size <= 0.0):
        raise ValueError("STL has a zero-sized dimension: %s" % input_path)

    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    depth_buffer = np.full((height, width), -np.inf, dtype=np.float64)
    face_colors = shaded_face_colors(triangles)
    for points, color in zip(screen_triangles, face_colors):
        _rasterize_triangle(canvas, depth_buffer, points, color)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    image = _compose_catalog_image(canvas, depth_buffer, width, height)
    image.save(output_path, format="PNG", optimize=True)
    return len(triangles), minimum, maximum


def _overview_font(size):
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def render_challenge_variant_overview(output_dir):
    """Build a labelled 3-by-4 contact sheet from the twelve catalogue renders."""
    tile_width, tile_height = 400, 300
    columns, rows = 3, 4
    label_height = 40
    overview = Image.new("RGB", (tile_width * columns, tile_height * rows), "#eef1ef")
    font = _overview_font(21)

    for index, ((_, output_name), title) in enumerate(
        zip(CHALLENGE_VARIANT_RENDERS, CHALLENGE_VARIANT_TITLES)
    ):
        source_path = os.path.join(output_dir, output_name)
        if not os.path.isfile(source_path):
            raise FileNotFoundError("missing challenge-variant render: %s" % source_path)
        with Image.open(source_path) as source:
            tile = source.convert("RGB").resize(
                (tile_width, tile_height),
                resample=Image.Resampling.LANCZOS,
            )
        draw = ImageDraw.Draw(tile)
        draw.rectangle(
            (0, tile_height - label_height, tile_width, tile_height),
            fill=(76, 77, 75),
        )
        text_box = draw.textbbox((0, 0), title, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        draw.text(
            (
                (tile_width - text_width) / 2.0,
                tile_height - label_height + (label_height - text_height) / 2.0 - text_box[1],
            ),
            title,
            fill="white",
            font=font,
        )
        column = index % columns
        row = index // columns
        overview.paste(tile, (column * tile_width, row * tile_height))

    output_path = os.path.join(output_dir, CHALLENGE_VARIANT_OVERVIEW)
    overview.save(output_path, format="PNG", optimize=True)
    return output_path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection",
        choices=(
            "all",
            "pieces",
            "h2d",
            "h2d-walls",
            "ramp",
            "challenge-ramp",
            "challenge-ramp-variants",
        ),
        default="all",
        help="render the maze pieces, H2D platforms, H2D wall variants, ramps, or all collections",
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="folder containing generated maze-piece STL files")
    parser.add_argument(
        "--h2d-input-dir",
        default=DEFAULT_H2D_INPUT_DIR,
        help="folder containing generated H2D platform STL files",
    )
    parser.add_argument(
        "--h2d-wall-input-dir",
        default=DEFAULT_H2D_WALL_INPUT_DIR,
        help="folder containing generated H2D wall-variant STL files",
    )
    parser.add_argument(
        "--ramp-input-dir",
        default=DEFAULT_RAMP_INPUT_DIR,
        help="folder containing the generated ramp STL file",
    )
    parser.add_argument(
        "--challenge-ramp-input-dir",
        default=DEFAULT_CHALLENGE_RAMP_INPUT_DIR,
        help="folder containing the generated up-and-down challenge-ramp STL file",
    )
    parser.add_argument(
        "--challenge-variants-input-dir",
        default=DEFAULT_CHALLENGE_VARIANTS_INPUT_DIR,
        help="folder containing the generated 200 x 300 challenge-ramp variant STL files",
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="folder for rendered PNG files")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    jobs = []
    if args.collection in ("all", "pieces"):
        jobs.extend((args.input_dir, input_name, output_name) for input_name, output_name in PIECE_RENDERS)
    if args.collection in ("all", "h2d"):
        jobs.extend((args.h2d_input_dir, input_name, output_name) for input_name, output_name in H2D_RENDERS)
    if args.collection in ("all", "h2d-walls"):
        jobs.extend(
            (args.h2d_wall_input_dir, input_name, output_name)
            for input_name, output_name in H2D_WALL_RENDERS
        )
    if args.collection in ("all", "ramp"):
        jobs.extend((args.ramp_input_dir, input_name, output_name) for input_name, output_name in RAMP_RENDERS)
    if args.collection in ("all", "challenge-ramp"):
        jobs.extend(
            (args.challenge_ramp_input_dir, input_name, output_name)
            for input_name, output_name in CHALLENGE_RAMP_RENDERS
        )
    if args.collection in ("all", "challenge-ramp-variants"):
        jobs.extend(
            (args.challenge_variants_input_dir, input_name, output_name)
            for input_name, output_name in CHALLENGE_VARIANT_RENDERS
        )

    for input_dir, input_name, output_name in jobs:
        input_path = os.path.join(input_dir, input_name)
        output_path = os.path.join(args.output_dir, output_name)
        if not os.path.isfile(input_path):
            raise FileNotFoundError("missing generated piece: %s" % input_path)
        triangle_count, minimum, maximum = render_stl(input_path, output_path)
        dimensions = maximum - minimum
        print(
            "%s: %d triangles, %.2f x %.2f x %.2f mm -> %s"
            % (input_name, triangle_count, dimensions[0], dimensions[1], dimensions[2], output_path)
        )
    if args.collection in ("all", "challenge-ramp-variants"):
        print("challenge overview -> %s" % render_challenge_variant_overview(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
