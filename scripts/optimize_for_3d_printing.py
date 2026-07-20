#!/usr/bin/env python3

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, os.pardir))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from generate_grid_maze_platform import GridMazePlatformSpec, PARAMS_PATH, load_spec, platform_metrics


REPORT_PATH = os.path.join(ROOT_DIR, "output", "print_optimization_report.md")
OPTIMIZED_PARAMS_PATH = os.path.join(ROOT_DIR, "params", "maze_platform_print_optimized.json")

SPEC_FIELDS = (
    "tile_size",
    "tile_height",
    "pocket_depth",
    "top_skin",
    "dovetail_length",
    "dovetail_neck_width",
    "dovetail_tail_width",
    "connector_thickness",
    "pocket_clearance",
    "enabled_sides",
    "fillet_radius",
    "mesh_tolerance",
)


PROFILES = {
    "tight": {
        "clearance_target": 0.20,
        "clearance_min": 0.18,
        "clearance_max": 0.24,
        "slack_target": 2.0,
        "thickness_target": 6.0,
        "angle_min": 10.0,
        "angle_max": 18.0,
        "neck_min": 20.0,
        "neck_max": 26.0,
        "neck_target": 22.0,
        "tail_min": 40.0,
        "tail_max": 50.0,
    },
    "balanced": {
        "clearance_target": 0.25,
        "clearance_min": 0.22,
        "clearance_max": 0.32,
        "slack_target": 2.0,
        "thickness_target": 6.0,
        "angle_min": 10.0,
        "angle_max": 18.0,
        "neck_min": 20.0,
        "neck_max": 26.0,
        "neck_target": 22.0,
        "tail_min": 40.0,
        "tail_max": 50.0,
    },
    "durable": {
        "clearance_target": 0.25,
        "clearance_min": 0.22,
        "clearance_max": 0.32,
        "slack_target": 1.5,
        "thickness_target": 6.5,
        "angle_min": 11.0,
        "angle_max": 20.0,
        "neck_min": 22.0,
        "neck_max": 28.0,
        "neck_target": 24.0,
        "tail_min": 44.0,
        "tail_max": 54.0,
    },
}


@dataclass(frozen=True)
class Candidate:
    score: float
    spec: GridMazePlatformSpec
    summary: str
    warnings: tuple


def spec_to_dict(spec):
    data = {}
    for field in SPEC_FIELDS:
        value = getattr(spec, field)
        if field == "enabled_sides":
            data[field] = list(value)
        else:
            data[field] = value
    return data


def clone_spec(spec, **overrides):
    data = spec_to_dict(spec)
    data.update(overrides)
    return GridMazePlatformSpec(**data).validate()


def _unique_sorted(values):
    return sorted(set(round(float(value), 4) for value in values))


def _candidate_values(base, values):
    return _unique_sorted(list(values) + [base])


def bridge_profile_area(spec):
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
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def dovetail_angle_degrees(spec):
    side_run = (spec.dovetail_tail_width - spec.dovetail_neck_width) / 2.0
    return math.degrees(math.atan2(side_run, spec.dovetail_length))


def estimate_metrics(spec):
    metrics = platform_metrics(spec)
    side_count = len(spec.enabled_sides)
    cutter_profile_area = metrics["cutter_length"] * (
        metrics["cutter_neck_width"] + metrics["cutter_tail_width"]
    ) / 2.0
    bridge_area = bridge_profile_area(spec)
    return {
        "side_count": side_count,
        "vertical_slack": spec.pocket_depth - spec.connector_thickness,
        "dovetail_angle": dovetail_angle_degrees(spec),
        "bridge_volume_mm3": bridge_area * spec.connector_thickness,
        "bridge_volume_cm3": bridge_area * spec.connector_thickness / 1000.0,
        "single_pocket_removed_mm3": cutter_profile_area * spec.pocket_depth,
        "selected_pockets_removed_mm3": cutter_profile_area * spec.pocket_depth * side_count,
        "tail_width_ratio": spec.dovetail_tail_width / spec.tile_size,
        "bridge_length": metrics["bridge_length"],
        "bridge_width": metrics["bridge_width"],
    }


def _penalty_outside(value, low, high, scale):
    if value < low:
        return (low - value) * scale
    if value > high:
        return (value - high) * scale
    return 0.0


def score_spec(spec, profile_name):
    profile = PROFILES[profile_name]
    metrics = estimate_metrics(spec)
    warnings = []
    score = 0.0

    clearance = spec.pocket_clearance
    score += abs(clearance - profile["clearance_target"]) * 80.0
    score += _penalty_outside(clearance, profile["clearance_min"], profile["clearance_max"], 200.0)
    if clearance < 0.2:
        warnings.append("clearance is below 0.20 mm and will likely bind on many FDM printers")
        score += 10.0
    elif clearance <= 0.2:
        warnings.append("0.20 mm clearance is a tuned-printer fit; print a connector coupon first")
        if profile_name != "tight":
            score += 2.0
    elif clearance > 0.35:
        warnings.append("clearance above 0.35 mm may make the connector feel loose")
        score += 5.0

    slack = metrics["vertical_slack"]
    score += abs(slack - profile["slack_target"]) * 12.0
    score += _penalty_outside(slack, 1.2, 2.6, 18.0)
    if slack < 1.2:
        warnings.append("vertical slack is low; the connector may rub before it seats fully")
    elif slack > 2.6:
        warnings.append("vertical slack is high; the connector may feel loose in the recess")

    angle = metrics["dovetail_angle"]
    score += _penalty_outside(angle, profile["angle_min"], profile["angle_max"], 1.5)
    if angle < 9.0:
        warnings.append("dovetail angle is shallow, so the connector may not resist pullout well")
    elif angle > 22.0:
        warnings.append("dovetail angle is steep and may be harder to slide into a printed pocket")

    score += _penalty_outside(spec.dovetail_tail_width, profile["tail_min"], profile["tail_max"], 0.5)
    score += _penalty_outside(spec.dovetail_neck_width, profile["neck_min"], profile["neck_max"], 0.8)
    score += abs(spec.dovetail_neck_width - profile["neck_target"]) * 0.08
    if spec.dovetail_neck_width < 20.0:
        warnings.append("neck width is compact but less robust for repeated handling")
        score += 1.5
    if metrics["tail_width_ratio"] > 0.28:
        warnings.append("tail width removes a lot of material from the board edge")
        score += 4.0

    if spec.top_skin < 1.8:
        warnings.append("top skin is thin for repeated connector use")
        score += 12.0
    elif spec.top_skin < 2.0:
        warnings.append("top skin is workable but less forgiving than 2.0 mm")
        score += 3.0

    if spec.connector_thickness < 5.0:
        warnings.append("connector is thin for repeated handling")
        score += 6.0
    if spec.connector_thickness > 6.8:
        warnings.append("connector is thick enough that recess slack becomes tight")
        score += 5.0

    score += abs(spec.connector_thickness - profile["thickness_target"]) * 3.0
    score += abs(spec.dovetail_length - 50.0) * 0.04

    summary = (
        "clearance %.2f mm, dovetail %.0f x %.0f/%.0f mm, connector %.1f mm, slack %.1f mm, angle %.1f deg"
        % (
            spec.pocket_clearance,
            spec.dovetail_length,
            spec.dovetail_neck_width,
            spec.dovetail_tail_width,
            spec.connector_thickness,
            slack,
            angle,
        )
    )
    return score, summary, tuple(warnings)


def generate_candidates(base_spec, profile_name):
    lengths = _candidate_values(base_spec.dovetail_length, (40.0, 45.0, 50.0, 55.0))
    necks = _candidate_values(base_spec.dovetail_neck_width, (18.0, 20.0, 22.0, 24.0, 26.0))
    tails = _candidate_values(base_spec.dovetail_tail_width, (38.0, 42.0, 44.0, 46.0, 48.0, 50.0, 54.0))
    thicknesses = _candidate_values(base_spec.connector_thickness, (5.0, 5.5, 6.0, 6.5))
    clearances = _candidate_values(base_spec.pocket_clearance, (0.20, 0.25, 0.30))

    candidates = []
    for length in lengths:
        for neck in necks:
            for tail in tails:
                for thickness in thicknesses:
                    for clearance in clearances:
                        try:
                            spec = clone_spec(
                                base_spec,
                                dovetail_length=length,
                                dovetail_neck_width=neck,
                                dovetail_tail_width=tail,
                                connector_thickness=thickness,
                                pocket_clearance=clearance,
                            )
                        except ValueError:
                            continue
                        score, summary, warnings = score_spec(spec, profile_name)
                        candidates.append(Candidate(score, spec, summary, warnings))
    candidates.sort(key=lambda candidate: (candidate.score, candidate.spec.pocket_clearance, candidate.spec.dovetail_tail_width))
    return candidates


def audit_spec(spec):
    metrics = estimate_metrics(spec)
    checks = []

    if spec.tile_height == 10.0 and spec.pocket_depth == 8.0 and spec.top_skin == 2.0:
        checks.append(("pass", "platform stack is 10 mm total, 8 mm underside recess, 2 mm top skin"))
    else:
        checks.append(("review", "platform stack differs from the requested 10/8/2 mm split"))

    if 0.2 <= spec.pocket_clearance <= 0.35:
        label = "pass" if spec.pocket_clearance >= 0.25 else "review"
        checks.append((label, "pocket clearance is %.2f mm per side" % spec.pocket_clearance))
    else:
        checks.append(("fail", "pocket clearance %.2f mm is outside the usual FDM range" % spec.pocket_clearance))

    if 1.2 <= metrics["vertical_slack"] <= 2.6:
        checks.append(("pass", "connector sits %.1f mm below the pocket roof" % metrics["vertical_slack"]))
    else:
        checks.append(("review", "connector vertical slack is %.1f mm" % metrics["vertical_slack"]))

    if 10.0 <= metrics["dovetail_angle"] <= 18.0:
        checks.append(("pass", "dovetail taper angle is %.1f degrees per side" % metrics["dovetail_angle"]))
    else:
        checks.append(("review", "dovetail taper angle is %.1f degrees per side" % metrics["dovetail_angle"]))

    checks.append(("info", "%d selected side pocket(s): %s" % (metrics["side_count"], ", ".join(spec.enabled_sides))))
    checks.append(("info", "estimated bridge volume is %.1f cm3" % metrics["bridge_volume_cm3"]))
    checks.append(("info", "estimated selected pocket removal is %.1f cm3" % (metrics["selected_pockets_removed_mm3"] / 1000.0)))
    return checks


def format_spec_line(spec):
    return (
        "tile %.0f x %.0f x %.1f mm, pocket %.1f mm, skin %.1f mm, dovetail %.0f x %.0f/%.0f mm, "
        "connector %.1f mm, clearance %.2f mm, sides %s"
        % (
            spec.tile_size,
            spec.tile_size,
            spec.tile_height,
            spec.pocket_depth,
            spec.top_skin,
            spec.dovetail_length,
            spec.dovetail_neck_width,
            spec.dovetail_tail_width,
            spec.connector_thickness,
            spec.pocket_clearance,
            ",".join(spec.enabled_sides),
        )
    )


def build_report(base_spec, profile_name, candidates, top_count):
    base_score, base_summary, base_warnings = score_spec(base_spec, profile_name)
    best = candidates[0]
    checks = audit_spec(base_spec)
    lines = []
    lines.append("# Grid Maze Platform 3D Print Optimization")
    lines.append("")
    lines.append("Profile: `%s`" % profile_name)
    lines.append("")
    lines.append("## Baseline")
    lines.append("")
    lines.append("- %s" % format_spec_line(base_spec))
    lines.append("- Baseline score: %.2f" % base_score)
    lines.append("- %s" % base_summary)
    if base_warnings:
        for warning in base_warnings:
            lines.append("- Warning: %s" % warning)
    lines.append("")
    lines.append("## Printability Checks")
    lines.append("")
    for status, message in checks:
        lines.append("- `%s` %s" % (status, message))
    lines.append("")
    lines.append("## Recommended Variant")
    lines.append("")
    lines.append("- Score: %.2f" % best.score)
    lines.append("- %s" % format_spec_line(best.spec))
    lines.append("- %s" % best.summary)
    if best.warnings:
        for warning in best.warnings:
            lines.append("- Warning: %s" % warning)
    lines.append("")
    lines.append("## Top Candidates")
    lines.append("")
    for index, candidate in enumerate(candidates[:top_count], 1):
        lines.append("%d. score %.2f: %s" % (index, candidate.score, candidate.summary))
    lines.append("")
    lines.append("## Practical Notes")
    lines.append("")
    lines.append("- Keep printing the connector flat on the bed; this design has no intentional overhang lock.")
    lines.append("- Print one bridge plus a short edge-pocket coupon before committing to full tiles.")
    lines.append("- Use the `tight` profile if your printer reliably handles 0.20 mm clearance.")
    lines.append("- Use the `balanced` profile for a more forgiving first FDM prototype.")
    lines.append("- The optimizer does not overwrite `params/maze_platform_v1.json`; use `--write-params` to create a separate optimized JSON.")
    lines.append("")
    return "\n".join(lines)


def write_json(path, spec):
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w") as handle:
        json.dump(spec_to_dict(spec), handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze and rank 3D-printable grid maze platform parameters.")
    parser.add_argument("--params", default=PARAMS_PATH, help="path to the baseline parameter JSON")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="balanced", help="print optimization profile")
    parser.add_argument("--top", type=int, default=8, help="number of ranked candidates to show")
    parser.add_argument("--write-report", action="store_true", help="write output/print_optimization_report.md")
    parser.add_argument("--report-path", default=REPORT_PATH, help="report path used with --write-report")
    parser.add_argument("--write-params", action="store_true", help="write params/maze_platform_print_optimized.json")
    parser.add_argument("--params-output", default=OPTIMIZED_PARAMS_PATH, help="optimized params path used with --write-params")
    args = parser.parse_args(argv)

    base_spec = load_spec(args.params)
    candidates = generate_candidates(base_spec, args.profile)
    if not candidates:
        raise RuntimeError("No printable candidates were found.")
    top_count = max(1, min(args.top, len(candidates)))
    report = build_report(base_spec, args.profile, candidates, top_count)
    print(report)

    if args.write_report:
        folder = os.path.dirname(args.report_path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(args.report_path, "w") as handle:
            handle.write(report)
            handle.write("\n")
        print("Wrote %s" % args.report_path)

    if args.write_params:
        write_json(args.params_output, candidates[0].spec)
        print("Wrote %s" % args.params_output)


if __name__ == "__main__":
    main()
