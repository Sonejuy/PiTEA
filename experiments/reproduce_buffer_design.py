"""Reproduce the joint pipeline and buffer design results.

The main experiment is a stylized map over corridor length, equivalent buffer
duration, and external-storage capacity cost at 0.50 Mt/y annual delivery.
Every point is evaluated under three service-equivalent strategies:

1. external storage only;
2. linepack without infrastructure redesign; and
3. joint design.

The script writes the complete machine-readable ledger, focal counterfactuals,
robustness and numerical-audit records, article tables, vector figures, and
a JSON metrics file. Outputs are written under ``outputs/buffer_design``.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipeline_model as model  # noqa: E402


OUTPUT_ROOT = ROOT / "outputs" / "buffer_design"
DATA_DIR = OUTPUT_ROOT / "data"
TABLE_DIR = OUTPUT_ROOT / "tables"
FIGURE_DIR = OUTPUT_ROOT / "figures"
LITERATURE_INPUT = (
    ROOT / "data" / "literature" / "buffer_design_literature_ledger.csv"
)

REFERENCE_ANNUAL_DELIVERY_KG = 0.50e9
LENGTHS_KM = (400.0, 800.0, 1200.0, 1600.0, 2000.0)
BUFFER_HOURS = (0.0, 6.0, 12.0, 24.0, 36.0, 48.0, 72.0)
STORAGE_COSTS_2023_USD_PER_KG = (100.0, 200.0, 600.0)
DIAMETERS_IN = (
    4.0,
    6.0,
    8.0,
    10.0,
    12.0,
    14.0,
    16.0,
    18.0,
    20.0,
    24.0,
    30.0,
    36.0,
    42.0,
)
Q_GRID_POINTS = 241

FOCAL_LENGTH_KM = 1200.0
FOCAL_BUFFER_HOURS = 72.0
FOCAL_STORAGE_COST_2023_USD_PER_KG = 600.0
MECHANISM_HOURS = tuple(float(value) for value in range(0, 73, 3))

PRIMARY_RESULTS = DATA_DIR / "selected_results.csv"
CATALOG_RESULTS = DATA_DIR / "transport_catalog.csv"
FOCAL_RESULTS = DATA_DIR / "focal_counterfactuals.csv"
FOCAL_RANKING = DATA_DIR / "focal_candidate_ranking.csv"
MECHANISM_RESULTS = DATA_DIR / "mechanism_slice.csv"
ROBUSTNESS_RESULTS = DATA_DIR / "throughput_robustness.csv"
Q_REFINEMENT_RESULTS = DATA_DIR / "q_grid_refinement.csv"
RATING_AUDIT_RESULTS = DATA_DIR / "fixed_rating_audit.csv"
LITERATURE_RESULTS = DATA_DIR / "literature_ledger.csv"
METRICS_RESULTS = DATA_DIR / "metrics.json"


def _mkdirs() -> None:
    for directory in (DATA_DIR, TABLE_DIR, FIGURE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write an empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _result_row(
    result: model.SelectedResult,
    *,
    external_storage_only: model.SelectedResult,
    fixed: model.SelectedResult,
    joint: model.SelectedResult,
) -> dict[str, Any]:
    row = result.to_dict()
    row.update(
        {
            "delta_embedded_2023_usd_per_kg": (
                external_storage_only.lcot_2023_usd_per_kg
                - fixed.lcot_2023_usd_per_kg
            ),
            "delta_redesign_2023_usd_per_kg": (
                fixed.lcot_2023_usd_per_kg
                - joint.lcot_2023_usd_per_kg
            ),
            "delta_joint_vs_external_storage_only_2023_usd_per_kg": (
                external_storage_only.lcot_2023_usd_per_kg
                - joint.lcot_2023_usd_per_kg
            ),
            "joint_saving_vs_external_storage_only_percent": (
                0.0
                if external_storage_only.lcot_2023_usd_per_kg == 0.0
                else 100.0
                * (
                    external_storage_only.lcot_2023_usd_per_kg
                    - joint.lcot_2023_usd_per_kg
                )
                / external_storage_only.lcot_2023_usd_per_kg
            ),
        }
    )
    return row


def _build_contexts(
    basis: model.StudyBasis,
    lengths_km: Sequence[float],
) -> tuple[
    dict[float, dict[str, Any]],
    list[dict[str, Any]],
]:
    contexts: dict[float, dict[str, Any]] = {}
    catalog_rows: list[dict[str, Any]] = []
    for length in lengths_km:
        catalog = model.build_transport_catalog(
            basis=basis,
            length_km=length,
            diameters_in=DIAMETERS_IN,
        )
        transport = model.select_transport(catalog)
        joint_curves, fixed_curve = model.build_curves(
            catalog=catalog,
            basis=basis,
            strict_fixed_candidate=transport,
            preserve_sizing_margin=True,
        )
        contexts[length] = {
            "catalog": catalog,
            "transport": transport,
            "joint_curves": joint_curves,
            "fixed_curve": fixed_curve or [],
        }
        for candidate in catalog:
            catalog_rows.append(
                {
                    "annual_delivered_kg": basis.annual_delivered_kg,
                    "length_km": length,
                    "diameter_in": candidate.diameter_in,
                    "stations": candidate.stations,
                    "segment_length_km": candidate.segment_length_km,
                    "pack_outlet_bar_a": candidate.pack_state.P_out_pack_bar,
                    "pack_average_bar_a": candidate.pack_state.P_avg_pack_bar,
                    "gathering_stages": (
                        candidate.gathering.installed_stages
                    ),
                    "gathering_rating_unit_kw": (
                        candidate.gathering.installed_rating_unit_kw
                    ),
                    "enroute_stages": candidate.enroute.installed_stages,
                    "enroute_rating_unit_kw": (
                        candidate.enroute.installed_rating_unit_kw
                    ),
                    "pipeline_capex_2018_usd": (
                        candidate.pipeline_cost.capex_pipe_usd
                    ),
                    "compressor_capex_2018_usd": (
                        candidate.compressor_capex_2018_usd
                    ),
                    "full_year_energy_kwh": (
                        candidate.full_year_energy_kwh
                    ),
                    "transport_lcot_2023_usd_per_kg": (
                        candidate.transport_lcot_2023_usd_per_kg
                    ),
                    "transport_selected": candidate is transport,
                }
            )
    return contexts, catalog_rows


def _evaluate_service_point(
    *,
    context: dict[str, Any],
    basis: model.StudyBasis,
    buffer_hours: float,
    storage_cost: float,
) -> tuple[
    model.SelectedResult,
    model.SelectedResult,
    model.SelectedResult,
    list[model.SelectedResult],
]:
    transport = context["transport"]
    external_storage_only = model.external_storage_only_result(
        transport=transport,
        basis=basis,
        buffer_hours=buffer_hours,
        storage_cost_2023_usd_per_kg=storage_cost,
    )
    fixed = model.linepack_without_redesign_result(
        transport=transport,
        fixed_curve=context["fixed_curve"],
        basis=basis,
        buffer_hours=buffer_hours,
        storage_cost_2023_usd_per_kg=storage_cost,
        preserve_sizing_margin=True,
    )
    joint, ranking = model.joint_design_result(
        catalog=context["catalog"],
        joint_curves=context["joint_curves"],
        transport=transport,
        basis=basis,
        buffer_hours=buffer_hours,
        storage_cost_2023_usd_per_kg=storage_cost,
    )
    return external_storage_only, fixed, joint, ranking


def _run_primary(
    basis: model.StudyBasis,
    contexts: dict[float, dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[model.SelectedResult],
    list[model.SelectedResult],
]:
    rows: list[dict[str, Any]] = []
    focal_results: list[model.SelectedResult] = []
    focal_ranking: list[model.SelectedResult] = []
    for storage_cost in STORAGE_COSTS_2023_USD_PER_KG:
        for length in LENGTHS_KM:
            context = contexts[length]
            for hours in BUFFER_HOURS:
                external_storage_only, fixed, joint, ranking = _evaluate_service_point(
                    context=context,
                    basis=basis,
                    buffer_hours=hours,
                    storage_cost=storage_cost,
                )
                for result in (external_storage_only, fixed, joint):
                    rows.append(
                        _result_row(
                            result,
                            external_storage_only=external_storage_only,
                            fixed=fixed,
                            joint=joint,
                        )
                    )
                if (
                    length == FOCAL_LENGTH_KM
                    and hours == FOCAL_BUFFER_HOURS
                    and storage_cost
                    == FOCAL_STORAGE_COST_2023_USD_PER_KG
                ):
                    focal_results = [external_storage_only, fixed, joint]
                    focal_ranking = ranking
    if len(focal_results) != 3:
        raise AssertionError("Focal counterfactual was not captured")
    joint_rows = [row for row in rows if row["strategy"] == "Joint design"]
    largest_saving = max(
        joint_rows,
        key=lambda row: float(row["joint_saving_vs_external_storage_only_percent"]),
    )
    largest_case = (
        float(largest_saving["length_km"]),
        float(largest_saving["buffer_hours"]),
        float(largest_saving["storage_cost_2023_usd_per_kg"]),
    )
    expected_case = (
        FOCAL_LENGTH_KM,
        FOCAL_BUFFER_HOURS,
        FOCAL_STORAGE_COST_2023_USD_PER_KG,
    )
    if largest_case != expected_case or not math.isclose(
        float(largest_saving["joint_saving_vs_external_storage_only_percent"]),
        43.129994643832106,
        rel_tol=1.0e-12,
        abs_tol=1.0e-12,
    ):
        raise AssertionError(
            "The article's focal case is no longer the largest evaluated "
            f"joint-design saving: {largest_case!r}"
        )
    return rows, focal_results, focal_ranking


def _run_mechanism_slice(
    basis: model.StudyBasis,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[model.SelectedResult]]:
    rows: list[dict[str, Any]] = []
    joint_results: list[model.SelectedResult] = []
    for hours in MECHANISM_HOURS:
        external_storage_only, fixed, joint, _ = _evaluate_service_point(
            context=context,
            basis=basis,
            buffer_hours=hours,
            storage_cost=FOCAL_STORAGE_COST_2023_USD_PER_KG,
        )
        joint_results.append(joint)
        for result in (external_storage_only, fixed, joint):
            rows.append(
                _result_row(
                    result,
                    external_storage_only=external_storage_only,
                    fixed=fixed,
                    joint=joint,
                )
            )
    return rows, joint_results


def _best_per_design(
    ranking: Sequence[model.SelectedResult],
) -> list[model.SelectedResult]:
    best: dict[tuple[float, int], model.SelectedResult] = {}
    for result in ranking:
        key = (result.diameter_in, result.stations)
        incumbent = best.get(key)
        if (
            incumbent is None
            or result.lcot_2023_usd_per_kg
            < incumbent.lcot_2023_usd_per_kg
        ):
            best[key] = result
    return sorted(
        best.values(),
        key=lambda result: result.lcot_2023_usd_per_kg,
    )


def _run_q_refinement() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for points in (41, 81, 121, 241, 481):
        basis = model.StudyBasis(
            annual_delivered_kg=REFERENCE_ANNUAL_DELIVERY_KG,
            q_grid_points=points,
        )
        contexts, _ = _build_contexts(basis, [FOCAL_LENGTH_KM])
        external_storage_only, fixed, joint, _ = _evaluate_service_point(
            context=contexts[FOCAL_LENGTH_KM],
            basis=basis,
            buffer_hours=FOCAL_BUFFER_HOURS,
            storage_cost=FOCAL_STORAGE_COST_2023_USD_PER_KG,
        )
        rows.append(
            {
                "q_grid_points": points,
                "external_storage_only_lcot_2023_usd_per_kg": (
                    external_storage_only.lcot_2023_usd_per_kg
                ),
                "linepack_without_redesign_lcot_2023_usd_per_kg": (
                    fixed.lcot_2023_usd_per_kg
                ),
                "linepack_without_redesign_q_bar_a": fixed.q_bar_a,
                "linepack_without_redesign_credited_linepack_kg": fixed.credited_linepack_kg,
                "linepack_without_redesign_external_storage_kg": fixed.external_storage_kg,
                "joint_design_lcot_2023_usd_per_kg": (
                    joint.lcot_2023_usd_per_kg
                ),
                "joint_design_diameter_in": joint.diameter_in,
                "joint_design_stations": joint.stations,
                "joint_design_q_bar_a": joint.q_bar_a,
                "joint_design_credited_linepack_kg": (
                    joint.credited_linepack_kg
                ),
                "joint_design_external_storage_kg": joint.external_storage_kg,
            }
        )
    return rows


def _run_rating_audit(
    basis: model.StudyBasis,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for preserve_margin in (True, False):
        fixed_curve = model.operating_curve(
            candidate=context["transport"],
            basis=basis,
            strict_fixed_hardware=True,
            preserve_sizing_margin=preserve_margin,
        )
        fixed = model.linepack_without_redesign_result(
            transport=context["transport"],
            fixed_curve=fixed_curve,
            basis=basis,
            buffer_hours=FOCAL_BUFFER_HOURS,
            storage_cost_2023_usd_per_kg=(
                FOCAL_STORAGE_COST_2023_USD_PER_KG
            ),
            preserve_sizing_margin=preserve_margin,
        )
        rows.append(
            {
                "policy": (
                    "Preserve 15% sizing margin"
                    if preserve_margin
                    else "Permit use of installed nameplate reserve"
                ),
                "diameter_in": fixed.diameter_in,
                "stations": fixed.stations,
                "q_bar_a": fixed.q_bar_a,
                "credited_linepack_kg": fixed.credited_linepack_kg,
                "external_storage_kg": fixed.external_storage_kg,
                "lcot_2023_usd_per_kg": fixed.lcot_2023_usd_per_kg,
            }
        )
    return rows


def _run_throughput_robustness() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for annual_mt in (0.25, 0.50, 1.00):
        basis = model.StudyBasis(
            annual_delivered_kg=annual_mt * 1.0e9,
            q_grid_points=Q_GRID_POINTS,
        )
        contexts, _ = _build_contexts(basis, LENGTHS_KM)
        for storage_cost in (200.0, 600.0):
            for length in LENGTHS_KM:
                context = contexts[length]
                for hours in BUFFER_HOURS:
                    external_storage_only, fixed, joint, _ = _evaluate_service_point(
                        context=context,
                        basis=basis,
                        buffer_hours=hours,
                        storage_cost=storage_cost,
                    )
                    rows.append(
                        {
                            "annual_delivery_mt_per_year": annual_mt,
                            "length_km": length,
                            "buffer_hours": hours,
                            "storage_cost_2023_usd_per_kg": storage_cost,
                            "transport_diameter_in": (
                                context["transport"].diameter_in
                            ),
                            "transport_stations": (
                                context["transport"].stations
                            ),
                            "joint_design_diameter_in": joint.diameter_in,
                            "joint_design_stations": joint.stations,
                            "joint_design_infrastructure_response": (
                                joint.infrastructure_response
                            ),
                            "external_storage_only_lcot_2023_usd_per_kg": (
                                external_storage_only.lcot_2023_usd_per_kg
                            ),
                            "linepack_without_redesign_lcot_2023_usd_per_kg": (
                                fixed.lcot_2023_usd_per_kg
                            ),
                            "joint_design_lcot_2023_usd_per_kg": (
                                joint.lcot_2023_usd_per_kg
                            ),
                            "delta_embedded_2023_usd_per_kg": (
                                external_storage_only.lcot_2023_usd_per_kg
                                - fixed.lcot_2023_usd_per_kg
                            ),
                            "delta_redesign_2023_usd_per_kg": (
                                fixed.lcot_2023_usd_per_kg
                                - joint.lcot_2023_usd_per_kg
                            ),
                        }
                    )
    return rows


def _literature_ledger() -> list[dict[str, Any]]:
    """Load the manually curated literature-comparison ledger."""

    with LITERATURE_INPUT.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"Literature ledger is empty: {LITERATURE_INPUT}")
    return rows


def _response_summary(
    rows: Sequence[dict[str, Any]],
    *,
    strategy: str = "Joint design",
) -> dict[str, int]:
    counts = {
        "Transport assets retained": 0,
        "Compressor resize": 0,
        "Station-count change": 0,
        "Diameter change": 0,
    }
    for row in rows:
        if (
            row.get("strategy") == strategy
            and float(row.get("buffer_hours", 0.0)) > 0.0
        ):
            counts[str(row["infrastructure_response"])] += 1
    return counts


def _plot_regime_map(rows: Sequence[dict[str, Any]]) -> None:
    joint_rows = [
        row for row in rows if row["strategy"] == "Joint design"
    ]
    lookup = {
        (
            float(row["storage_cost_2023_usd_per_kg"]),
            float(row["length_km"]),
            float(row["buffer_hours"]),
        ): row
        for row in joint_rows
    }
    categories = [
        "Transport assets retained",
        "Compressor resize",
        "Station-count change",
        "Diameter change",
    ]
    display_categories = {
        "Transport assets retained": "Same hardware",
        "Compressor resize": "Compressor changed",
        "Station-count change": "Station count changed",
        "Diameter change": "Diameter changed",
    }
    colors = ["#dceaf4", "#8fc4df", "#f6b26b", "#d95f0e"]
    category_index = {category: index for index, category in enumerate(categories)}
    cmap = ListedColormap(colors)
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], cmap.N)

    lcot_values = [
        float(row["lcot_2023_usd_per_kg"])
        for row in joint_rows
    ]
    q_values = [
        float(row["q_bar_a"])
        for row in joint_rows
        if row["q_bar_a"] not in (None, "")
    ]
    lcot_min = math.floor(min(lcot_values) * 20.0) / 20.0
    lcot_max = math.ceil(max(lcot_values) * 20.0) / 20.0
    q_min = 5.0 * math.floor(min(q_values) / 5.0)
    q_max = 5.0 * math.ceil(max(q_values) / 5.0)
    lcot_norm = Normalize(vmin=lcot_min, vmax=lcot_max)
    q_norm = Normalize(vmin=q_min, vmax=q_max)
    lcot_cmap = plt.get_cmap("YlOrRd").copy()
    q_cmap = plt.get_cmap("YlGnBu").copy()
    q_cmap.set_bad("#eeeeee")

    def text_color(color_map: Any, color_norm: Normalize, value: float) -> str:
        red, green, blue, _ = color_map(color_norm(value))
        luminance = 0.299 * red + 0.587 * green + 0.114 * blue
        return "white" if luminance < 0.52 else "#1b1b1b"

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig = plt.figure(figsize=(7.35, 6.95))
    grid = fig.add_gridspec(
        3,
        4,
        width_ratios=(1.0, 1.0, 1.0, 0.055),
        hspace=0.20,
        wspace=0.11,
    )
    axes = [
        [fig.add_subplot(grid[row_index, column_index]) for column_index in range(3)]
        for row_index in range(3)
    ]
    legend_axis = fig.add_subplot(grid[0, 3])
    legend_axis.axis("off")
    lcot_color_axis = fig.add_subplot(grid[1, 3])
    q_color_axis = fig.add_subplot(grid[2, 3])

    lcot_image = None
    q_image = None
    for column_index, storage_cost in enumerate(
        STORAGE_COSTS_2023_USD_PER_KG
    ):
        response_matrix = []
        lcot_matrix = []
        q_matrix = []
        for hours in BUFFER_HOURS:
            response_matrix.append(
                [
                    category_index[
                        str(
                            lookup[
                                (storage_cost, length, hours)
                            ]["infrastructure_response"]
                        )
                    ]
                    for length in LENGTHS_KM
                ]
            )
            lcot_matrix.append(
                [
                    float(
                        lookup[(storage_cost, length, hours)][
                            "lcot_2023_usd_per_kg"
                        ]
                    )
                    for length in LENGTHS_KM
                ]
            )
            q_matrix.append(
                [
                    (
                        math.nan
                        if lookup[(storage_cost, length, hours)]["q_bar_a"]
                        in (None, "")
                        else float(
                            lookup[(storage_cost, length, hours)]["q_bar_a"]
                        )
                    )
                    for length in LENGTHS_KM
                ]
            )

        response_axis = axes[0][column_index]
        lcot_axis = axes[1][column_index]
        q_axis = axes[2][column_index]
        response_axis.imshow(
            response_matrix,
            origin="lower",
            aspect="auto",
            cmap=cmap,
            norm=norm,
            interpolation="none",
        )
        lcot_image = lcot_axis.imshow(
            lcot_matrix,
            origin="lower",
            aspect="auto",
            cmap=lcot_cmap,
            norm=lcot_norm,
            interpolation="none",
        )
        q_image = q_axis.imshow(
            q_matrix,
            origin="lower",
            aspect="auto",
            cmap=q_cmap,
            norm=q_norm,
            interpolation="none",
        )
        for y_index, hours in enumerate(BUFFER_HOURS):
            for x_index, length in enumerate(LENGTHS_KM):
                row = lookup[(storage_cost, length, hours)]
                value = category_index[str(row["infrastructure_response"])]
                response_axis.text(
                    x_index,
                    y_index,
                    (
                        f"{float(row['diameter_in']):.0f}/"
                        f"{int(row['stations'])}"
                    ),
                    ha="center",
                    va="center",
                    fontsize=5.8,
                    color="white" if value == 3 else "#1b1b1b",
                    fontweight="semibold" if value >= 2 else "normal",
                )
                lcot = float(row["lcot_2023_usd_per_kg"])
                lcot_axis.text(
                    x_index,
                    y_index,
                    f"{lcot:.3f}",
                    ha="center",
                    va="center",
                    fontsize=5.3,
                    color=text_color(lcot_cmap, lcot_norm, lcot),
                )
                q_value = row["q_bar_a"]
                if q_value in (None, ""):
                    q_text = "--"
                    q_text_color = "#555555"
                else:
                    q_float = float(q_value)
                    q_text = f"{q_float:.1f}"
                    q_text_color = text_color(q_cmap, q_norm, q_float)
                q_axis.text(
                    x_index,
                    y_index,
                    q_text,
                    ha="center",
                    va="center",
                    fontsize=5.5,
                    color=q_text_color,
                )

        response_axis.set_title(f"{storage_cost:.0f}", pad=4)
        for row_index, axis in enumerate(
            (response_axis, lcot_axis, q_axis)
        ):
            axis.set_xticks(range(len(LENGTHS_KM)))
            axis.set_xticklabels(
                [f"{length / 1000:.1f}" for length in LENGTHS_KM]
            )
            axis.set_yticks(range(len(BUFFER_HOURS)))
            axis.set_yticklabels([f"{hours:.0f}" for hours in BUFFER_HOURS])
            axis.tick_params(
                labelbottom=row_index == 2,
                labelleft=column_index == 0,
            )
            axis.set_xticks(
                [index - 0.5 for index in range(1, len(LENGTHS_KM))],
                minor=True,
            )
            axis.set_yticks(
                [index - 0.5 for index in range(1, len(BUFFER_HOURS))],
                minor=True,
            )
            axis.grid(which="minor", color="white", linewidth=0.75)
            axis.tick_params(which="minor", length=0)
        q_axis.set_xlabel("Length (10$^3$ km)")

    axes[0][0].set_ylabel("Buffer duration (h)")
    axes[1][0].set_ylabel("Buffer duration (h)")
    axes[2][0].set_ylabel("Buffer duration (h)")
    fig.text(
        0.015,
        0.765,
        "(a) Optimal design",
        rotation=90,
        ha="center",
        va="center",
        fontsize=8.2,
        fontweight="semibold",
    )
    fig.text(
        0.015,
        0.495,
        "(b) Joint-design LCOT",
        rotation=90,
        ha="center",
        va="center",
        fontsize=8.2,
        fontweight="semibold",
    )
    fig.text(
        0.015,
        0.225,
        "(c) Draft outlet pressure",
        rotation=90,
        ha="center",
        va="center",
        fontsize=8.2,
        fontweight="semibold",
    )
    fig.text(
        0.515,
        0.985,
        "External-storage cost (constant-2023 USD/kg-capacity)",
        ha="center",
        va="top",
        fontsize=8.5,
    )

    focal_column = STORAGE_COSTS_2023_USD_PER_KG.index(
        FOCAL_STORAGE_COST_2023_USD_PER_KG
    )
    focal_x = LENGTHS_KM.index(FOCAL_LENGTH_KM)
    focal_y = BUFFER_HOURS.index(FOCAL_BUFFER_HOURS)
    for row_index in range(3):
        axes[row_index][focal_column].add_patch(
            Rectangle(
                (focal_x - 0.46, focal_y - 0.46),
                0.92,
                0.92,
                fill=False,
                edgecolor="black",
                linewidth=1.5,
            )
        )

    handles = [
        Line2D(
            [0],
            [0],
            marker="s",
            linestyle="",
            markerfacecolor=color,
            markeredgecolor="none",
            markersize=7,
            label=display_categories[category],
        )
        for category, color in zip(categories, colors, strict=True)
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.008),
        fontsize=6.7,
        columnspacing=0.9,
        handletextpad=0.25,
    )
    if lcot_image is None or q_image is None:
        raise AssertionError("Sweep figure did not receive plot data")
    lcot_bar = fig.colorbar(lcot_image, cax=lcot_color_axis)
    lcot_bar.set_label("2023 USD/kg", fontsize=7.2)
    lcot_bar.ax.tick_params(labelsize=6.7)
    q_bar = fig.colorbar(q_image, cax=q_color_axis)
    q_bar.set_label("$q^*$ (bar(a))", fontsize=7.2)
    q_bar.ax.tick_params(labelsize=6.7)
    fig.subplots_adjust(
        left=0.105,
        right=0.965,
        top=0.935,
        bottom=0.105,
    )
    pdf_path = FIGURE_DIR / "regime_map.pdf"
    png_path = FIGURE_DIR / "regime_map.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _plot_mechanism(
    mechanism_rows: Sequence[dict[str, Any]],
    focal_results: Sequence[model.SelectedResult],
) -> None:
    lookup = {
        (str(row["strategy"]), float(row["buffer_hours"])): row
        for row in mechanism_rows
    }
    strategies = (
        ("External storage only", "External storage only", "#7f7f7f", "--"),
        (
            "Linepack without redesign",
            "Linepack without redesign",
            "#2b6ca3",
            "-.",
        ),
        ("Joint design", "Joint design", "#d95f0e", "-"),
    )
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "legend.fontsize": 7.4,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig = plt.figure(figsize=(7.35, 3.15))
    grid = fig.add_gridspec(
        1,
        2,
        width_ratios=[1.55, 1.0],
        wspace=0.34,
    )
    ax_curve = fig.add_subplot(grid[0, 0])
    ax_bar = fig.add_subplot(grid[0, 1])

    for strategy, display_label, color, linestyle in strategies:
        values = [
            float(
                lookup[(strategy, hours)][
                    "lcot_2023_usd_per_kg"
                ]
            )
            for hours in MECHANISM_HOURS
        ]
        ax_curve.plot(
            MECHANISM_HOURS,
            values,
            color=color,
            linestyle=linestyle,
            linewidth=1.8,
            label=display_label,
        )
    ax_curve.axvline(
        FOCAL_BUFFER_HOURS,
        color="#222222",
        linewidth=0.8,
        linestyle=":",
    )
    milestone_hours = (0.0, 24.0, 36.0, 48.0, 72.0)
    offsets = {
        0.0: (3, 8),
        24.0: (-2, 8),
        36.0: (-5, -17),
        48.0: (-2, 8),
        72.0: (-27, -16),
    }
    for hours in milestone_hours:
        row = lookup[("Joint design", hours)]
        x_value = hours
        y_value = float(row["lcot_2023_usd_per_kg"])
        ax_curve.scatter(
            [x_value],
            [y_value],
            s=18,
            facecolor="white",
            edgecolor="#d95f0e",
            linewidth=1.0,
            zorder=5,
        )
        dx, dy = offsets[hours]
        ax_curve.annotate(
            (
                f"{float(row['diameter_in']):.0f} in., "
                f"$n={int(row['stations'])}$"
            ),
            (x_value, y_value),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=6.7,
            color="#6b2e00",
        )
    ax_curve.set_xlim(0.0, 72.0)
    ax_curve.set_xticks((0, 12, 24, 36, 48, 60, 72))
    ax_curve.set_xlabel("Equivalent buffer duration (h)")
    ax_curve.set_ylabel("LCOT (2023 USD/kg)")
    ax_curve.set_title("(a) LCOT by buffer-supply strategy")
    ax_curve.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax_curve.legend(frameon=False, loc="upper left")

    components = (
        ("pipeline_lcot_2023_usd_per_kg", "Pipeline", "#4c78a8"),
        ("compressor_lcot_2023_usd_per_kg", "Compression", "#f58518"),
        ("electricity_lcot_2023_usd_per_kg", "Electricity", "#54a24b"),
        ("storage_lcot_2023_usd_per_kg", "External storage", "#e45756"),
    )
    x_positions = range(len(focal_results))
    bottoms = [0.0] * len(focal_results)
    for field, label, color in components:
        heights = [float(getattr(result, field)) for result in focal_results]
        ax_bar.bar(
            x_positions,
            heights,
            bottom=bottoms,
            width=0.66,
            color=color,
            label=label,
        )
        bottoms = [
            bottom + height
            for bottom, height in zip(bottoms, heights, strict=True)
        ]
    for x_value, result in zip(x_positions, focal_results, strict=True):
        ax_bar.text(
            x_value,
            result.lcot_2023_usd_per_kg + 0.012,
            rf"\${result.lcot_2023_usd_per_kg:.3f}",
            ha="center",
            va="bottom",
            fontsize=7.2,
            fontweight="semibold",
        )
    ax_bar.set_xticks(
        list(x_positions),
        ["External\nonly", "No\nredesign", "Joint\ndesign"],
    )
    ax_bar.set_ylabel("LCOT contribution (2023 USD/kg)")
    ax_bar.set_title(
        f"(b) Focal {FOCAL_BUFFER_HOURS:.0f} h cost mechanism",
    )
    ax_bar.set_axisbelow(True)
    ax_bar.grid(axis="y", color="#dddddd", linewidth=0.6)
    ax_bar.legend(
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
        columnspacing=0.8,
        handletextpad=0.35,
    )
    maximum = max(result.lcot_2023_usd_per_kg for result in focal_results)
    ax_bar.set_ylim(0.0, maximum * 1.15)
    fig.subplots_adjust(left=0.09, right=0.995, top=0.90, bottom=0.25)
    pdf_path = FIGURE_DIR / "mechanism.pdf"
    png_path = FIGURE_DIR / "mechanism.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    plt.close(fig)


def _tex_number(value: float | None, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "--"
    return f"{value:.{digits}f}"


def _write_counterfactual_table(
    focal: Sequence[model.SelectedResult],
    best_designs: Sequence[model.SelectedResult],
) -> None:
    joint = next(result for result in focal if result.strategy == "Joint design")
    near = [
        result
        for result in best_designs
        if result.diameter_in == joint.diameter_in
        and result.stations != joint.stations
    ][:2]
    near_text = ""
    if near:
        pieces = [
            (
                f"$n={result.stations}$ "
                f"(+{result.lcot_2023_usd_per_kg - joint.lcot_2023_usd_per_kg:.6f} "
                "USD/kg)"
            )
            for result in near
        ]
        near_text = "; ".join(pieces)
    lines = [
        r"\begin{table*}[!t]",
        r"\centering",
        (
            rf"\caption{{Three ways to supply the same buffer in the focal "
            rf"$L={FOCAL_LENGTH_KM:.0f}$ km, "
            rf"$H_{{\mathrm{{buf}}}}={FOCAL_BUFFER_HOURS:.0f}$ h, "
            rf"external-storage cost of "
            rf"{FOCAL_STORAGE_COST_2023_USD_PER_KG:.0f} USD/kg-capacity. "
            rf"Every row supplies the same "
            rf"{joint.required_buffer_kg / 1000.0:.1f} t buffer.}}"
        ),
        r"\label{tab:buffer_design_counterfactuals}",
        r"\small",
        r"\setlength{\tabcolsep}{4.5pt}",
        r"\begin{tabular}{lccccccc}",
        r"\toprule",
        (
            r"Strategy & Design $(D,n)$ & Enroute rating & $q$ "
            r"& Linepack & External & LCOT \\"
        ),
        (
            r" &  & (MW/unit) & (bar(a)) & (t) & storage (t) "
            r"& (2023 USD/kg) \\"
        ),
        r"\midrule",
    ]
    labels = {
        "External storage only": "External storage only",
        "Linepack without redesign": "Linepack, no redesign",
        "Joint design": "Joint design",
    }
    for result in focal:
        design = f"{result.diameter_in:.0f} in., {result.stations}"
        lines.append(
            " & ".join(
                [
                    labels[result.strategy],
                    design,
                    (
                        "--"
                        if result.stations == 0
                        else _tex_number(
                            result.enroute_rating_unit_kw / 1000.0,
                            2,
                        )
                    ),
                    _tex_number(result.q_bar_a, 2),
                    _tex_number(result.credited_linepack_kg / 1000.0, 1),
                    _tex_number(result.external_storage_kg / 1000.0, 1),
                    _tex_number(result.lcot_2023_usd_per_kg, 4),
                ]
            )
            + r" \\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            (
                r"\begin{minipage}{0.96\textwidth}\footnotesize "
                r"The no-redesign case freezes the transport-selected "
                r"diameter, station count, stages, and ratings and preserves "
                r"the common 15\% equipment sizing margin. The joint optimum "
                r"is locally flat in station count; nearby alternatives are "
                + near_text
                + r".\end{minipage}"
            ),
            r"\end{table*}",
            "",
        ]
    )
    (TABLE_DIR / "counterfactuals.tex").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_inputs_table(basis: model.StudyBasis) -> None:
    values = [
        ("Annual delivered hydrogen", "0.50 Mt/yr"),
        ("Capacity factor", "0.90"),
        (
            "Hydraulic design flow",
            f"{basis.design_flow_kg_per_day / 1.0e3:.1f} t/day",
        ),
        ("Source / contract / rated pressure", "20 / 20 / 70 bar(g)"),
        (
            "Corridor lengths",
            "400, 800, 1200, 1600, 2000 km",
        ),
        ("Equivalent buffer durations", "0, 6, 12, 24, 36, 48, 72 h"),
        (
            "Aggregate external-storage capacity cost",
            "100, 200, 600 constant-2023 USD/kg-capacity",
        ),
        (
            "Annual external-storage capacity cost",
            r"10, 20, 60 constant-2023 USD/(kg-capacity\,yr)",
        ),
        (
            "Diameter catalog",
            "4--42 in. (13 PiTEA sizes)",
        ),
        ("Minimum balanced segment length", "50 km"),
        (
            "Draft-pressure search",
            "241 points plus exact service and hardware-frontier roots",
        ),
        ("Annual capital charge", r"$0.08~\mathrm{yr}^{-1}$"),
        (
            "Pipeline / compressor / storage fixed charges",
            r"2.5 / 6.1 / 2.0\% of respective CAPEX/yr",
        ),
        (
            "Electricity tariff",
            "0.0804 USD/kWh on the 2018 basis, escalated to 2023",
        ),
    ]
    lines = [
        r"\begin{table}[!t]",
        r"\centering",
        r"\caption{Buffer-design experiment basis.}",
        r"\label{tab:buffer_design_inputs_si}",
        r"\small",
        r"\begin{tabularx}{\textwidth}{@{}lX@{}}",
        r"\toprule",
        r"Input & Value \\",
        r"\midrule",
    ]
    lines.extend(f"{label} & {value} \\\\" for label, value in values)
    lines.extend([r"\bottomrule", r"\end{tabularx}", r"\end{table}", ""])
    (TABLE_DIR / "inputs.tex").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_robustness_table(
    rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for annual_mt in (0.25, 0.50, 1.00):
        for storage_cost in (200.0, 600.0):
            subset = [
                row
                for row in rows
                if float(row["annual_delivery_mt_per_year"]) == annual_mt
                and float(row["storage_cost_2023_usd_per_kg"])
                == storage_cost
                and float(row["buffer_hours"]) > 0.0
            ]
            counts = {
                category: sum(
                    1
                    for row in subset
                    if row["joint_design_infrastructure_response"] == category
                )
                for category in (
                    "Transport assets retained",
                    "Compressor resize",
                    "Station-count change",
                    "Diameter change",
                )
            }
            summaries.append(
                {
                    "annual_mt": annual_mt,
                    "storage_cost": storage_cost,
                    "retained": counts["Transport assets retained"],
                    "compressor": counts["Compressor resize"],
                    "station": counts["Station-count change"],
                    "diameter": counts["Diameter change"],
                    "max_redesign": max(
                        float(row["delta_redesign_2023_usd_per_kg"])
                        for row in subset
                    ),
                }
            )
    lines = [
        r"\begin{table}[!t]",
        r"\centering",
        (
            r"\caption{Throughput robustness of the infrastructure-response "
            r"map. Counts are over the 30 positive-duration length--buffer "
            r"points at each storage cost.}"
        ),
        r"\label{tab:buffer_design_robustness_si}",
        r"\small",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{ccrrrrr}",
        r"\toprule",
        (
            r"Delivery & $a_{\mathrm{ext}}$ & Retained & Resize & "
            r"$\Delta n$ & $\Delta D$ & Max. redesign \\"
        ),
        (
            r"(Mt/yr) & (USD/kg-capacity) & "
            r"\multicolumn{4}{c}{number of points} "
            r"& (USD/kg) \\"
        ),
        r"\midrule",
    ]
    for summary in summaries:
        lines.append(
            (
                f"{summary['annual_mt']:.2f} & "
                f"{summary['storage_cost']:.0f} & "
                f"{summary['retained']} & {summary['compressor']} & "
                f"{summary['station']} & {summary['diameter']} & "
                f"{summary['max_redesign']:.3f} \\\\"
            )
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    (TABLE_DIR / "robustness.tex").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )
    return summaries


def _write_literature_table(rows: Sequence[dict[str, Any]]) -> None:
    lines = [
        r"\begin{table}[!t]",
        r"\centering",
        (
            r"\caption{Selected literature evidence for the buffer-design experiment. "
            r"The studies use different"
        ),
        (
            r"services and cost boundaries and are not direct benchmarks for PiTEA's "
            r"LCOT"
        ),
        (
            r"savings. Values retain their source currency and financial basis unless "
            r"a"
        ),
        r"conversion is explicitly stated.}",
        r"\label{tab:buffer_design_literature_si}",
        r"\scriptsize",
        r"\begin{tabularx}{\textwidth}{@{}p{0.16\textwidth}XXX@{}}",
        r"\toprule",
        r"Source & Service & Auditable result & Use in this paper \\",
        r"\midrule",
        (
            r"\citet{GPA2022} & 10 TJ/day, 500 km, 4 h linepack "
            r"& 0.658 base and 0.828 total AUD/kg; 0.170 AUD/kg increment "
            r"from rounded source tables (0.153 from the tariff equation) "
            r"& Prescribed-duration engineering check \\"
        ),
        (
            r"\citet{GPA2022} & 500 km, 24 h at 50--500 TJ/day "
            r"& 51.3--61.5 2021 USD/(kg-capacity yr) "
            r"& Annual-service scale check \\"
        ),
        (
            r"\citet{Purwanto2026} & 173 t/day with fixed seven-day storage "
            r"& 0.87, 1.30, 2.18 USD/kg over 100, 200, 400 km; dollar year not captured "
            r"& Fixed-external-buffer comparator only \\"
        ),
        (
            r"\citet{Karlberg2025} & Fixed 336.4 t linepack; optimized rock cavern "
            r"& 0.55 EUR/kg LCOT reported; ${\sim}$0.63 reconstructed "
            r"& Closest accounting boundary; fixed pipe \\"
        ),
        (
            r"UC Davis report \citep{Burke2024HydrogenStorageTransport} "
            r"& 100 km; packed/unpacked inlet conditions of 90/70 bar "
            r"& Reported pressure-state mass differences: 62.5, 151, 277 t for 24, 36, 48 in.; no auditable LCOT "
            r"& Physical scale check only \\"
        ),
        (
            r"\citet{Mhanna2023} & Joint linepack/UHS network design "
            r"& Tabulated NPV values imply a derived 21.6\% reduction "
            r"& Independent infrastructure-substitution evidence \\"
        ),
        (
            r"\citet{Allansson2025} & Joint pipeline, "
            r"compressor, linepack, and tank design "
            r"& Whole-chain LCOH; no isolated corridor LCOT "
            r"& Peer-reviewed architecture context \\"
        ),
        r"\bottomrule",
        r"\end{tabularx}",
        r"\end{table}",
        "",
    ]
    (TABLE_DIR / "literature.tex").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_q_audit_table(
    q_rows: Sequence[dict[str, Any]],
    rating_rows: Sequence[dict[str, Any]],
) -> None:
    lines = [
        r"\begin{table}[!t]",
        r"\centering",
        (
            r"\caption{Numerical and fixed-rating audit for the focal case. "
            r"Exact service and frozen-hardware frontier roots are added to "
            r"every pressure grid.}"
        ),
        r"\label{tab:buffer_design_numerical_audit_si}",
        r"\small",
        r"\begin{tabular}{rrrrrr}",
        r"\toprule",
        (
            r"$N_q$ & Fixed $q$ & Fixed LCOT & Joint $D$ & Joint $n$ & "
            r"Joint LCOT \\"
        ),
        r" & (bar(a)) & (USD/kg) & (in.) &  & (USD/kg) \\",
        r"\midrule",
    ]
    for row in q_rows:
        lines.append(
            (
                f"{int(row['q_grid_points'])} & "
                f"{float(row['linepack_without_redesign_q_bar_a']):.3f} & "
                f"{float(row['linepack_without_redesign_lcot_2023_usd_per_kg']):.6f} & "
                f"{float(row['joint_design_diameter_in']):.0f} & "
                f"{int(row['joint_design_stations'])} & "
                f"{float(row['joint_design_lcot_2023_usd_per_kg']):.6f} \\\\"
            )
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\vspace{3pt}",
            r"\begin{tabular}{lrrr}",
            r"\toprule",
            (
                r"Fixed-rating policy & Linepack (t) & External (t) "
                r"& LCOT (USD/kg) \\"
            ),
            r"\midrule",
        ]
    )
    for row in rating_rows:
        policy_tex = str(row["policy"]).replace("%", r"\%")
        lines.append(
            (
                f"{policy_tex} & "
                f"{float(row['credited_linepack_kg']) / 1000.0:.1f} & "
                f"{float(row['external_storage_kg']) / 1000.0:.1f} & "
                f"{float(row['lcot_2023_usd_per_kg']):.4f} \\\\"
            )
        )
    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table}", ""])
    (TABLE_DIR / "numerical_audit.tex").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _metrics(
    *,
    basis: model.StudyBasis,
    primary_rows: Sequence[dict[str, Any]],
    focal: Sequence[model.SelectedResult],
    best_designs: Sequence[model.SelectedResult],
    robustness_summaries: Sequence[dict[str, Any]],
    q_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    focal_lookup = {result.strategy: result for result in focal}
    external_storage_only = focal_lookup["External storage only"]
    fixed = focal_lookup["Linepack without redesign"]
    joint = focal_lookup["Joint design"]
    response_by_cost = {}
    for storage_cost in STORAGE_COSTS_2023_USD_PER_KG:
        subset = [
            row
            for row in primary_rows
            if float(row["storage_cost_2023_usd_per_kg"]) == storage_cost
        ]
        response_by_cost[str(int(storage_cost))] = _response_summary(subset)
    design_alternatives = [
        {
            "diameter_in": result.diameter_in,
            "stations": result.stations,
            "lcot_2023_usd_per_kg": result.lcot_2023_usd_per_kg,
            "gap_to_best_2023_usd_per_kg": (
                result.lcot_2023_usd_per_kg
                - best_designs[0].lcot_2023_usd_per_kg
            ),
        }
        for result in best_designs[:10]
    ]
    q_lcot = [
        float(row["joint_design_lcot_2023_usd_per_kg"]) for row in q_rows
    ]
    fixed_q_lcot = [
        float(row["linepack_without_redesign_lcot_2023_usd_per_kg"]) for row in q_rows
    ]
    return {
        "study_basis": {
            **asdict(basis),
            "design_flow_kg_per_day": basis.design_flow_kg_per_day,
            "average_delivery_kg_per_day": (
                basis.average_delivery_kg_per_day
            ),
            "diameters_in": list(DIAMETERS_IN),
            "lengths_km": list(LENGTHS_KM),
            "buffer_hours": list(BUFFER_HOURS),
            "storage_costs_2023_usd_per_kg": list(
                STORAGE_COSTS_2023_USD_PER_KG
            ),
            "linepack_without_redesign_policy": (
                "Freeze stages/ratings and preserve the 15% sizing margin"
            ),
        },
        "primary_dimensions": {
            "service_points": (
                len(LENGTHS_KM)
                * len(BUFFER_HOURS)
                * len(STORAGE_COSTS_2023_USD_PER_KG)
            ),
            "strategies": 3,
            "selected_rows": len(primary_rows),
        },
        "infrastructure_response_counts_positive_duration": response_by_cost,
        "focal_case": {
            "length_km": FOCAL_LENGTH_KM,
            "buffer_hours": FOCAL_BUFFER_HOURS,
            "storage_cost_2023_usd_per_kg": (
                FOCAL_STORAGE_COST_2023_USD_PER_KG
            ),
            "required_buffer_t": external_storage_only.required_buffer_kg / 1000.0,
            "external_storage_only_lcot_2023_usd_per_kg": (
                external_storage_only.lcot_2023_usd_per_kg
            ),
            "linepack_without_redesign_lcot_2023_usd_per_kg": fixed.lcot_2023_usd_per_kg,
            "joint_design_lcot_2023_usd_per_kg": joint.lcot_2023_usd_per_kg,
            "embedded_value_2023_usd_per_kg": (
                external_storage_only.lcot_2023_usd_per_kg
                - fixed.lcot_2023_usd_per_kg
            ),
            "redesign_value_2023_usd_per_kg": (
                fixed.lcot_2023_usd_per_kg
                - joint.lcot_2023_usd_per_kg
            ),
            "joint_saving_vs_external_storage_only_percent": (
                100.0
                * (
                    external_storage_only.lcot_2023_usd_per_kg
                    - joint.lcot_2023_usd_per_kg
                )
                / external_storage_only.lcot_2023_usd_per_kg
            ),
            "external_storage_only_design": [
                external_storage_only.diameter_in,
                external_storage_only.stations,
            ],
            "linepack_without_redesign_design": [fixed.diameter_in, fixed.stations],
            "joint_design": [joint.diameter_in, joint.stations],
            "linepack_without_redesign_linepack_t": fixed.credited_linepack_kg / 1000.0,
            "joint_design_linepack_t": joint.credited_linepack_kg / 1000.0,
            "joint_design_external_storage_t": (
                joint.external_storage_kg / 1000.0
            ),
            "joint_design_q_bar_a": joint.q_bar_a,
            "near_optimal_designs": design_alternatives,
        },
        "q_grid_audit": {
            "tested_points": [
                int(row["q_grid_points"]) for row in q_rows
            ],
            "maximum_joint_design_lcot_spread_2023_usd_per_kg": (
                max(q_lcot) - min(q_lcot)
            ),
            "maximum_linepack_without_redesign_lcot_spread_2023_usd_per_kg": (
                max(fixed_q_lcot) - min(fixed_q_lcot)
            ),
            "selected_designs": [
                [
                    float(row["joint_design_diameter_in"]),
                    int(row["joint_design_stations"]),
                ]
                for row in q_rows
            ],
        },
        "throughput_robustness_summary": list(robustness_summaries),
        "literature_audit": {
            "gpa_4h_increment_from_source_tables_aud_per_kg": 0.170,
            "gpa_4h_increment_from_tariff_aud_per_kg": (
                6.47 * 0.1418 * 4.0 / 24.0
            ),
            "invalid_survey_increment_aud_per_kg": 0.92,
            "uc_davis_cost_used_as_lcot": False,
        },
        "source_hashes": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in sorted((ROOT / "src" / "pipeline_model").glob("*.py"))
        },
    }


def main() -> None:
    _mkdirs()
    basis = model.StudyBasis(
        annual_delivered_kg=REFERENCE_ANNUAL_DELIVERY_KG,
        q_grid_points=Q_GRID_POINTS,
    )
    contexts, catalog_rows = _build_contexts(basis, LENGTHS_KM)
    primary_rows, focal, focal_ranking = _run_primary(basis, contexts)
    mechanism_rows, _ = _run_mechanism_slice(
        basis,
        contexts[FOCAL_LENGTH_KM],
    )
    best_designs = _best_per_design(focal_ranking)
    q_rows = _run_q_refinement()
    rating_rows = _run_rating_audit(
        basis,
        contexts[FOCAL_LENGTH_KM],
    )
    robustness_rows = _run_throughput_robustness()
    literature_rows = _literature_ledger()

    _write_csv(PRIMARY_RESULTS, primary_rows)
    _write_csv(CATALOG_RESULTS, catalog_rows)
    _write_csv(
        FOCAL_RESULTS,
        [
            _result_row(
                result,
                external_storage_only=focal[0],
                fixed=focal[1],
                joint=focal[2],
            )
            for result in focal
        ],
    )
    ranking_rows = []
    best_lcot = best_designs[0].lcot_2023_usd_per_kg
    for rank, result in enumerate(best_designs, start=1):
        row = result.to_dict()
        row.update(
            {
                "design_rank": rank,
                "gap_to_best_2023_usd_per_kg": (
                    result.lcot_2023_usd_per_kg - best_lcot
                ),
            }
        )
        ranking_rows.append(row)
    _write_csv(FOCAL_RANKING, ranking_rows)
    _write_csv(MECHANISM_RESULTS, mechanism_rows)
    _write_csv(ROBUSTNESS_RESULTS, robustness_rows)
    _write_csv(Q_REFINEMENT_RESULTS, q_rows)
    _write_csv(RATING_AUDIT_RESULTS, rating_rows)
    _write_csv(LITERATURE_RESULTS, literature_rows)

    _plot_regime_map(primary_rows)
    _plot_mechanism(mechanism_rows, focal)
    _write_counterfactual_table(focal, best_designs)
    _write_inputs_table(basis)
    robustness_summaries = _write_robustness_table(robustness_rows)
    _write_literature_table(literature_rows)
    _write_q_audit_table(q_rows, rating_rows)

    metrics = _metrics(
        basis=basis,
        primary_rows=primary_rows,
        focal=focal,
        best_designs=best_designs,
        robustness_summaries=robustness_summaries,
        q_rows=q_rows,
    )
    METRICS_RESULTS.write_text(
        json.dumps(metrics, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "primary_rows": len(primary_rows),
                "catalog_rows": len(catalog_rows),
                "robustness_rows": len(robustness_rows),
                "focal_joint_design": [
                    focal[2].diameter_in,
                    focal[2].stations,
                ],
                "focal_joint_design_lcot": focal[2].lcot_2023_usd_per_kg,
                "metrics": str(METRICS_RESULTS),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
