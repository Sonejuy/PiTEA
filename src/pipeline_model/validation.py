"""Input validation shared by the model domains."""

from __future__ import annotations

from .parameters import (
    BROWN_REQUIRED_CATEGORIES,
    CompressorParams,
    EconomicParams,
    PhysicalParams,
    PipelineCostData,
    ScenarioInputs,
)


def validate_positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be > 0, got {value}.")


def validate_nonnegative(name: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}.")


def validate_integer_at_least(name: str, value: int, lower: int) -> None:
    if int(value) != value or value < lower:
        raise ValueError(f"{name} must be an integer >= {lower}, got {value}.")


def validate_route_shares(route_shares: dict[str, float], tol: float = 1e-9) -> None:
    if not route_shares:
        raise ValueError("route_shares cannot be empty.")
    total = sum(route_shares.values())
    if abs(total - 1.0) > tol:
        raise ValueError(f"route_shares must sum to 1.0, got {total}.")
    for region, share in route_shares.items():
        if share < 0:
            raise ValueError(
                f"route share for region '{region}' is negative: {share}."
            )


def validate_scenario_inputs(scenario: ScenarioInputs) -> None:
    validate_positive("Q_mass_kg_per_day", scenario.Q_mass_kg_per_day)
    validate_positive("L_total_km", scenario.L_total_km)
    validate_positive("d_in", scenario.d_in)
    validate_route_shares(dict(scenario.route_shares))
    validate_nonnegative("F_fluct", scenario.F_fluct)
    validate_positive("buffer_hours", scenario.buffer_hours)
    validate_integer_at_least("q_grid_points", scenario.q_grid_points, 1)


def validate_physical_params(physical: PhysicalParams) -> None:
    validate_positive("P_amb_bar", physical.P_amb_bar)
    validate_positive("T_pipe_K", physical.T_pipe_K)
    validate_positive("R_J_per_molK", physical.R_J_per_molK)
    validate_positive("MW_H2_g_per_mol", physical.MW_H2_g_per_mol)
    validate_positive("gamma", physical.gamma)
    validate_positive("mu_Pa_s", physical.mu_Pa_s)
    validate_nonnegative("epsilon_mm", physical.epsilon_mm)
    validate_positive("L_min_seg_km", physical.L_min_seg_km)
    validate_nonnegative("beta_Z_per_bar", physical.beta_Z_per_bar)
    validate_positive(
        "beta_slope_kg_per_m3_per_bar",
        physical.beta_slope_kg_per_m3_per_bar,
    )


def validate_compressor_params(compressor: CompressorParams) -> None:
    validate_positive("eta_poly", compressor.eta_poly)
    validate_positive("r_max", compressor.r_max)
    if compressor.r_max <= 1.0:
        raise ValueError(f"r_max must exceed 1.0, got {compressor.r_max}.")
    validate_integer_at_least("N_op", compressor.N_op, 1)
    validate_integer_at_least("N_spare", compressor.N_spare, 0)
    validate_positive("SF", compressor.SF)
    validate_positive("a_comp_2018_usd", compressor.a_comp_2018_usd)
    validate_positive("b_comp", compressor.b_comp)
    validate_positive("mu_tech", compressor.mu_tech)


def validate_economic_params(economics: EconomicParams) -> None:
    validate_positive("CRF", economics.CRF)
    validate_nonnegative("C_elec_usd_per_kWh", economics.C_elec_usd_per_kWh)
    validate_nonnegative("f_om_pipe", economics.f_om_pipe)
    validate_nonnegative("f_om_comp", economics.f_om_comp)
    validate_nonnegative("f_ins", economics.f_ins)
    validate_nonnegative("f_tax", economics.f_tax)
    validate_nonnegative("f_permit", economics.f_permit)
    validate_nonnegative("C_ext_usd_per_kg", economics.C_ext_usd_per_kg)
    validate_nonnegative("f_om_store", economics.f_om_store)


def validate_pipeline_cost_data(data: PipelineCostData) -> None:
    if not data.brown_coeffs:
        raise ValueError("brown_coeffs cannot be empty.")
    if not data.mu_mat:
        raise ValueError("mu_mat cannot be empty.")
    if not data.delta_uc_weld:
        raise ValueError("delta_uc_weld cannot be empty.")
    missing = [
        category
        for category in BROWN_REQUIRED_CATEGORIES
        if category not in data.brown_coeffs
    ]
    if missing:
        raise ValueError("brown_coeffs missing categories: " + ", ".join(missing))


def validate_pipeline_cost_lookup_inputs(
    scenario: ScenarioInputs,
    data: PipelineCostData,
) -> None:
    validate_scenario_inputs(scenario)
    validate_pipeline_cost_data(data)
    for category in BROWN_REQUIRED_CATEGORIES:
        missing_regions = [
            region
            for region in scenario.route_shares
            if region not in data.brown_coeffs[category]
        ]
        if missing_regions:
            raise ValueError(
                f"brown_coeffs['{category}'] missing route_share regions: "
                f"{missing_regions}"
            )
    lookup_key = (scenario.d_in, scenario.location_class)
    if lookup_key not in data.mu_mat:
        raise ValueError(f"mu_mat missing lookup key {lookup_key!r}.")
    if lookup_key not in data.delta_uc_weld:
        raise ValueError(f"delta_uc_weld missing lookup key {lookup_key!r}.")
