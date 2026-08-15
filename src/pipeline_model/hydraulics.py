"""Steady-state hydrogen pipeline hydraulics used by PiTEA.

Pressures are absolute inside the hydraulic calculations; scenario pressure
inputs are gauge pressures.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .parameters import PhysicalParams, ScenarioInputs
from .validation import (
    validate_integer_at_least,
    validate_nonnegative,
    validate_physical_params,
    validate_positive,
    validate_scenario_inputs,
)


@dataclass(frozen=True)
class PressureInputsAbsolute:
    P_source_a_bar: float
    P_contract_a_bar: float
    P_rate_a_bar: float


@dataclass(frozen=True)
class DiameterHydraulicPrecompute:
    d_in: float
    d_m: float
    Q_mass_kg_per_day: float
    Q_kg_per_s: float
    epsilon_m: float
    Re_d: float
    C_f_d: float
    K_phys: float
    M_station: int
    V_pipe_m3: float
    pressures_abs: PressureInputsAbsolute


@dataclass(frozen=True)
class PackStateResult:
    Z_pack: float
    H_pack_bar2: float
    P_in_pack_bar: float
    P_out_pack_bar: float
    P_avg_pack_bar: float
    feasible: bool
    infeasibility_reason: str | None


@dataclass(frozen=True)
class DraftStateBoundsResult:
    Z_draft: float
    H_draft_bar2: float
    q_lower_bar: float
    q_upper_bar: float
    q_lower_contract_bar: float
    q_lower_source_bar: float
    q_upper_rate_bar: float
    q_upper_pack_bar: float
    feasible: bool
    infeasibility_reason: str | None


def barg_to_bara(p_g_bar: float, p_amb_bar: float) -> float:
    return p_g_bar + p_amb_bar


def inch_to_meter(d_in: float) -> float:
    return 0.0254 * d_in


def mm_to_meter(x_mm: float) -> float:
    return 1e-3 * x_mm


def kg_per_day_to_kg_per_s(q_kg_day: float) -> float:
    return q_kg_day / (24.0 * 3600.0)


def km_to_miles(length_km: float) -> float:
    return length_km / 1.60934


def bar_to_pa(p_bar: float) -> float:
    return p_bar * 1e5


def compute_pipe_cross_section_area_m2(d_m: float) -> float:
    validate_positive("d_m", d_m)
    return math.pi * d_m**2 / 4.0


def compute_pipe_volume_m3(d_m: float, L_total_km: float) -> float:
    validate_positive("d_m", d_m)
    validate_positive("L_total_km", L_total_km)
    return compute_pipe_cross_section_area_m2(d_m) * (L_total_km * 1000.0)


def compute_m_station(L_total_km: float, L_min_seg_km: float) -> int:
    return max(0, math.floor(L_total_km / L_min_seg_km) - 1)


def validate_pressure_inputs_absolute(pressures: PressureInputsAbsolute) -> None:
    validate_positive("P_source_a_bar", pressures.P_source_a_bar)
    validate_positive("P_contract_a_bar", pressures.P_contract_a_bar)
    validate_positive("P_rate_a_bar", pressures.P_rate_a_bar)
    if pressures.P_rate_a_bar < pressures.P_contract_a_bar:
        raise ValueError(
            "P_rate_a_bar must be >= P_contract_a_bar, got "
            f"{pressures.P_rate_a_bar} < {pressures.P_contract_a_bar}."
        )


def build_absolute_pressures(
    scenario: ScenarioInputs,
    physical: PhysicalParams,
) -> PressureInputsAbsolute:
    pressures = PressureInputsAbsolute(
        P_source_a_bar=barg_to_bara(
            scenario.P_source_g_bar,
            physical.P_amb_bar,
        ),
        P_contract_a_bar=barg_to_bara(
            scenario.P_contract_g_bar,
            physical.P_amb_bar,
        ),
        P_rate_a_bar=barg_to_bara(
            scenario.P_rate_g_bar,
            physical.P_amb_bar,
        ),
    )
    validate_pressure_inputs_absolute(pressures)
    return pressures


def safe_sqrt_nonnegative(x: float) -> float:
    if x < -1e-12:
        raise ValueError(f"Expected nonnegative value under square root, got {x}.")
    return math.sqrt(max(0.0, x))


def average_pressure_bar(p_in_bar: float, p_out_bar: float, use_exact: bool) -> float:
    validate_positive("p_in_bar", p_in_bar)
    validate_positive("p_out_bar", p_out_bar)
    if use_exact:
        denom = p_in_bar**2 - p_out_bar**2
        if abs(denom) < 1e-12:
            return p_in_bar
        return (2.0 / 3.0) * (p_in_bar**3 - p_out_bar**3) / denom
    return 0.5 * (p_in_bar + p_out_bar)


def buffer_mass_required_kg(
    Q_mass_kg_per_day: float,
    F_fluct: float,
    buffer_hours: float,
) -> float:
    validate_positive("Q_mass_kg_per_day", Q_mass_kg_per_day)
    validate_nonnegative("F_fluct", F_fluct)
    validate_positive("buffer_hours", buffer_hours)
    return F_fluct * Q_mass_kg_per_day * (buffer_hours / 24.0)


def compute_k_phys(physical: PhysicalParams) -> float:
    mw_kg_per_mol = physical.MW_H2_g_per_mol * 1e-3
    numerator = 16.0 * physical.R_J_per_molK * physical.T_pipe_K
    denominator = (math.pi**2) * mw_kg_per_mol
    unit_factor = 1000.0 / (
        (1e5) ** 2 * (0.0254**5) * ((24.0 * 3600.0) ** 2)
    )
    return (numerator / denominator) * unit_factor


def compute_reynolds_number(
    Q_kg_per_s: float,
    d_m: float,
    mu_Pa_s: float,
) -> float:
    validate_positive("Q_kg_per_s", Q_kg_per_s)
    validate_positive("d_m", d_m)
    validate_positive("mu_Pa_s", mu_Pa_s)
    return 4.0 * Q_kg_per_s / (math.pi * d_m * mu_Pa_s)


def compute_haaland_friction_factor(
    Re_d: float,
    epsilon_m: float,
    d_m: float,
) -> float:
    validate_positive("Re_d", Re_d)
    validate_positive("d_m", d_m)
    validate_nonnegative("epsilon_m", epsilon_m)
    roughness_term = ((epsilon_m / d_m) / 3.7) ** 1.11
    reynolds_term = 6.9 / Re_d
    inv_sqrt_cf = -1.8 * math.log10(roughness_term + reynolds_term)
    C_f_d = 1.0 / (inv_sqrt_cf**2)
    validate_positive("C_f_d", C_f_d)
    return C_f_d


def precompute_diameter_hydraulics(
    scenario: ScenarioInputs,
    physical: PhysicalParams,
) -> DiameterHydraulicPrecompute:
    validate_scenario_inputs(scenario)
    validate_physical_params(physical)
    d_m = inch_to_meter(scenario.d_in)
    Q_kg_per_s = kg_per_day_to_kg_per_s(scenario.Q_mass_kg_per_day)
    epsilon_m = mm_to_meter(physical.epsilon_mm)
    Re_d = compute_reynolds_number(Q_kg_per_s, d_m, physical.mu_Pa_s)
    C_f_d = compute_haaland_friction_factor(Re_d, epsilon_m, d_m)
    K_phys = compute_k_phys(physical)
    M_station = compute_m_station(scenario.L_total_km, physical.L_min_seg_km)
    pressures_abs = build_absolute_pressures(scenario, physical)
    V_pipe_m3 = compute_pipe_volume_m3(d_m, scenario.L_total_km)
    return DiameterHydraulicPrecompute(
        d_in=scenario.d_in,
        d_m=d_m,
        Q_mass_kg_per_day=scenario.Q_mass_kg_per_day,
        Q_kg_per_s=Q_kg_per_s,
        epsilon_m=epsilon_m,
        Re_d=Re_d,
        C_f_d=C_f_d,
        K_phys=K_phys,
        M_station=M_station,
        V_pipe_m3=V_pipe_m3,
        pressures_abs=pressures_abs,
    )


def compute_segment_length_km(L_total_km: float, n_stations: int) -> float:
    validate_positive("L_total_km", L_total_km)
    validate_integer_at_least("n_stations", n_stations, 0)
    return L_total_km / (n_stations + 1)


def compute_state_Z_from_nominal_pressure(
    nominal_pressure_bar: float,
    physical: PhysicalParams,
) -> float:
    validate_positive("nominal_pressure_bar", nominal_pressure_bar)
    return 1.0 + physical.beta_Z_per_bar * nominal_pressure_bar


def compute_state_pressure_drop_bar2(
    Q_mass_kg_per_day: float,
    d_in: float,
    L_seg_km: float,
    Z_state: float,
    C_f_d: float,
    K_phys: float,
) -> float:
    validate_positive("Q_mass_kg_per_day", Q_mass_kg_per_day)
    validate_positive("d_in", d_in)
    validate_positive("L_seg_km", L_seg_km)
    validate_positive("Z_state", Z_state)
    validate_positive("C_f_d", C_f_d)
    validate_positive("K_phys", K_phys)
    return (
        K_phys
        * Z_state
        * L_seg_km
        * (C_f_d / (d_in**5))
        * (Q_mass_kg_per_day**2)
    )


def evaluate_pack_state(
    n_stations: int,
    scenario: ScenarioInputs,
    physical: PhysicalParams,
    pre: DiameterHydraulicPrecompute,
) -> PackStateResult:
    if n_stations > pre.M_station:
        return PackStateResult(
            Z_pack=float("nan"),
            H_pack_bar2=float("nan"),
            P_in_pack_bar=pre.pressures_abs.P_rate_a_bar,
            P_out_pack_bar=float("nan"),
            P_avg_pack_bar=float("nan"),
            feasible=False,
            infeasibility_reason=(
                f"n_stations={n_stations} exceeds M_station={pre.M_station}."
            ),
        )
    L_seg_km = compute_segment_length_km(scenario.L_total_km, n_stations)
    Z_pack = compute_state_Z_from_nominal_pressure(
        pre.pressures_abs.P_rate_a_bar,
        physical,
    )
    H_pack_bar2 = compute_state_pressure_drop_bar2(
        scenario.Q_mass_kg_per_day,
        scenario.d_in,
        L_seg_km,
        Z_pack,
        pre.C_f_d,
        pre.K_phys,
    )
    radicand = pre.pressures_abs.P_rate_a_bar**2 - H_pack_bar2
    if radicand < 0:
        return PackStateResult(
            Z_pack=Z_pack,
            H_pack_bar2=H_pack_bar2,
            P_in_pack_bar=pre.pressures_abs.P_rate_a_bar,
            P_out_pack_bar=float("nan"),
            P_avg_pack_bar=float("nan"),
            feasible=False,
            infeasibility_reason=(
                "Pack state infeasible: (P_rate)^2 - H_pack < 0."
            ),
        )
    P_out_pack_bar = safe_sqrt_nonnegative(radicand)
    if P_out_pack_bar < pre.pressures_abs.P_contract_a_bar:
        return PackStateResult(
            Z_pack=Z_pack,
            H_pack_bar2=H_pack_bar2,
            P_in_pack_bar=pre.pressures_abs.P_rate_a_bar,
            P_out_pack_bar=P_out_pack_bar,
            P_avg_pack_bar=float("nan"),
            feasible=False,
            infeasibility_reason=(
                "Pack state infeasible: P_out,pack < P_contract."
            ),
        )
    P_avg_pack_bar = average_pressure_bar(
        pre.pressures_abs.P_rate_a_bar,
        P_out_pack_bar,
        physical.use_exact_average_pressure,
    )
    return PackStateResult(
        Z_pack=Z_pack,
        H_pack_bar2=H_pack_bar2,
        P_in_pack_bar=pre.pressures_abs.P_rate_a_bar,
        P_out_pack_bar=P_out_pack_bar,
        P_avg_pack_bar=P_avg_pack_bar,
        feasible=True,
        infeasibility_reason=None,
    )


def evaluate_draft_state_bounds(
    n_stations: int,
    scenario: ScenarioInputs,
    physical: PhysicalParams,
    pre: DiameterHydraulicPrecompute,
    pack_state: PackStateResult,
) -> DraftStateBoundsResult:
    if not pack_state.feasible:
        return DraftStateBoundsResult(
            Z_draft=float("nan"),
            H_draft_bar2=float("nan"),
            q_lower_bar=float("nan"),
            q_upper_bar=float("nan"),
            q_lower_contract_bar=float("nan"),
            q_lower_source_bar=float("nan"),
            q_upper_rate_bar=float("nan"),
            q_upper_pack_bar=float("nan"),
            feasible=False,
            infeasibility_reason=(
                "Draft state unavailable because pack state is infeasible."
            ),
        )
    L_seg_km = compute_segment_length_km(scenario.L_total_km, n_stations)
    Z_draft = compute_state_Z_from_nominal_pressure(
        pre.pressures_abs.P_contract_a_bar,
        physical,
    )
    H_draft_bar2 = compute_state_pressure_drop_bar2(
        scenario.Q_mass_kg_per_day,
        scenario.d_in,
        L_seg_km,
        Z_draft,
        pre.C_f_d,
        pre.K_phys,
    )
    q_lower_contract = pre.pressures_abs.P_contract_a_bar
    q_lower_source = safe_sqrt_nonnegative(
        max(0.0, pre.pressures_abs.P_source_a_bar**2 - H_draft_bar2)
    )
    q_upper_rate = safe_sqrt_nonnegative(
        max(0.0, pre.pressures_abs.P_rate_a_bar**2 - H_draft_bar2)
    )
    q_upper_pack = pack_state.P_out_pack_bar
    q_lower = max(q_lower_contract, q_lower_source)
    q_upper = min(q_upper_rate, q_upper_pack)
    feasible = q_lower <= q_upper + 1e-12
    reason = (
        None
        if feasible
        else "No admissible draft-state interval: q_lower > q_upper."
    )
    return DraftStateBoundsResult(
        Z_draft=Z_draft,
        H_draft_bar2=H_draft_bar2,
        q_lower_bar=q_lower,
        q_upper_bar=q_upper,
        q_lower_contract_bar=q_lower_contract,
        q_lower_source_bar=q_lower_source,
        q_upper_rate_bar=q_upper_rate,
        q_upper_pack_bar=q_upper_pack,
        feasible=feasible,
        infeasibility_reason=reason,
    )


def build_q_grid(
    bounds: DraftStateBoundsResult,
    q_grid_points: int,
) -> list[float]:
    validate_integer_at_least("q_grid_points", q_grid_points, 1)
    if not bounds.feasible:
        return []
    if q_grid_points == 1 or abs(bounds.q_upper_bar - bounds.q_lower_bar) < 1e-12:
        return [bounds.q_lower_bar]
    return [
        bounds.q_lower_bar
        + index
        * (bounds.q_upper_bar - bounds.q_lower_bar)
        / (q_grid_points - 1)
        for index in range(q_grid_points)
    ]
