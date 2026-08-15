"""Brown-regression pipeline capital cost with hydrogen adjustments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .hydraulics import km_to_miles
from .parameters import (
    BROWN_REQUIRED_CATEGORIES,
    BROWN_US_AVERAGE_ROUTE_SHARES,
    BrownCoeff,
    EconomicParams,
    PipelineCostData,
    ScenarioInputs,
)
from .validation import (
    validate_economic_params,
    validate_pipeline_cost_data,
    validate_pipeline_cost_lookup_inputs,
    validate_positive,
    validate_route_shares,
    validate_scenario_inputs,
)


@dataclass(frozen=True)
class PipelineCostResult:
    d_in: float
    L_miles: float
    location_class: str
    unit_cost_by_category_region: Mapping[str, Mapping[str, float]]
    unit_cost_avg_by_category: Mapping[str, float]
    unit_cost_h2_by_category: Mapping[str, float]
    capex_pipe_usd: float
    opex_pipe_usd_per_year: float


def compute_brown_unit_cost_usd_per_inch_mile(
    coeff: BrownCoeff,
    d_in: float,
    L_miles: float,
) -> float:
    validate_positive("d_in", d_in)
    validate_positive("L_miles", L_miles)
    return coeff.a * (d_in**coeff.b) * (L_miles**coeff.c)


def compute_brown_natural_gas_cost_2018_usd_per_mile(
    pipeline_data: PipelineCostData,
    nominal_diameter_in: float,
    L_miles: float,
    route_shares: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Evaluate unadjusted Brown component costs per route mile."""

    validate_positive("nominal_diameter_in", nominal_diameter_in)
    validate_positive("L_miles", L_miles)
    validate_pipeline_cost_data(pipeline_data)
    shares = dict(
        BROWN_US_AVERAGE_ROUTE_SHARES
        if route_shares is None
        else route_shares
    )
    validate_route_shares(shares)
    component_costs: dict[str, float] = {}
    for category in BROWN_REQUIRED_CATEGORIES:
        missing_regions = [
            region
            for region in shares
            if region not in pipeline_data.brown_coeffs[category]
        ]
        if missing_regions:
            raise ValueError(
                f"brown_coeffs['{category}'] missing route-share regions: "
                f"{missing_regions}"
            )
        weighted_unit_cost = sum(
            shares[region]
            * compute_brown_unit_cost_usd_per_inch_mile(
                pipeline_data.brown_coeffs[category][region],
                nominal_diameter_in,
                L_miles,
            )
            for region in shares
        )
        component_costs[category] = weighted_unit_cost * nominal_diameter_in
    component_costs["total"] = sum(component_costs.values())
    return component_costs


def evaluate_pipeline_cost(
    scenario: ScenarioInputs,
    econ: EconomicParams,
    pipeline_data: PipelineCostData,
) -> PipelineCostResult:
    validate_scenario_inputs(scenario)
    validate_economic_params(econ)
    validate_pipeline_cost_lookup_inputs(scenario, pipeline_data)
    L_miles = km_to_miles(scenario.L_total_km)
    lookup_key = (scenario.d_in, scenario.location_class)
    unit_cost_by_category_region: dict[str, dict[str, float]] = {}
    unit_cost_avg_by_category: dict[str, float] = {}
    for category in BROWN_REQUIRED_CATEGORIES:
        unit_cost_by_category_region[category] = {}
        for region in scenario.route_shares:
            coeff = pipeline_data.brown_coeffs[category][region]
            unit_cost_by_category_region[category][region] = (
                compute_brown_unit_cost_usd_per_inch_mile(
                    coeff,
                    scenario.d_in,
                    L_miles,
                )
            )
        unit_cost_avg_by_category[category] = sum(
            scenario.route_shares[region]
            * unit_cost_by_category_region[category][region]
            for region in scenario.route_shares
        )
    unit_cost_h2_by_category = {
        "mat": (
            pipeline_data.mu_mat[lookup_key]
            * unit_cost_avg_by_category["mat"]
        ),
        "labor": (
            unit_cost_avg_by_category["labor"]
            + pipeline_data.delta_uc_weld[lookup_key]
        ),
        "misc": unit_cost_avg_by_category["misc"],
        "row": unit_cost_avg_by_category["row"],
    }
    capex_pipe_usd = (
        sum(unit_cost_h2_by_category.values()) * scenario.d_in * L_miles
    )
    opex_pipe_usd_per_year = econ.f_om_pipe * capex_pipe_usd
    return PipelineCostResult(
        d_in=scenario.d_in,
        L_miles=L_miles,
        location_class=scenario.location_class,
        unit_cost_by_category_region=unit_cost_by_category_region,
        unit_cost_avg_by_category=unit_cost_avg_by_category,
        unit_cost_h2_by_category=unit_cost_h2_by_category,
        capex_pipe_usd=capex_pipe_usd,
        opex_pipe_usd_per_year=opex_pipe_usd_per_year,
    )


def build_default_pipeline_cost_data() -> PipelineCostData:
    """Return the Brown/HDSAM pipeline-cost data used in the analysis."""

    brown_coeffs = {
        "mat": {
            "NE": BrownCoeff(10409.0, 0.296847, -0.07257),
            "MA": BrownCoeff(9113.0, 0.279875, -0.00840),
            "GL": BrownCoeff(8971.0, 0.255012, -0.03138),
            "RMGP": BrownCoeff(5813.0, 0.31599, -0.00376),
            "SEPN": BrownCoeff(6207.0, 0.38224, -0.05211),
            "SWCA": BrownCoeff(5605.0, 0.41642, -0.06441),
        },
        "labor": {
            "NE": BrownCoeff(249131.0, -0.33162, -0.17892),
            "MA": BrownCoeff(43692.0, 0.05683, -0.10108),
            "GL": BrownCoeff(58154.0, -0.14821, -0.10596),
            "RMGP": BrownCoeff(10406.0, 0.20953, -0.08419),
            "SEPN": BrownCoeff(32094.0, 0.06110, -0.14828),
            "SWCA": BrownCoeff(95295.0, -0.53848, 0.03070),
        },
        "misc": {
            "NE": BrownCoeff(65990.0, -0.29673, -0.06856),
            "MA": BrownCoeff(14616.0, 0.16354, -0.16186),
            "GL": BrownCoeff(41238.0, -0.34751, -0.11104),
            "RMGP": BrownCoeff(4944.0, 0.17351, -0.07621),
            "SEPN": BrownCoeff(11270.0, 0.19077, -0.13669),
            "SWCA": BrownCoeff(19211.0, -0.14178, -0.04697),
        },
        "row": {
            "NE": BrownCoeff(83124.0, -0.66357, -0.07544),
            "MA": BrownCoeff(1942.0, 0.17394, -0.01555),
            "GL": BrownCoeff(14259.0, -0.65318, 0.06865),
            "RMGP": BrownCoeff(2751.0, -0.28294, 0.00731),
            "SEPN": BrownCoeff(9531.0, -0.37284, 0.02616),
            "SWCA": BrownCoeff(72634.0, -1.07566, 0.05284),
        },
    }
    mu_mat = {
        (4.0, "Class1"): 1.10,
        (6.0, "Class1"): 1.10,
        (8.0, "Class1"): 0.81,
        (10.0, "Class1"): 0.89,
        (12.0, "Class1"): 1.01,
        (14.0, "Class1"): 1.10,
        (16.0, "Class1"): 1.10,
        (18.0, "Class1"): 1.10,
        (20.0, "Class1"): 0.74,
        (24.0, "Class1"): 0.74,
        (30.0, "Class1"): 0.69,
        (36.0, "Class1"): 0.83,
        (42.0, "Class1"): 0.74,
        (4.0, "Class3"): 1.10,
        (6.0, "Class3"): 1.10,
        (8.0, "Class3"): 1.10,
        (10.0, "Class3"): 1.10,
        (12.0, "Class3"): 1.52,
        (14.0, "Class3"): 1.10,
        (16.0, "Class3"): 1.10,
        (18.0, "Class3"): 1.37,
        (20.0, "Class3"): 1.10,
        (24.0, "Class3"): 1.10,
        (30.0, "Class3"): 1.10,
        (36.0, "Class3"): 1.37,
        (42.0, "Class3"): 1.10,
    }
    delta_uc_weld = {
        (4.0, "Class1"): 2.0,
        (6.0, "Class1"): 3.0,
        (8.0, "Class1"): -120.0,
        (10.0, "Class1"): -105.0,
        (12.0, "Class1"): -53.0,
        (14.0, "Class1"): 6.0,
        (16.0, "Class1"): 6.0,
        (18.0, "Class1"): 6.0,
        (20.0, "Class1"): -697.0,
        (24.0, "Class1"): -700.0,
        (30.0, "Class1"): -1311.0,
        (36.0, "Class1"): -926.0,
        (42.0, "Class1"): -2536.0,
        (4.0, "Class3"): 2.0,
        (6.0, "Class3"): 3.0,
        (8.0, "Class3"): 3.0,
        (10.0, "Class3"): 4.0,
        (12.0, "Class3"): 318.0,
        (14.0, "Class3"): 6.0,
        (16.0, "Class3"): 6.0,
        (18.0, "Class3"): 329.0,
        (20.0, "Class3"): 11.0,
        (24.0, "Class3"): 11.0,
        (30.0, "Class3"): 18.0,
        (36.0, "Class3"): 1188.0,
        (42.0, "Class3"): 37.0,
    }
    data = PipelineCostData(
        brown_coeffs=brown_coeffs,
        mu_mat=mu_mat,
        delta_uc_weld=delta_uc_weld,
    )
    validate_pipeline_cost_data(data)
    return data

