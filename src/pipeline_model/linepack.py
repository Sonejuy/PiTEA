"""Linepack inventory and coupled draft-state evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from .compressor import (
    CompressorEnvelopeResult,
    UnitFlowRates,
    evaluate_compressor_envelope,
    evaluate_compressor_state,
    evaluate_zero_enroute_envelope,
)
from .hydraulics import (
    DiameterHydraulicPrecompute,
    DraftStateBoundsResult,
    PackStateResult,
    average_pressure_bar,
    buffer_mass_required_kg,
    safe_sqrt_nonnegative,
)
from .parameters import (
    CompressorParams,
    EconomicParams,
    PhysicalParams,
    ScenarioInputs,
)
from .pipeline_costs import PipelineCostResult


@dataclass(frozen=True)
class DraftStateEvaluationResult:
    q_bar: float
    P_in_draft_bar: float
    P_out_draft_bar: float
    P_avg_draft_bar: float
    delta_P_avg_bar: float
    M_lp_kg: float
    M_ext_kg: float
    gathering: CompressorEnvelopeResult
    enroute: CompressorEnvelopeResult
    capex_store_usd: float
    opex_store_usd_per_year: float
    capex_comp_total_usd: float
    opex_comp_total_usd_per_year: float
    capex_total_usd: float
    opex_total_usd_per_year: float
    annualized_cost_usd_per_year: float
    lcoh_usd_per_kg: float


def evaluate_one_q_candidate(
    q_bar: float,
    n_stations: int,
    scenario: ScenarioInputs,
    physical: PhysicalParams,
    comp: CompressorParams,
    econ: EconomicParams,
    pre: DiameterHydraulicPrecompute,
    pack_state: PackStateResult,
    draft_bounds: DraftStateBoundsResult,
    unit_flows: UnitFlowRates,
    pipeline_cost: PipelineCostResult,
) -> DraftStateEvaluationResult:
    """Evaluate one pressure-draft operating point."""

    P_in_draft_bar = safe_sqrt_nonnegative(
        q_bar**2 + draft_bounds.H_draft_bar2
    )
    P_avg_draft_bar = average_pressure_bar(
        P_in_draft_bar,
        q_bar,
        physical.use_exact_average_pressure,
    )
    delta_P_avg_bar = pack_state.P_avg_pack_bar - P_avg_draft_bar
    M_lp_kg = (
        pre.V_pipe_m3
        * physical.beta_slope_kg_per_m3_per_bar
        * delta_P_avg_bar
    )
    M_req_buf_kg = buffer_mass_required_kg(
        scenario.Q_mass_kg_per_day,
        scenario.F_fluct,
        scenario.buffer_hours,
    )
    M_ext_kg = max(0.0, M_req_buf_kg - M_lp_kg)

    gathering_pack = evaluate_compressor_state(
        label="gathering",
        state="pack",
        P_suc_bar=pre.pressures_abs.P_source_a_bar,
        P_disc_bar=pack_state.P_in_pack_bar,
        T_suc_K=physical.T_pipe_K,
        unit_flows=unit_flows,
        physical=physical,
        comp=comp,
    )
    gathering_draft = evaluate_compressor_state(
        label="gathering",
        state="draft",
        P_suc_bar=pre.pressures_abs.P_source_a_bar,
        P_disc_bar=P_in_draft_bar,
        T_suc_K=physical.T_pipe_K,
        unit_flows=unit_flows,
        physical=physical,
        comp=comp,
    )
    gathering = evaluate_compressor_envelope(
        "gathering",
        gathering_pack,
        gathering_draft,
        n_stations,
        comp,
        econ,
    )

    if n_stations == 0:
        enroute = evaluate_zero_enroute_envelope(comp, econ)
    else:
        enroute_pack = evaluate_compressor_state(
            label="enroute",
            state="pack",
            P_suc_bar=pack_state.P_out_pack_bar,
            P_disc_bar=pack_state.P_in_pack_bar,
            T_suc_K=physical.T_pipe_K,
            unit_flows=unit_flows,
            physical=physical,
            comp=comp,
        )
        enroute_draft = evaluate_compressor_state(
            label="enroute",
            state="draft",
            P_suc_bar=q_bar,
            P_disc_bar=P_in_draft_bar,
            T_suc_K=physical.T_pipe_K,
            unit_flows=unit_flows,
            physical=physical,
            comp=comp,
        )
        enroute = evaluate_compressor_envelope(
            "enroute",
            enroute_pack,
            enroute_draft,
            n_stations,
            comp,
            econ,
        )

    n_units_total = comp.N_op + comp.N_spare
    capex_comp_total_usd = n_units_total * (
        gathering.station_capex_usd
        + n_stations * enroute.station_capex_usd
    )
    fixed_fraction = (
        econ.f_om_comp + econ.f_ins + econ.f_tax + econ.f_permit
    )
    opex_comp_total_usd_per_year = (
        gathering.opex_elec_usd_per_year
        + enroute.opex_elec_usd_per_year
        + fixed_fraction * capex_comp_total_usd
    )

    capex_store_usd = econ.C_ext_usd_per_kg * M_ext_kg
    opex_store_usd_per_year = econ.f_om_store * capex_store_usd
    capex_total_usd = (
        pipeline_cost.capex_pipe_usd
        + capex_comp_total_usd
        + capex_store_usd
    )
    opex_total_usd_per_year = (
        pipeline_cost.opex_pipe_usd_per_year
        + opex_comp_total_usd_per_year
        + opex_store_usd_per_year
    )
    annualized_cost_usd_per_year = (
        econ.CRF * capex_total_usd + opex_total_usd_per_year
    )
    lcoh_usd_per_kg = annualized_cost_usd_per_year / (
        365.0 * scenario.Q_mass_kg_per_day
    )

    return DraftStateEvaluationResult(
        q_bar=q_bar,
        P_in_draft_bar=P_in_draft_bar,
        P_out_draft_bar=q_bar,
        P_avg_draft_bar=P_avg_draft_bar,
        delta_P_avg_bar=delta_P_avg_bar,
        M_lp_kg=M_lp_kg,
        M_ext_kg=M_ext_kg,
        gathering=gathering,
        enroute=enroute,
        capex_store_usd=capex_store_usd,
        opex_store_usd_per_year=opex_store_usd_per_year,
        capex_comp_total_usd=capex_comp_total_usd,
        opex_comp_total_usd_per_year=opex_comp_total_usd_per_year,
        capex_total_usd=capex_total_usd,
        opex_total_usd_per_year=opex_total_usd_per_year,
        annualized_cost_usd_per_year=annualized_cost_usd_per_year,
        lcoh_usd_per_kg=lcoh_usd_per_kg,
    )
