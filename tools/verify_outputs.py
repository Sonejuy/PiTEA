#!/usr/bin/env python3
"""Compare reproduced outputs with the verified article references."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ABSOLUTE_TOLERANCE = 1.0e-9
RELATIVE_TOLERANCE = 1.0e-10

CSV_PAIRS = (
    ("outputs/transport_results/data/lcot_comparison.csv", "reference_results/transport_results/lcot_comparison.csv"),
    ("outputs/transport_results/data/diameter_comparison.csv", "reference_results/transport_results/diameter_comparison.csv"),
    ("outputs/transport_results/data/fixed_design_attribution.csv", "reference_results/transport_results/fixed_design_attribution.csv"),
    ("outputs/buffer_design/data/selected_results.csv", "reference_results/buffer_design/selected_results.csv"),
    ("outputs/buffer_design/data/transport_catalog.csv", "reference_results/buffer_design/transport_catalog.csv"),
    ("outputs/buffer_design/data/focal_counterfactuals.csv", "reference_results/buffer_design/focal_counterfactuals.csv"),
    ("outputs/buffer_design/data/focal_candidate_ranking.csv", "reference_results/buffer_design/focal_candidate_ranking.csv"),
    ("outputs/buffer_design/data/mechanism_slice.csv", "reference_results/buffer_design/mechanism_slice.csv"),
    ("outputs/buffer_design/data/throughput_robustness.csv", "reference_results/buffer_design/throughput_robustness.csv"),
    ("outputs/buffer_design/data/q_grid_refinement.csv", "reference_results/buffer_design/q_grid_refinement.csv"),
    ("outputs/buffer_design/data/fixed_rating_audit.csv", "reference_results/buffer_design/fixed_rating_audit.csv"),
)

TEXT_PAIRS = (
    ("outputs/transport_results/tables/lcot_matrix.tex", "reference_results/transport_results/tables/lcot_matrix.tex"),
    ("outputs/transport_results/tables/diameter_comparison.tex", "reference_results/transport_results/tables/diameter_comparison.tex"),
    ("outputs/transport_results/tables/representative_costs.tex", "reference_results/transport_results/tables/representative_costs.tex"),
    ("outputs/transport_results/figures/lcot_cost_components.tex", "reference_results/transport_results/tables/lcot_cost_components.tex"),
    ("outputs/buffer_design/tables/counterfactuals.tex", "reference_results/buffer_design/tables/counterfactuals.tex"),
    ("outputs/buffer_design/tables/inputs.tex", "reference_results/buffer_design/tables/inputs.tex"),
    ("outputs/buffer_design/tables/robustness.tex", "reference_results/buffer_design/tables/robustness.tex"),
    ("outputs/buffer_design/tables/numerical_audit.tex", "reference_results/buffer_design/tables/numerical_audit.tex"),
    ("outputs/buffer_design/tables/literature.tex", "reference_results/buffer_design/tables/literature.tex"),
)


def maybe_number(value: str) -> float | None:
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def compare_csv(actual_path: Path, expected_path: Path) -> list[str]:
    failures: list[str] = []
    with actual_path.open(newline="", encoding="utf-8") as stream:
        actual = list(csv.DictReader(stream))
    with expected_path.open(newline="", encoding="utf-8") as stream:
        expected = list(csv.DictReader(stream))
    if len(actual) != len(expected):
        return [f"row count {len(actual)} != {len(expected)}"]
    if (actual[0].keys() if actual else ()) != (expected[0].keys() if expected else ()):
        return ["column names or order differ"]
    for row_index, (observed, reference) in enumerate(zip(actual, expected), start=2):
        for field in reference:
            left = observed[field]
            right = reference[field]
            left_number = maybe_number(left)
            right_number = maybe_number(right)
            if left_number is not None and right_number is not None:
                if not math.isclose(
                    left_number,
                    right_number,
                    rel_tol=RELATIVE_TOLERANCE,
                    abs_tol=ABSOLUTE_TOLERANCE,
                ):
                    failures.append(
                        f"row {row_index}, {field}: {left!r} != {right!r}"
                    )
            elif left != right:
                failures.append(
                    f"row {row_index}, {field}: {left!r} != {right!r}"
                )
            if len(failures) >= 20:
                return failures
    return failures


def nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        current = current[key]
    return current


def compare_metric_anchors() -> list[str]:
    checks = (
        (
            "outputs/transport_results/data/metrics.json",
            "reference_results/transport_results/metrics.json",
            (
                ("grid", "mean_absolute_relative_difference_pct"),
                ("grid", "common_feasible_case_count"),
                ("grid", "nominal_diameter_match_count"),
                ("grid", "diameter_station_match_count"),
                ("diameter_grid", "pitea_h2p_nominal_diameter_match_count"),
                ("candidate_audit", "pitea_candidate_count"),
                ("candidate_audit", "h2p_candidate_count"),
            ),
        ),
        (
            "outputs/buffer_design/data/metrics.json",
            "reference_results/buffer_design/metrics.json",
            (
                ("primary_dimensions", "service_points"),
                ("primary_dimensions", "selected_rows"),
                ("focal_case", "required_buffer_t"),
                ("focal_case", "external_storage_only_lcot_2023_usd_per_kg"),
                ("focal_case", "linepack_without_redesign_lcot_2023_usd_per_kg"),
                ("focal_case", "joint_design_lcot_2023_usd_per_kg"),
                ("focal_case", "joint_saving_vs_external_storage_only_percent"),
                ("focal_case", "joint_design"),
            ),
        ),
    )
    failures: list[str] = []
    for actual_name, expected_name, paths in checks:
        actual = json.loads((ROOT / actual_name).read_text(encoding="utf-8"))
        expected = json.loads((ROOT / expected_name).read_text(encoding="utf-8"))
        for path in paths:
            observed = nested(actual, *path)
            reference = nested(expected, *path)
            if isinstance(observed, (int, float)) and isinstance(reference, (int, float)):
                equal = math.isclose(
                    float(observed),
                    float(reference),
                    rel_tol=RELATIVE_TOLERANCE,
                    abs_tol=ABSOLUTE_TOLERANCE,
                )
            else:
                equal = observed == reference
            if not equal:
                failures.append(
                    f"{actual_name}:{'.'.join(path)} {observed!r} != {reference!r}"
                )
    recomputation = json.loads(
        (ROOT / "outputs/transport_results/data/pitea_recomputation_audit.json").read_text(
            encoding="utf-8"
        )
    )
    expected_recomputation = {
        "status": "pass",
        "case_count": 48,
        "candidate_count": 10_088,
        "feasible_candidate_count": 2_751,
    }
    for field, reference in expected_recomputation.items():
        if recomputation.get(field) != reference:
            failures.append(
                "outputs/transport_results/data/pitea_recomputation_audit.json:"
                f"{field} {recomputation.get(field)!r} != {reference!r}"
            )
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Package root (defaults to the parent of this script)",
    )
    return parser.parse_args()


def main() -> None:
    global ROOT
    ROOT = parse_args().root.resolve()
    failures: list[str] = []
    for actual_name, expected_name in CSV_PAIRS:
        actual_path = ROOT / actual_name
        expected_path = ROOT / expected_name
        if not actual_path.exists():
            failures.append(f"missing reproduced file: {actual_name}")
            continue
        problems = compare_csv(actual_path, expected_path)
        if problems:
            failures.extend(f"{actual_name}: {problem}" for problem in problems)
        else:
            print(f"PASS {actual_name}")
    for actual_name, expected_name in TEXT_PAIRS:
        actual_path = ROOT / actual_name
        expected_path = ROOT / expected_name
        if not actual_path.exists():
            failures.append(f"missing reproduced file: {actual_name}")
        elif actual_path.read_bytes() != expected_path.read_bytes():
            failures.append(f"{actual_name}: text differs from verified reference")
        else:
            print(f"PASS {actual_name}")
    if not failures:
        metric_failures = compare_metric_anchors()
        failures.extend(metric_failures)
        if not metric_failures:
            print("PASS article result anchors")
    if failures:
        detail = "\n".join(f"- {failure}" for failure in failures)
        raise SystemExit(f"Verification failed:\n{detail}")
    print("All authoritative numerical outputs match the associated article.")


if __name__ == "__main__":
    main()
