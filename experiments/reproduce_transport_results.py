"""Reproduce the transport design and cost results.

The calculation has three stages:

1. Read the included PiTEA and reconstructed H2P candidate ledgers.
2. Remove the H2_P_COM break-even-price finance wrapper and rank both candidate
   sets with the same annualized LCOT equation.
3. Recompute the 30-case diameter surface directly with PiTEA.

The printed H2_P_COM break-even prices are not multiplied by a conversion
factor.  They validate the H2_P_COM source reconstruction; the LCOT values are
then derived from the reconstructed capital and operating-cost ledgers.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
import statistics
import sys


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipeline_model as model  # noqa: E402


OUTPUT_ROOT = ROOT / "outputs" / "transport_results"
DATA = OUTPUT_ROOT / "data"
TABLES = OUTPUT_ROOT / "tables"
FIGURES = OUTPUT_ROOT / "figures"
INPUT_DATA = ROOT / "data" / "transport_validation"

PITEA_SOURCE = INPUT_DATA / "pitea_candidates.csv"
H2P_SOURCE = INPUT_DATA / "h2p_reconstructed_candidates.csv"
H2P_TARGETS = INPUT_DATA / "h2p_bep_targets.csv"
DIAMETER_TARGETS = INPUT_DATA / "exhibit45_published_diameters.csv"
DIAMETERS = DATA / "diameter_comparison.csv"

ANNUAL_CAPITAL_CHARGE_FACTOR = 0.08
CAPACITY_FACTOR = 0.90
H2P_CONTINGENCY_FRACTION = 0.15
ESCALATION_2011_TO_2023 = 1.048**12
BROWN_2018_TO_2011 = 544.0 / 660.0
ESCALATION_2018_TO_2023 = (
    BROWN_2018_TO_2011 * ESCALATION_2011_TO_2023
)

PITEA_CANDIDATES_OUT = DATA / "pitea_lcot_candidates.csv"
H2P_CANDIDATES_OUT = DATA / "h2p_derived_lcot_candidates.csv"
SELECTED_OUT = DATA / "selected_designs.csv"
COMPARISON_OUT = DATA / "lcot_comparison.csv"
ATTRIBUTION_OUT = DATA / "fixed_design_attribution.csv"
METRICS_OUT = DATA / "metrics.json"
PITEA_RECOMPUTATION_AUDIT_OUT = DATA / "pitea_recomputation_audit.json"

PSI_TO_BAR = 0.0689475729317831
# The 48-case LCOT benchmark follows H2P Exhibit 4-4.
BENCHMARK_INLET_PRESSURE_PSIG = 1000.0
BENCHMARK_OUTLET_PRESSURE_PSIG = 705.0
# The separate 30-case diameter comparison follows H2P Exhibit 4-5.
INLET_PRESSURE_PSIG = 1015.0
OUTLET_PRESSURE_PSIG = 500.0
DIAMETERS_IN = (4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0,
                20.0, 24.0, 30.0, 36.0, 42.0)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write an empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_diameter_surface() -> list[dict[str, object]]:
    """Recompute the 30 H2P Exhibit 4-5 diameter-comparison cases."""

    published = read_csv(DIAMETER_TARGETS)
    if len(published) != 30:
        raise AssertionError(
            f"Expected 30 published diameter cases, found {len(published)}"
        )

    outputs: list[dict[str, object]] = []
    inlet_barg = INLET_PRESSURE_PSIG * PSI_TO_BAR
    outlet_barg = OUTLET_PRESSURE_PSIG * PSI_TO_BAR
    for target in published:
        length_mi = float(target["length_mi"])
        capacity = float(target["capacity_mt_per_year"])
        case_id = f"DIA_Q{capacity:.2f}_L{int(length_mi):04d}"
        basis = model.StudyBasis(
            annual_delivered_kg=capacity * 1.0e9,
            capacity_factor=CAPACITY_FACTOR,
            source_pressure_g_bar=inlet_barg,
            contract_pressure_g_bar=outlet_barg,
            rated_pressure_g_bar=inlet_barg,
            q_grid_points=101,
        )
        catalog = model.build_transport_catalog(
            basis=basis,
            length_km=length_mi * 1.609344,
            diameters_in=DIAMETERS_IN,
        )
        selected = model.select_transport(catalog)
        outputs.append(
            {
                "case_id": case_id,
                "length_mi": length_mi,
                "capacity_mt_per_year": capacity,
                "capacity_factor": CAPACITY_FACTOR,
                "inlet_pressure_psig": INLET_PRESSURE_PSIG,
                "outlet_pressure_psig": OUTLET_PRESSURE_PSIG,
                "pipeline_om_fraction": 0.025,
                "compressibility_model": "PiTEA pressure-dependent Z",
                "hdsam_diameter_in_reported_by_h2p": float(
                    target["hdsam_diameter_in"]
                ),
                "h2p_diameter_in": float(target["h2p_diameter_in"]),
                "pitea_diameter_in": selected.diameter_in,
                "pitea_station_count_enroute": selected.stations,
                "pitea_lcot_2023_usd_per_kg": (
                    selected.transport_lcot_2023_usd_per_kg
                ),
            }
        )
    outputs.sort(
        key=lambda row: (
            float(row["capacity_mt_per_year"]),
            float(row["length_mi"]),
        )
    )
    write_csv(DIAMETERS, outputs)
    return outputs


def verify_pitea_candidate_recomputation() -> dict[str, object]:
    """Recompute every PiTEA candidate used by the 48-case benchmark.

    The candidate ledger retains the BEP-selection flag
    needed for the objective-switch audit. All physical feasibility and every
    capital and operating-cost field consumed by the LCOT calculation are
    independently rebuilt here from ``pipeline_model``.
    """

    source_rows = read_csv(PITEA_SOURCE)
    grouped: dict[tuple[str, float, float], list[dict[str, str]]] = defaultdict(list)
    for row in source_rows:
        grouped[
            (
                row["case_id"],
                float(row["length_mi"]),
                float(row["capacity_mt_per_year"]),
            )
        ].append(row)

    inlet_barg = BENCHMARK_INLET_PRESSURE_PSIG * PSI_TO_BAR
    outlet_barg = BENCHMARK_OUTLET_PRESSURE_PSIG * PSI_TO_BAR
    conversion_2018_to_2011 = BROWN_2018_TO_2011
    maximum_relative_residual = 0.0
    feasible_count = 0

    for (case_id, length_mi, capacity), rows in grouped.items():
        basis = model.StudyBasis(
            annual_delivered_kg=capacity * 1.0e9,
            capacity_factor=CAPACITY_FACTOR,
            source_pressure_g_bar=inlet_barg,
            contract_pressure_g_bar=outlet_barg,
            rated_pressure_g_bar=inlet_barg,
            q_grid_points=101,
        )
        try:
            catalog = model.build_transport_catalog(
                basis=basis,
                length_km=length_mi * 1.609344,
                diameters_in=DIAMETERS_IN,
            )
        except RuntimeError as error:
            if "No feasible transport candidates" not in str(error):
                raise
            catalog = []
        computed = {
            (candidate.diameter_in, candidate.stations): candidate
            for candidate in catalog
        }
        expected_feasible = {
            (
                float(row["pitea_nominal_and_internal_diameter_in"]),
                int(row["station_count_enroute"]),
            )
            for row in rows
            if as_bool(row["feasible"])
        }
        if set(computed) != expected_feasible:
            raise AssertionError(f"PiTEA feasibility map changed for {case_id}")

        feasible_count += len(computed)
        for row in rows:
            if not as_bool(row["feasible"]):
                continue
            key = (
                float(row["pitea_nominal_and_internal_diameter_in"]),
                int(row["station_count_enroute"]),
            )
            candidate = computed[key]
            esc = basis.escalation_2018_to_2023
            expected = {
                "capex_pipeline_subtotal_2011_usd": (
                    candidate.pipeline_cost.capex_pipe_usd
                    * conversion_2018_to_2011
                ),
                "capex_compressor_2011_usd": (
                    candidate.compressor_capex_2018_usd
                    * conversion_2018_to_2011
                ),
                "annual_pipeline_om_2023_usd": (
                    basis.pipeline_fixed_om_fraction
                    * candidate.pipeline_cost.capex_pipe_usd
                    * esc
                ),
                "annual_compressor_fixed_2023_usd": (
                    basis.compressor_fixed_om_fraction
                    * candidate.compressor_capex_2018_usd
                    * esc
                ),
                "annual_electricity_2023_usd": (
                    basis.capacity_factor
                    * candidate.full_year_energy_kwh
                    * basis.electricity_2018_usd_per_kwh
                    * esc
                ),
            }
            expected["annual_total_opex_2023_usd"] = sum(
                expected[field]
                for field in (
                    "annual_pipeline_om_2023_usd",
                    "annual_compressor_fixed_2023_usd",
                    "annual_electricity_2023_usd",
                )
            )
            for field, observed in expected.items():
                reference = float(row[field])
                scale = max(1.0, abs(reference))
                relative_residual = abs(observed - reference) / scale
                maximum_relative_residual = max(
                    maximum_relative_residual,
                    relative_residual,
                )
                if not math.isclose(
                    observed,
                    reference,
                    rel_tol=1.0e-12,
                    abs_tol=1.0e-6,
                ):
                    raise AssertionError(
                        f"PiTEA recomputation changed {case_id} {key} {field}: "
                        f"{observed!r} != {reference!r}"
                    )

    audit = {
        "case_count": len(grouped),
        "candidate_count": len(source_rows),
        "feasible_candidate_count": feasible_count,
        "fields_recomputed": [
            "physical feasibility",
            "pipeline CAPEX",
            "compressor CAPEX",
            "pipeline fixed O&M",
            "compressor fixed charges",
            "electricity",
            "annual total OPEX",
        ],
        "maximum_scaled_residual": maximum_relative_residual,
        "status": "pass",
    }
    PITEA_RECOMPUTATION_AUDIT_OUT.write_text(
        json.dumps(audit, indent=2) + "\n",
        encoding="utf-8",
    )
    return audit


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def as_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def annual_mass_kg(capacity_mt_per_year: float) -> float:
    return capacity_mt_per_year * 1.0e9


def lcot_components(
    capex_2023_usd: float,
    opex_2023_usd_per_year: float,
    capacity_mt_per_year: float,
) -> tuple[float, float, float]:
    annual_mass = annual_mass_kg(capacity_mt_per_year)
    capital = ANNUAL_CAPITAL_CHARGE_FACTOR * capex_2023_usd / annual_mass
    operating = opex_2023_usd_per_year / annual_mass
    return capital, operating, capital + operating


def build_pitea_candidates() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for source in read_csv(PITEA_SOURCE):
        feasible = as_bool(source["feasible"])
        row: dict[str, object] = {
            "model": "PiTEA",
            "case_id": source["case_id"],
            "length_mi": float(source["length_mi"]),
            "capacity_mt_per_year": float(source["capacity_mt_per_year"]),
            "capacity_factor": float(source["capacity_factor"]),
            "diameter_in": float(
                source["pitea_nominal_and_internal_diameter_in"]
            ),
            "station_count_enroute": int(source["station_count_enroute"]),
            "eligible_for_lcot_selection": feasible,
            "source_bep_selected": as_bool(source["selected"]),
            "capex_precontingency_2023_usd": "",
            "annual_opex_2023_usd": "",
            "lcot_capital_2023_usd_per_kg": "",
            "lcot_opex_2023_usd_per_kg": "",
            "lcot_2023_usd_per_kg": "",
            "lcot_rank": "",
            "lcot_selected": False,
        }
        if feasible:
            # The source ledger stores PiTEA 2018-dollar components after
            # conversion to 2011 dollars for the BEP bridge.  Escalating those
            # pre-contingency components to 2023 preserves PiTEA's
            # equipment boundary without importing the BEP contingency.
            capex_2011 = float(
                source["capex_pipeline_subtotal_2011_usd"]
            ) + float(source["capex_compressor_2011_usd"])
            capex_2023 = capex_2011 * ESCALATION_2011_TO_2023
            opex_2023 = float(source["annual_total_opex_2023_usd"])
            capital, operating, total = lcot_components(
                capex_2023,
                opex_2023,
                float(source["capacity_mt_per_year"]),
            )
            row.update(
                {
                    "capex_precontingency_2023_usd": capex_2023,
                    "annual_opex_2023_usd": opex_2023,
                    "lcot_capital_2023_usd_per_kg": capital,
                    "lcot_opex_2023_usd_per_kg": operating,
                    "lcot_2023_usd_per_kg": total,
                }
            )
        output.append(row)

    by_case: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in output:
        if bool(row["eligible_for_lcot_selection"]):
            by_case[str(row["case_id"])].append(row)
    for rows in by_case.values():
        ordered = sorted(
            rows,
            key=lambda row: (
                float(row["lcot_2023_usd_per_kg"]),
                float(row["diameter_in"]),
                int(row["station_count_enroute"]),
            ),
        )
        for rank, row in enumerate(ordered, start=1):
            row["lcot_rank"] = rank
        ordered[0]["lcot_selected"] = True
    return output


def build_h2p_candidates() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    source_rows = read_csv(H2P_SOURCE)
    targets = {row["case_id"]: row for row in read_csv(H2P_TARGETS)}
    selected_bep = [row for row in source_rows if as_bool(row["selected"])]
    if len(source_rows) != 576 or len(selected_bep) != 48:
        raise AssertionError("Unexpected H2P reconstruction dimensions.")
    for row in selected_bep:
        published = float(
            targets[row["case_id"]]["published_2023_usd_per_t"]
        )
        reconstructed = float(
            row["break_even_first_project_year_2023_usd_per_t"]
        )
        if abs(reconstructed - published) >= 0.005:
            raise AssertionError(
                f"H2P Exhibit 4-4 reproduction failed for {row['case_id']}."
            )

    for source in source_rows:
        source_evaluated = as_bool(source["evaluated_by_h2p_macro"])
        # H2_P_COM's reported project CAPEX includes a 15% contingency.
        # Divide it out to match PiTEA's pre-contingency LCOT boundary.  This
        # is an explicit accounting harmonization, not a claim that
        # contingency is a financing cash flow.
        capex_2023 = float(source["total_capex_2023_usd"]) / (
            1.0 + H2P_CONTINGENCY_FRACTION
        )
        opex_2023 = sum(
            float(source[field])
            for field in (
                "annual_pipeline_om_2023_usd",
                "annual_station_and_control_om_2023_usd",
                "annual_electricity_2023_usd",
            )
        )
        capital, operating, total = lcot_components(
            capex_2023,
            opex_2023,
            float(source["capacity_mt_per_year"]),
        )
        output.append(
            {
                "model": "H2P-derived",
                "case_id": source["case_id"],
                "length_mi": float(source["length_mi"]),
                "capacity_mt_per_year": float(
                    source["capacity_mt_per_year"]
                ),
                "capacity_factor": float(source["capacity_factor"]),
                "diameter_in": float(source["nominal_diameter_in"]),
                "station_count_enroute": int(source["station_count"]),
                "eligible_for_lcot_selection": source_evaluated,
                "source_bep_selected": as_bool(source["selected"]),
                "capex_precontingency_2023_usd": capex_2023,
                "annual_opex_2023_usd": opex_2023,
                "lcot_capital_2023_usd_per_kg": capital,
                "lcot_opex_2023_usd_per_kg": operating,
                "lcot_2023_usd_per_kg": total,
                "lcot_rank": "",
                "lcot_selected": False,
            }
        )

    by_case: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in output:
        if bool(row["eligible_for_lcot_selection"]):
            by_case[str(row["case_id"])].append(row)
    for rows in by_case.values():
        ordered = sorted(
            rows,
            key=lambda row: (
                float(row["lcot_2023_usd_per_kg"]),
                float(row["diameter_in"]),
                int(row["station_count_enroute"]),
            ),
        )
        for rank, row in enumerate(ordered, start=1):
            row["lcot_rank"] = rank
        ordered[0]["lcot_selected"] = True

    # The source macro does not visit some catalog sizes after its screening
    # rule triggers.  The reconstructed ledgers nevertheless cover the full
    # catalog. Verify that expanding to all sizes would not change any LCOT
    # optimum.
    complete_by_case: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in output:
        complete_by_case[str(row["case_id"])].append(row)
    for case_id, rows in complete_by_case.items():
        complete_best = min(
            rows,
            key=lambda row: (
                float(row["lcot_2023_usd_per_kg"]),
                float(row["diameter_in"]),
                int(row["station_count_enroute"]),
            ),
        )
        source_best = next(
            row
            for row in rows
            if bool(row["lcot_selected"])
        )
        if (
            float(complete_best["diameter_in"]),
            int(complete_best["station_count_enroute"]),
        ) != (
            float(source_best["diameter_in"]),
            int(source_best["station_count_enroute"]),
        ):
            raise AssertionError(
                f"Source-screen and full-catalog LCOT optima differ for {case_id}."
            )
    return output


def selected_lookup(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        str(row["case_id"]): row
        for row in rows
        if bool(row["lcot_selected"])
    }


def build_comparison(
    pitea_rows: list[dict[str, object]],
    h2p_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    pitea = selected_lookup(pitea_rows)
    h2p = selected_lookup(h2p_rows)
    targets = {row["case_id"]: row for row in read_csv(H2P_TARGETS)}
    pitea_cases = sorted(
        {
            (
                str(row["case_id"]),
                float(row["length_mi"]),
                float(row["capacity_mt_per_year"]),
            )
            for row in pitea_rows
        },
        key=lambda item: (item[1], item[2]),
    )
    comparison: list[dict[str, object]] = []
    selected: list[dict[str, object]] = []
    for case_id, length, capacity in pitea_cases:
        h2p_row = h2p[case_id]
        pitea_row = pitea.get(case_id)
        target = targets[case_id]
        record: dict[str, object] = {
            "case_id": case_id,
            "length_mi": length,
            "capacity_mt_per_year": capacity,
            "capacity_factor": CAPACITY_FACTOR,
            "pitea_feasible": pitea_row is not None,
            "pitea_lcot_2023_usd_per_kg": "",
            "pitea_diameter_in": "",
            "pitea_station_count_enroute": "",
            "pitea_lcot_design_differs_from_bep": "",
            "h2p_derived_lcot_2023_usd_per_kg": float(
                h2p_row["lcot_2023_usd_per_kg"]
            ),
            "h2p_diameter_in": float(h2p_row["diameter_in"]),
            "h2p_station_count_enroute": int(
                h2p_row["station_count_enroute"]
            ),
            "h2p_lcot_design_differs_from_bep": not bool(
                h2p_row["source_bep_selected"]
            ),
            "h2p_published_bep_2023_usd_per_t": float(
                target["published_2023_usd_per_t"]
            ),
            "h2p_minus_pitea_lcot_2023_usd_per_kg": "",
            "pitea_minus_h2p_relative_difference_pct": "",
        }
        if pitea_row is not None:
            p_lcot = float(pitea_row["lcot_2023_usd_per_kg"])
            h_lcot = float(h2p_row["lcot_2023_usd_per_kg"])
            record.update(
                {
                    "pitea_lcot_2023_usd_per_kg": p_lcot,
                    "pitea_diameter_in": float(pitea_row["diameter_in"]),
                    "pitea_station_count_enroute": int(
                        pitea_row["station_count_enroute"]
                    ),
                    "pitea_lcot_design_differs_from_bep": not bool(
                        pitea_row["source_bep_selected"]
                    ),
                    "h2p_minus_pitea_lcot_2023_usd_per_kg": h_lcot
                    - p_lcot,
                    "pitea_minus_h2p_relative_difference_pct": 100.0
                    * (p_lcot - h_lcot)
                    / h_lcot,
                }
            )
            selected.append(dict(pitea_row))
        selected.append(dict(h2p_row))
        comparison.append(record)
    return comparison, selected


def make_lcot_table(comparison: list[dict[str, object]]) -> None:
    by_case = {
        (float(row["length_mi"]), float(row["capacity_mt_per_year"])): row
        for row in comparison
    }
    lengths = (10, 25, 75, 100, 200, 300, 400, 500, 750, 1000, 1250, 1500)
    capacities = (0.25, 0.50, 1.00, 5.00)
    lines = [
        r"\begin{tabular}{@{}rlrrrr@{}}",
        r"\toprule",
        r"Length & & \multicolumn{4}{c}{Transport capacity (Mt/yr)} \\",
        r"\cmidrule(l){3-6}",
        r"(mile) & Model & 0.25 & 0.50 & 1.00 & 5.00 \\",
        r"\midrule",
    ]
    for length in lengths:
        pitea_values: list[str] = []
        h2p_values: list[str] = []
        for capacity in capacities:
            row = by_case[(float(length), capacity)]
            if bool(row["pitea_feasible"]):
                pitea_values.append(
                    f"{float(row['pitea_lcot_2023_usd_per_kg']):.5f}"
                )
            else:
                pitea_values.append(r"\multicolumn{1}{c}{--}")
            h2p_values.append(
                f"{float(row['h2p_derived_lcot_2023_usd_per_kg']):.5f}"
            )
        lines.append(
            f"{length} & PiTEA & " + " & ".join(pitea_values) + r" \\"
        )
        lines.append(
            r" & H$_2$P-derived & " + " & ".join(h2p_values) + r" \\"
        )
        if length != lengths[-1]:
            lines.append(r"\addlinespace[2pt]")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TABLES / "lcot_matrix.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def make_diameter_table(diameters: list[dict[str, str]]) -> None:
    by_case = {
        (float(row["length_mi"]), float(row["capacity_mt_per_year"])): row
        for row in diameters
    }
    capacities = (0.22, 1.10, 2.20)
    lines = [
        r"\begin{tabular}{@{}r*{3}{rrr}@{}}",
        r"\toprule",
        (
            r"Length & \multicolumn{3}{c}{0.22 Mt/yr} "
            r"& \multicolumn{3}{c}{1.10 Mt/yr} "
            r"& \multicolumn{3}{c}{2.20 Mt/yr} \\"
        ),
        r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}\cmidrule(l){8-10}",
        (
            r"(mile) & HDSAM & H$_2$P & PiTEA "
            r"& HDSAM & H$_2$P & PiTEA "
            r"& HDSAM & H$_2$P & PiTEA \\"
        ),
        r"\midrule",
    ]
    for length in range(100, 1001, 100):
        values: list[str] = []
        for capacity in capacities:
            row = by_case[(float(length), capacity)]
            values.extend(
                [
                    f"{float(row['hdsam_diameter_in_reported_by_h2p']):.2f}",
                    f"{float(row['h2p_diameter_in']):.0f}",
                    f"{float(row['pitea_diameter_in']):.0f}",
                ]
            )
        lines.append(f"{length} & " + " & ".join(values) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TABLES / "diameter_comparison.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def make_representative_table(
    selected_rows: list[dict[str, object]],
) -> dict[str, object]:
    lookup = {
        (str(row["case_id"]), str(row["model"])): row
        for row in selected_rows
    }
    cases = (
        ("BEP_Q025_L0010", "10 mi, 0.25 Mt/yr"),
        ("BEP_Q100_L1000", "1000 mi, 1.00 Mt/yr"),
    )

    def design(row: dict[str, object]) -> str:
        return (
            f"{float(row['diameter_in']):.0f} in., "
            f"{int(row['station_count_enroute'])}"
        )

    p0 = lookup[(cases[0][0], "PiTEA")]
    h0 = lookup[(cases[0][0], "H2P-derived")]
    p1 = lookup[(cases[1][0], "PiTEA")]
    h1 = lookup[(cases[1][0], "H2P-derived")]
    lines = [
        r"\begin{tabular}{@{}lrrrr@{}}",
        r"\toprule",
        (
            r"& \multicolumn{2}{c}{10 mi, 0.25 Mt/yr} "
            r"& \multicolumn{2}{c}{1000 mi, 1.00 Mt/yr} \\"
        ),
        r"\cmidrule(lr){2-3}\cmidrule(l){4-5}",
        r"Metric & PiTEA & H$_2$P-derived & PiTEA & H$_2$P-derived \\",
        r"\midrule",
        (
            "Diameter / stations"
            f" & {design(p0)} & {design(h0)}"
            f" & {design(p1)} & {design(h1)}"
            r" \\"
        ),
        (
            r"LCOT (USD/kg)"
            f" & {float(p0['lcot_2023_usd_per_kg']):.5f}"
            f" & {float(h0['lcot_2023_usd_per_kg']):.5f}"
            f" & {float(p1['lcot_2023_usd_per_kg']):.5f}"
            f" & {float(h1['lcot_2023_usd_per_kg']):.5f}"
            r" \\"
        ),
        (
            r"CAPEX (million USD)"
            f" & {float(p0['capex_precontingency_2023_usd']) / 1e6:.2f}"
            f" & {float(h0['capex_precontingency_2023_usd']) / 1e6:.2f}"
            f" & {float(p1['capex_precontingency_2023_usd']) / 1e6:.2f}"
            f" & {float(h1['capex_precontingency_2023_usd']) / 1e6:.2f}"
            r" \\"
        ),
        (
            r"Annual OPEX (million USD/yr)"
            f" & {float(p0['annual_opex_2023_usd']) / 1e6:.3f}"
            f" & {float(h0['annual_opex_2023_usd']) / 1e6:.3f}"
            f" & {float(p1['annual_opex_2023_usd']) / 1e6:.2f}"
            f" & {float(h1['annual_opex_2023_usd']) / 1e6:.2f}"
            r" \\"
        ),
        r"\bottomrule",
        r"\end{tabular}",
    ]
    (TABLES / "representative_costs.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    return {
        case_id: {
            model: {
                key: row[key]
                for key in (
                    "diameter_in",
                    "station_count_enroute",
                    "lcot_2023_usd_per_kg",
                    "capex_precontingency_2023_usd",
                    "annual_opex_2023_usd",
                )
            }
            for model, row in (
                ("PiTEA", lookup[(case_id, "PiTEA")]),
                ("H2P-derived", lookup[(case_id, "H2P-derived")]),
            )
        }
        for case_id, _ in cases
    }


def source_row_lookups() -> tuple[
    dict[tuple[str, float, int], dict[str, str]],
    dict[tuple[str, float, int], dict[str, str]],
]:
    pitea = {
        (
            row["case_id"],
            float(row["pitea_nominal_and_internal_diameter_in"]),
            int(row["station_count_enroute"]),
        ): row
        for row in read_csv(PITEA_SOURCE)
        if as_bool(row["feasible"])
    }
    h2p = {
        (
            row["case_id"],
            float(row["nominal_diameter_in"]),
            int(row["station_count"]),
        ): row
        for row in read_csv(H2P_SOURCE)
    }
    return pitea, h2p


def fixed_design_attribution(
    comparison: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, float]]:
    pitea_source, h2p_source = source_row_lookups()
    matched = [
        row
        for row in comparison
        if bool(row["pitea_feasible"])
        and float(row["pitea_diameter_in"]) == float(row["h2p_diameter_in"])
        and int(row["pitea_station_count_enroute"])
        == int(row["h2p_station_count_enroute"])
    ]
    output: list[dict[str, object]] = []
    for case in matched:
        case_id = str(case["case_id"])
        diameter = float(case["pitea_diameter_in"])
        stations = int(case["pitea_station_count_enroute"])
        capacity = float(case["capacity_mt_per_year"])
        mass = annual_mass_kg(capacity)
        p = pitea_source[(case_id, diameter, stations)]
        h = h2p_source[(case_id, diameter, stations)]

        p_pipe_capex = (
            float(p["capex_pipeline_subtotal_2011_usd"])
            * ESCALATION_2011_TO_2023
        )
        p_comp_capex = (
            float(p["capex_compressor_2011_usd"])
            * ESCALATION_2011_TO_2023
        )
        p_pipeline_om = float(p["annual_pipeline_om_2023_usd"])
        p_comp_fixed = float(p["annual_compressor_fixed_2023_usd"])
        p_electricity = float(p["annual_electricity_2023_usd"])

        h_pipe_capex = (
            sum(
                float(h[field])
                for field in (
                    "pipeline_material_2011_usd",
                    "pipeline_labor_2011_usd",
                    "pipeline_row_2011_usd",
                    "pipeline_misc_2011_usd",
                )
            )
            * ESCALATION_2011_TO_2023
        )
        h_comp_capex = (
            float(h["compressor_capex_2011_usd"])
            * ESCALATION_2011_TO_2023
        )
        h_control_capex = (
            float(h["control_and_surge_capex_2011_usd"])
            * ESCALATION_2011_TO_2023
        )
        h_pipeline_om = 0.025 * h_pipe_capex
        h_comp_fixed = 0.04 * h_comp_capex
        h_electricity = float(h["annual_electricity_2023_usd"])
        h_total_opex = sum(
            float(h[field])
            for field in (
                "annual_pipeline_om_2023_usd",
                "annual_station_and_control_om_2023_usd",
                "annual_electricity_2023_usd",
            )
        )

        contributions = {
            "pipeline_capex": (
                ANNUAL_CAPITAL_CHARGE_FACTOR
                * (h_pipe_capex - p_pipe_capex)
                / mass
            ),
            "compressor_capex": (
                ANNUAL_CAPITAL_CHARGE_FACTOR
                * (h_comp_capex - p_comp_capex)
                / mass
            ),
            "pipeline_om": (h_pipeline_om - p_pipeline_om) / mass,
            "compressor_fixed_om": (h_comp_fixed - p_comp_fixed) / mass,
            "electricity": (h_electricity - p_electricity) / mass,
        }
        p_lcot = float(case["pitea_lcot_2023_usd_per_kg"])
        h_lcot = float(case["h2p_derived_lcot_2023_usd_per_kg"])
        gap = h_lcot - p_lcot
        contributions["other"] = gap - sum(contributions.values())
        closure = sum(contributions.values()) - gap
        if abs(closure) > 1.0e-9:
            raise AssertionError(f"LCOT attribution does not close for {case_id}.")
        # The residual consists of H2P control/surge CAPEX and O&M.  Preserve
        # the explicit check so a future change in that boundary cannot hide in
        # the grouped display.
        explicit_other = (
            ANNUAL_CAPITAL_CHARGE_FACTOR * h_control_capex
            + h_total_opex
            - h_pipeline_om
            - h_comp_fixed
            - h_electricity
        ) / mass
        if abs(explicit_other - contributions["other"]) > 1.0e-7:
            raise AssertionError(
                f"Other-component audit does not close for {case_id}."
            )
        output.append(
            {
                "case_id": case_id,
                "length_mi": float(case["length_mi"]),
                "capacity_mt_per_year": capacity,
                "diameter_in": diameter,
                "station_count_enroute": stations,
                "h2p_minus_pitea_lcot_2023_usd_per_kg": gap,
                **{
                    f"{name}_contribution_2023_usd_per_kg": value
                    for name, value in contributions.items()
                },
                "closure_residual_2023_usd_per_kg": closure,
            }
        )
    means = {
        name: statistics.mean(
            float(row[f"{name}_contribution_2023_usd_per_kg"])
            for row in output
        )
        for name in (
            "pipeline_capex",
            "compressor_capex",
            "pipeline_om",
            "compressor_fixed_om",
            "electricity",
            "other",
        )
    }
    means["gap"] = statistics.mean(
        float(row["h2p_minus_pitea_lcot_2023_usd_per_kg"])
        for row in output
    )
    return output, means


def make_attribution_figure(means: dict[str, float]) -> dict[str, float]:
    grouped = {
        "Electricity": means["electricity"],
        "Compressor CAPEX": means["compressor_capex"],
        "Compressor O&M": means["compressor_fixed_om"],
        "Other": (
            means["pipeline_capex"]
            + means["pipeline_om"]
            + means["other"]
        ),
    }
    if abs(sum(grouped.values()) - means["gap"]) > 1.0e-8:
        raise AssertionError("Grouped LCOT attribution does not close.")
    labels = list(grouped)
    y_positions = (3.2, 2.2, 1.2, 0.2)
    lines = [
        r"\begin{tikzpicture}[x=1.30cm,y=0.78cm,font=\small]",
        r"\draw[->,gray!70] (0,-0.35) -- (4.30,-0.35);",
    ]
    for tick in range(5):
        tick_label = "0" if tick == 0 else f"{tick / 1000.0:.3f}"
        lines.append(
            rf"\draw[gray!55] ({tick},-0.42) -- ({tick},-0.28) "
            rf"node[below=2pt,text=black] {{{tick_label}}};"
        )
    for label, y in zip(labels, y_positions):
        value = grouped[label]
        plotted_value = 1000.0 * value
        lines.append(
            rf"\node[anchor=east] at (-0.12,{y}) "
            rf"{{{label.replace('&', r'\&')}}};"
        )
        lines.append(
            rf"\fill[blue!58!black] (0,{y - 0.28:.2f}) "
            rf"rectangle ({plotted_value:.6f},{y + 0.28:.2f});"
        )
        lines.append(
            rf"\node[anchor=west] at ({plotted_value + 0.06:.6f},{y}) "
            rf"{{{value:.5f}}};"
        )
    lines += [
        r"\node[anchor=north] at (2.15,-0.82) "
        r"{Contribution to H$_2$P-derived--PiTEA LCOT difference (2023 USD/kg)};",
        r"\end{tikzpicture}",
    ]
    (FIGURES / "lcot_cost_components.tex").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return grouped


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    recomputation_audit = verify_pitea_candidate_recomputation()
    diameters = build_diameter_surface()
    pitea_candidates = build_pitea_candidates()
    h2p_candidates = build_h2p_candidates()
    comparison, selected = build_comparison(pitea_candidates, h2p_candidates)
    if (
        len(pitea_candidates) != 10_088
        or sum(
            bool(row["eligible_for_lcot_selection"])
            for row in pitea_candidates
        )
        != 2_751
    ):
        raise AssertionError("Unexpected PiTEA candidate dimensions.")
    if len(comparison) != 48 or len(selected) != 86:
        raise AssertionError("Unexpected LCOT selected-result dimensions.")
    if len(diameters) != 30:
        raise AssertionError("Expected 30 Exhibit 4-5 diameter cases.")

    write_csv(PITEA_CANDIDATES_OUT, pitea_candidates)
    write_csv(H2P_CANDIDATES_OUT, h2p_candidates)
    write_csv(SELECTED_OUT, selected)
    write_csv(COMPARISON_OUT, comparison)
    make_lcot_table(comparison)
    make_diameter_table(diameters)
    representative = make_representative_table(selected)
    attribution_rows, attribution_means = fixed_design_attribution(comparison)
    write_csv(ATTRIBUTION_OUT, attribution_rows)
    grouped = make_attribution_figure(attribution_means)

    common = [row for row in comparison if bool(row["pitea_feasible"])]
    relative = [
        float(row["pitea_minus_h2p_relative_difference_pct"])
        for row in common
    ]
    bep_to_lcot_ratios = [
        float(row["h2p_published_bep_2023_usd_per_t"])
        / (1000.0 * float(row["h2p_derived_lcot_2023_usd_per_kg"]))
        for row in comparison
    ]
    audit_counts = {
        "common": len(common),
        "within_10": sum(abs(value) <= 10.0 for value in relative),
        "within_15": sum(abs(value) <= 15.0 for value in relative),
        "diameter": sum(
            float(row["pitea_diameter_in"]) == float(row["h2p_diameter_in"])
            for row in common
        ),
        "pair": sum(
            float(row["pitea_diameter_in"]) == float(row["h2p_diameter_in"])
            and int(row["pitea_station_count_enroute"])
            == int(row["h2p_station_count_enroute"])
            for row in common
        ),
        "pitea_switch": sum(
            bool(row["pitea_lcot_design_differs_from_bep"])
            for row in common
        ),
        "h2p_switch": sum(
            bool(row["h2p_lcot_design_differs_from_bep"])
            for row in comparison
        ),
    }
    expected_counts = {
        "common": 38,
        "within_10": 34,
        "within_15": 38,
        "diameter": 31,
        "pair": 23,
        "pitea_switch": 4,
        "h2p_switch": 1,
    }
    if audit_counts != expected_counts:
        raise AssertionError(
            f"LCOT grid audit changed: {audit_counts!r} != {expected_counts!r}"
        )
    mard = statistics.mean(abs(value) for value in relative)
    if abs(mard - 4.750164138378167) > 1.0e-10:
        raise AssertionError("Unexpected LCOT mean absolute relative difference.")
    if len(attribution_rows) != 23:
        raise AssertionError("Expected 23 identical selected designs.")
    metrics = {
        "metric": (
            "LCOT=(0.08/yr annual capital charge factor * "
            "pre-contingency CAPEX + annual OPEX)"
            "/actual annual delivered mass"
        ),
        "reporting_convention": {
            "cost_year": 2023,
            "capacity_factor": CAPACITY_FACTOR,
            "annual_capital_charge_factor_per_year": (
                ANNUAL_CAPITAL_CHARGE_FACTOR
            ),
            "explicit_discount_rate": None,
            "explicit_operating_or_economic_life_years": None,
            "lcot_unit": "2023 USD/kg",
            "pipeline_om_fraction": 0.025,
            "pitea_compressibility": "pressure-dependent Z",
            "pitea_electricity": "PiTEA electricity tariff",
            "gathering": "bypassed",
            "h2p_contingency_adjustment": (
                "15% project contingency removed to match the PiTEA "
                "pre-contingency capital boundary"
            ),
        },
        "source_validation": {
            "h2p_reconstruction_matches_exhibit44_case_count": 48,
            "published_bep_is_not_directly_converted": True,
            "published_bep_over_derived_lcot_ratio_min": min(
                bep_to_lcot_ratios
            ),
            "published_bep_over_derived_lcot_ratio_max": max(
                bep_to_lcot_ratios
            ),
        },
        "grid": {
            "case_count": len(comparison),
            "common_feasible_case_count": len(common),
            "pitea_infeasible_case_count": len(comparison) - len(common),
            "mean_absolute_relative_difference_pct": mard,
            "within_10_pct_count": audit_counts["within_10"],
            "within_15_pct_count": audit_counts["within_15"],
            "nominal_diameter_match_count": audit_counts["diameter"],
            "diameter_station_match_count": audit_counts["pair"],
            "pitea_lcot_vs_bep_design_switch_count": audit_counts[
                "pitea_switch"
            ],
            "h2p_lcot_vs_bep_design_switch_count": audit_counts["h2p_switch"],
        },
        "diameter_grid": {
            "case_count": len(diameters),
            "pitea_h2p_nominal_diameter_match_count": sum(
                float(row["pitea_diameter_in"])
                == float(row["h2p_diameter_in"])
                for row in diameters
            ),
            "pitea_high_flow_endpoint_station_count": int(
                next(
                    row["pitea_station_count_enroute"]
                    for row in diameters
                    if float(row["length_mi"]) == 1000.0
                    and float(row["capacity_mt_per_year"]) == 2.20
                )
            ),
            "hdsam_values_are_secondary_values_reported_by_h2p": True,
        },
        "candidate_audit": {
            "pitea_candidate_count": len(pitea_candidates),
            "pitea_feasible_candidate_count": sum(
                bool(row["eligible_for_lcot_selection"])
                for row in pitea_candidates
            ),
            "h2p_candidate_count": len(h2p_candidates),
            "h2p_source_evaluated_candidate_count": sum(
                bool(row["eligible_for_lcot_selection"])
                for row in h2p_candidates
            ),
            "h2p_full_catalog_gives_same_lcot_selections": True,
            "pitea_model_recomputation": recomputation_audit,
        },
        "representative_cases": representative,
        "fixed_design_attribution": {
            "case_count": len(attribution_rows),
            "mean_h2p_minus_pitea_lcot_2023_usd_per_kg": attribution_means[
                "gap"
            ],
            "grouped_contributions_2023_usd_per_kg": grouped,
        },
        "cost_year_factors": {
            "2011_to_2023": ESCALATION_2011_TO_2023,
            "pitea_2018_to_2011": BROWN_2018_TO_2011,
            "pitea_2018_to_2023": ESCALATION_2018_TO_2023,
        },
        "source_hashes": {
            str(path.relative_to(ROOT)): sha256(path)
            for path in (
                PITEA_SOURCE,
                H2P_SOURCE,
                H2P_TARGETS,
                DIAMETER_TARGETS,
            )
        },
    }
    METRICS_OUT.write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Reproduced the transport-validation candidates, selected designs, "
        "tables, figure data, and metrics."
    )


if __name__ == "__main__":
    main()
