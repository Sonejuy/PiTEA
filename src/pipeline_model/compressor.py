"""Hydrogen compressor thermodynamics, sizing, and capital cost."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .hydraulics import compute_state_Z_from_nominal_pressure
from .parameters import (
    CompressorParams,
    EconomicParams,
    MotorEfficiencyCoeffs,
    PhysicalParams,
)
from .validation import (
    validate_integer_at_least,
    validate_nonnegative,
    validate_positive,
)


@dataclass(frozen=True)
class UnitFlowRates:
    Q_kg_per_s_unit: float
    Q_mol_per_s_unit: float


@dataclass(frozen=True)
class CompressorStateResult:
    label: str
    state: str
    P_suc_bar: float
    P_disc_bar: float
    compression_ratio: float
    Z_comp: float
    n_stage: int
    T_suc_K: float
    P_shaft_kW: float
    eta_motor: float
    W_unit_kW: float


@dataclass(frozen=True)
class CompressorEnvelopeResult:
    label: str
    pack: CompressorStateResult
    draft: CompressorStateResult
    governing_state: str
    governing_n_stage: int
    governing_W_unit_kW: float
    W_req_unit_kW: float
    stage_multiplier: float
    station_capex_usd: float
    annual_energy_kWh: float
    opex_elec_usd_per_year: float


@dataclass(frozen=True)
class CompressorHardware:
    """Pack-selected hardware at one compressor location."""

    label: str
    installed_stages: int
    installed_rating_unit_kw: float
    pack_motor_power_unit_kw: float
    station_capex_2018_usd: float
    pack_ratio: float


def compute_unit_flow_rates(
    Q_mass_kg_per_day: float,
    N_op: int,
    MW_H2_g_per_mol: float,
) -> UnitFlowRates:
    validate_positive("Q_mass_kg_per_day", Q_mass_kg_per_day)
    validate_integer_at_least("N_op", N_op, 1)
    validate_positive("MW_H2_g_per_mol", MW_H2_g_per_mol)
    Q_kg_per_s_unit = Q_mass_kg_per_day / (24.0 * 3600.0 * N_op)
    Q_mol_per_s_unit = 1000.0 * Q_kg_per_s_unit / MW_H2_g_per_mol
    return UnitFlowRates(Q_kg_per_s_unit, Q_mol_per_s_unit)


def compute_compression_ratio(P_disc_bar: float, P_suc_bar: float) -> float:
    validate_positive("P_disc_bar", P_disc_bar)
    validate_positive("P_suc_bar", P_suc_bar)
    return P_disc_bar / P_suc_bar


def compute_required_stage_count(compression_ratio: float, r_max: float) -> int:
    validate_positive("compression_ratio", compression_ratio)
    validate_positive("r_max", r_max)
    if compression_ratio <= 1.0:
        return 0
    return math.ceil(math.log(compression_ratio) / math.log(r_max))


def motor_efficiency_hdsam(
    P_shaft_kW: float,
    coeffs: MotorEfficiencyCoeffs,
) -> float:
    validate_nonnegative("P_shaft_kW", P_shaft_kW)
    if P_shaft_kW == 0.0:
        return 1.0
    lnP = math.log(P_shaft_kW)
    eta = (
        coeffs.a * lnP**4
        - coeffs.b * lnP**3
        + coeffs.c * lnP**2
        + coeffs.d * lnP
        + coeffs.e
    )
    if eta <= 0:
        raise ValueError(
            f"Motor efficiency polynomial returned nonpositive value {eta}."
        )
    return eta


def compute_shaft_power_kW(
    compression_ratio: float,
    n_stage: int,
    Z_comp: float,
    T_suc_K: float,
    R_J_per_molK: float,
    Q_mol_per_s_unit: float,
    gamma: float,
    eta_poly: float,
) -> float:
    if n_stage == 0 or compression_ratio <= 1.0 or Q_mol_per_s_unit == 0.0:
        return 0.0
    exponent = (gamma - 1.0) / (n_stage * gamma)
    bracket = compression_ratio**exponent - 1.0
    P_shaft_kW = (
        n_stage
        * (gamma / (gamma - 1.0))
        * (Z_comp * T_suc_K * R_J_per_molK * Q_mol_per_s_unit / eta_poly)
        * bracket
        / 1000.0
    )
    if P_shaft_kW < 0:
        raise ValueError(f"Computed negative shaft power {P_shaft_kW} kW.")
    return P_shaft_kW


def evaluate_compressor_state(
    label: str,
    state: str,
    P_suc_bar: float,
    P_disc_bar: float,
    T_suc_K: float,
    unit_flows: UnitFlowRates,
    physical: PhysicalParams,
    comp: CompressorParams,
) -> CompressorStateResult:
    validate_positive("P_suc_bar", P_suc_bar)
    validate_positive("P_disc_bar", P_disc_bar)
    compression_ratio = compute_compression_ratio(P_disc_bar, P_suc_bar)
    n_stage = compute_required_stage_count(compression_ratio, comp.r_max)
    Z_comp = compute_state_Z_from_nominal_pressure(
        0.5 * (P_suc_bar + P_disc_bar),
        physical,
    )
    P_shaft_kW = compute_shaft_power_kW(
        compression_ratio,
        n_stage,
        Z_comp,
        T_suc_K,
        physical.R_J_per_molK,
        unit_flows.Q_mol_per_s_unit,
        physical.gamma,
        comp.eta_poly,
    )
    eta_motor = motor_efficiency_hdsam(P_shaft_kW, comp.motor_efficiency)
    W_unit_kW = 0.0 if P_shaft_kW == 0.0 else P_shaft_kW / eta_motor
    return CompressorStateResult(
        label=label,
        state=state,
        P_suc_bar=P_suc_bar,
        P_disc_bar=P_disc_bar,
        compression_ratio=compression_ratio,
        Z_comp=Z_comp,
        n_stage=n_stage,
        T_suc_K=T_suc_K,
        P_shaft_kW=P_shaft_kW,
        eta_motor=eta_motor,
        W_unit_kW=W_unit_kW,
    )


def compute_stage_complexity_multiplier(n_stage: int) -> float:
    if n_stage < 0:
        raise ValueError(f"n_stage must be >= 0, got {n_stage}.")
    if n_stage <= 2:
        return 1.0
    return 1.0 + 0.2 * (n_stage - 2)


def compute_station_compressor_capex_usd(
    governing_n_stage: int,
    W_req_unit_kW: float,
    comp: CompressorParams,
) -> float:
    if W_req_unit_kW == 0.0:
        return 0.0
    return (
        1.4
        * compute_stage_complexity_multiplier(governing_n_stage)
        * comp.a_comp_2018_usd
        * (W_req_unit_kW**comp.b_comp)
        * comp.mu_tech
    )


def evaluate_compressor_envelope(
    label: str,
    pack_state: CompressorStateResult,
    draft_state: CompressorStateResult,
    n_stations: int,
    comp: CompressorParams,
    econ: EconomicParams,
) -> CompressorEnvelopeResult:
    governing_state = (
        "pack" if pack_state.W_unit_kW >= draft_state.W_unit_kW else "draft"
    )
    governing_n_stage = max(pack_state.n_stage, draft_state.n_stage)
    governing_W_unit_kW = max(pack_state.W_unit_kW, draft_state.W_unit_kW)
    W_req_unit_kW = comp.SF * governing_W_unit_kW
    station_capex_usd = compute_station_compressor_capex_usd(
        governing_n_stage,
        W_req_unit_kW,
        comp,
    )
    annual_energy_kWh = 8760.0 * comp.N_op * governing_W_unit_kW
    if label == "enroute":
        annual_energy_kWh *= n_stations
    opex_elec_usd_per_year = annual_energy_kWh * econ.C_elec_usd_per_kWh
    return CompressorEnvelopeResult(
        label=label,
        pack=pack_state,
        draft=draft_state,
        governing_state=governing_state,
        governing_n_stage=governing_n_stage,
        governing_W_unit_kW=governing_W_unit_kW,
        W_req_unit_kW=W_req_unit_kW,
        stage_multiplier=compute_stage_complexity_multiplier(
            governing_n_stage
        ),
        station_capex_usd=station_capex_usd,
        annual_energy_kWh=annual_energy_kWh,
        opex_elec_usd_per_year=opex_elec_usd_per_year,
    )


def evaluate_zero_enroute_envelope(
    comp: CompressorParams,
    econ: EconomicParams,
) -> CompressorEnvelopeResult:
    zero = CompressorStateResult(
        label="enroute",
        state="pack",
        P_suc_bar=1.0,
        P_disc_bar=1.0,
        compression_ratio=1.0,
        Z_comp=1.0,
        n_stage=0,
        T_suc_K=298.15,
        P_shaft_kW=0.0,
        eta_motor=1.0,
        W_unit_kW=0.0,
    )
    zero_draft = CompressorStateResult(
        label="enroute",
        state="draft",
        P_suc_bar=1.0,
        P_disc_bar=1.0,
        compression_ratio=1.0,
        Z_comp=1.0,
        n_stage=0,
        T_suc_K=298.15,
        P_shaft_kW=0.0,
        eta_motor=1.0,
        W_unit_kW=0.0,
    )
    return evaluate_compressor_envelope(
        "enroute",
        zero,
        zero_draft,
        0,
        comp,
        econ,
    )
