"""Transport, linepack-credit, and joint-design selection.

The model evaluates three service-equivalent strategies: external storage
only, linepack without infrastructure redesign, and joint design. It uses
deterministic tie-breaking and exact pressure-boundary refinements.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable, Sequence

from .compressor import (
    CompressorHardware,
    compute_compression_ratio,
    compute_shaft_power_kW,
    compute_station_compressor_capex_usd,
    compute_unit_flow_rates,
    evaluate_compressor_envelope,
    evaluate_compressor_state,
    evaluate_zero_enroute_envelope,
    motor_efficiency_hdsam,
)
from .economics import cost_ledger, study_economic_inputs
from .hydraulics import (
    average_pressure_bar,
    compute_segment_length_km,
    compute_state_Z_from_nominal_pressure,
    evaluate_draft_state_bounds,
    evaluate_pack_state,
    precompute_diameter_hydraulics,
    safe_sqrt_nonnegative,
)
from .linepack import evaluate_one_q_candidate
from .parameters import (
    BROWN_US_AVERAGE_ROUTE_SHARES,
    CompressorParams,
    PhysicalParams,
    PipelineCostData,
    ScenarioInputs,
    StudyBasis,
)
from .pipeline_costs import (
    PipelineCostResult,
    build_default_pipeline_cost_data,
    evaluate_pipeline_cost,
)


@dataclass(frozen=True)
class PackCandidate:
    """Transport-only candidate with pack-state hardware and costs."""

    length_km: float
    diameter_in: float
    stations: int
    segment_length_km: float
    scenario: ScenarioInputs
    precompute: Any
    pack_state: Any
    pipeline_cost: PipelineCostResult
    gathering: CompressorHardware
    enroute: CompressorHardware
    compressor_capex_2018_usd: float
    full_year_energy_kwh: float
    transport_lcot_2023_usd_per_kg: float
    transport_annual_cost_2023_usd: float


@dataclass(frozen=True)
class OperatingPoint:
    """One hydraulically admissible pack-draft operating point."""

    q_bar_a: float
    draft_inlet_bar_a: float
    draft_average_bar_a: float
    pressure_swing_bar: float
    raw_linepack_kg: float
    gathering_ratio: float
    gathering_stages: int
    gathering_motor_power_unit_kw: float
    gathering_installed_rating_unit_kw: float
    enroute_ratio: float
    enroute_stages: int
    enroute_motor_power_unit_kw: float
    enroute_installed_rating_unit_kw: float
    compressor_capex_2018_usd: float
    full_year_energy_kwh: float
    fixed_hardware_feasible: bool
    fixed_rating_margin_gathering_kw: float
    fixed_rating_margin_enroute_kw: float


@dataclass(frozen=True)
class SelectedResult:
    """Selected result on the common service and LCOT boundary."""

    strategy: str
    length_km: float
    buffer_hours: float
    storage_cost_2023_usd_per_kg: float
    annual_delivered_kg: float
    required_buffer_kg: float
    diameter_in: float
    stations: int
    segment_length_km: float
    q_bar_a: float | None
    draft_inlet_bar_a: float | None
    pressure_swing_bar: float
    raw_linepack_kg: float
    credited_linepack_kg: float
    external_storage_kg: float
    gathering_stages: int
    gathering_rating_unit_kw: float
    enroute_stages: int
    enroute_rating_unit_kw: float
    compressor_capex_2018_usd: float
    full_year_energy_kwh: float
    pipeline_capex_2023_usd: float
    compressor_capex_2023_usd: float
    storage_capex_2023_usd: float
    pipeline_lcot_2023_usd_per_kg: float
    compressor_lcot_2023_usd_per_kg: float
    electricity_lcot_2023_usd_per_kg: float
    storage_lcot_2023_usd_per_kg: float
    lcot_2023_usd_per_kg: float
    annual_cost_2023_usd: float
    service_closure_kg: float
    infrastructure_response: str
    uses_linepack: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_scenario(
    basis: StudyBasis,
    length_km: float,
    diameter_in: float,
) -> ScenarioInputs:
    """Build a PiTEA scenario from the study basis."""

    return ScenarioInputs(
        Q_mass_kg_per_day=basis.design_flow_kg_per_day,
        L_total_km=float(length_km),
        d_in=float(diameter_in),
        P_source_g_bar=basis.source_pressure_g_bar,
        P_contract_g_bar=basis.contract_pressure_g_bar,
        P_rate_g_bar=basis.rated_pressure_g_bar,
        route_shares=dict(BROWN_US_AVERAGE_ROUTE_SHARES),
        location_class=basis.location_class,
        F_fluct=1.0,
        buffer_hours=1.0,
        q_grid_points=basis.q_grid_points,
    )


def _zero_hardware(label: str) -> CompressorHardware:
    return CompressorHardware(
        label=label,
        installed_stages=0,
        installed_rating_unit_kw=0.0,
        pack_motor_power_unit_kw=0.0,
        station_capex_2018_usd=0.0,
        pack_ratio=1.0,
    )


def _pack_hardware(
    label: str,
    state: Any,
    compressor: CompressorParams,
) -> CompressorHardware:
    installed_rating = compressor.SF * state.W_unit_kW
    station_capex = compute_station_compressor_capex_usd(
        state.n_stage,
        installed_rating,
        compressor,
    )
    return CompressorHardware(
        label=label,
        installed_stages=state.n_stage,
        installed_rating_unit_kw=installed_rating,
        pack_motor_power_unit_kw=state.W_unit_kW,
        station_capex_2018_usd=station_capex,
        pack_ratio=state.compression_ratio,
    )


def build_transport_catalog(
    *,
    basis: StudyBasis,
    length_km: float,
    diameters_in: Sequence[float],
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
    pipeline_data: PipelineCostData | None = None,
) -> list[PackCandidate]:
    """Enumerate all feasible pack-only transport candidates.

    The pressure basis is controlled by ``StudyBasis``, allowing the buffer
    design and transport-validation cases to use one catalog evaluator.
    """

    physical = PhysicalParams() if physical is None else physical
    compressor = CompressorParams() if compressor is None else compressor
    pipeline_data = (
        build_default_pipeline_cost_data()
        if pipeline_data is None
        else pipeline_data
    )
    econ = study_economic_inputs(basis)
    output: list[PackCandidate] = []

    for diameter_in in diameters_in:
        scenario = make_scenario(basis, length_km, diameter_in)
        pre = precompute_diameter_hydraulics(scenario, physical)
        pipeline_cost = evaluate_pipeline_cost(scenario, econ, pipeline_data)
        unit_flows = compute_unit_flow_rates(
            scenario.Q_mass_kg_per_day,
            compressor.N_op,
            physical.MW_H2_g_per_mol,
        )
        for stations in range(pre.M_station + 1):
            pack = evaluate_pack_state(stations, scenario, physical, pre)
            if not pack.feasible:
                continue
            gathering_state = evaluate_compressor_state(
                label="gathering",
                state="pack",
                P_suc_bar=pre.pressures_abs.P_source_a_bar,
                P_disc_bar=pack.P_in_pack_bar,
                T_suc_K=physical.T_pipe_K,
                unit_flows=unit_flows,
                physical=physical,
                comp=compressor,
            )
            gathering = _pack_hardware(
                "gathering",
                gathering_state,
                compressor,
            )
            if stations == 0:
                enroute = _zero_hardware("enroute")
            else:
                enroute_state = evaluate_compressor_state(
                    label="enroute",
                    state="pack",
                    P_suc_bar=pack.P_out_pack_bar,
                    P_disc_bar=pack.P_in_pack_bar,
                    T_suc_K=physical.T_pipe_K,
                    unit_flows=unit_flows,
                    physical=physical,
                    comp=compressor,
                )
                enroute = _pack_hardware(
                    "enroute",
                    enroute_state,
                    compressor,
                )

            units = compressor.N_op + compressor.N_spare
            compressor_capex = units * (
                gathering.station_capex_2018_usd
                + stations * enroute.station_capex_2018_usd
            )
            full_year_energy = 8760.0 * compressor.N_op * (
                gathering.pack_motor_power_unit_kw
                + stations * enroute.pack_motor_power_unit_kw
            )
            ledger = cost_ledger(
                basis=basis,
                pipeline_capex_2018_usd=pipeline_cost.capex_pipe_usd,
                compressor_capex_2018_usd=compressor_capex,
                full_year_energy_kwh=full_year_energy,
                external_storage_kg=0.0,
                storage_cost_2023_usd_per_kg=0.0,
            )
            output.append(
                PackCandidate(
                    length_km=float(length_km),
                    diameter_in=float(diameter_in),
                    stations=stations,
                    segment_length_km=compute_segment_length_km(
                        length_km,
                        stations,
                    ),
                    scenario=scenario,
                    precompute=pre,
                    pack_state=pack,
                    pipeline_cost=pipeline_cost,
                    gathering=gathering,
                    enroute=enroute,
                    compressor_capex_2018_usd=compressor_capex,
                    full_year_energy_kwh=full_year_energy,
                    transport_lcot_2023_usd_per_kg=ledger[
                        "lcot_2023_usd_per_kg"
                    ],
                    transport_annual_cost_2023_usd=ledger[
                        "annual_cost_2023_usd"
                    ],
                )
            )
    if not output:
        raise RuntimeError(
            f"No feasible transport candidates at L={length_km} km"
        )
    return output


def select_transport(catalog: Sequence[PackCandidate]) -> PackCandidate:
    """Select the pack-only LCOT optimum with deterministic tie-breaking."""

    return min(
        catalog,
        key=lambda candidate: (
            round(candidate.transport_lcot_2023_usd_per_kg, 10),
            candidate.diameter_in,
            candidate.stations,
        ),
    )


def _q_values(bounds: Any, points: int) -> list[float]:
    if not bounds.feasible:
        return []
    if points < 2 or math.isclose(
        bounds.q_lower_bar,
        bounds.q_upper_bar,
        abs_tol=1.0e-12,
    ):
        return [bounds.q_lower_bar]
    step = (bounds.q_upper_bar - bounds.q_lower_bar) / (points - 1)
    return [bounds.q_lower_bar + index * step for index in range(points)]


def _fixed_compressor_duty(
    *,
    suction_bar: float,
    discharge_bar: float,
    hardware: CompressorHardware,
    unit_flows: Any,
    physical: PhysicalParams,
    compressor: CompressorParams,
    preserve_sizing_margin: bool,
) -> tuple[bool, float, float, float]:
    """Evaluate one duty without changing frozen stages or rating."""

    if hardware.installed_stages == 0:
        feasible = discharge_bar <= suction_bar * (1.0 + 1.0e-10)
        margin = hardware.installed_rating_unit_kw
        return feasible, 1.0, 0.0, margin

    ratio = compute_compression_ratio(discharge_bar, suction_bar)
    if ratio > compressor.r_max**hardware.installed_stages + 1.0e-10:
        return False, ratio, math.inf, -math.inf
    z_comp = compute_state_Z_from_nominal_pressure(
        0.5 * (suction_bar + discharge_bar),
        physical,
    )
    shaft_kw = compute_shaft_power_kW(
        ratio,
        hardware.installed_stages,
        z_comp,
        physical.T_pipe_K,
        physical.R_J_per_molK,
        unit_flows.Q_mol_per_s_unit,
        physical.gamma,
        compressor.eta_poly,
    )
    eta_motor = motor_efficiency_hdsam(
        shaft_kw,
        compressor.motor_efficiency,
    )
    motor_kw = 0.0 if shaft_kw == 0.0 else shaft_kw / eta_motor
    tested_kw = compressor.SF * motor_kw if preserve_sizing_margin else motor_kw
    margin_kw = hardware.installed_rating_unit_kw - tested_kw
    return margin_kw >= -1.0e-8, ratio, motor_kw, margin_kw


def _operating_point_at_q(
    *,
    candidate: PackCandidate,
    basis: StudyBasis,
    q_bar: float,
    strict_fixed_hardware: bool,
    preserve_sizing_margin: bool,
    physical: PhysicalParams,
    compressor: CompressorParams,
    bounds: Any,
) -> OperatingPoint:
    """Evaluate one q value for either joint or strict-fixed hardware."""

    unit_flows = compute_unit_flow_rates(
        candidate.scenario.Q_mass_kg_per_day,
        compressor.N_op,
        physical.MW_H2_g_per_mol,
    )
    draft_inlet = safe_sqrt_nonnegative(q_bar**2 + bounds.H_draft_bar2)
    draft_average = average_pressure_bar(
        draft_inlet,
        q_bar,
        physical.use_exact_average_pressure,
    )
    pressure_swing = max(
        0.0,
        candidate.pack_state.P_avg_pack_bar - draft_average,
    )
    linepack = (
        candidate.precompute.V_pipe_m3
        * physical.beta_slope_kg_per_m3_per_bar
        * pressure_swing
    )

    if strict_fixed_hardware:
        g_feasible, g_ratio, g_power, g_margin = _fixed_compressor_duty(
            suction_bar=candidate.precompute.pressures_abs.P_source_a_bar,
            discharge_bar=draft_inlet,
            hardware=candidate.gathering,
            unit_flows=unit_flows,
            physical=physical,
            compressor=compressor,
            preserve_sizing_margin=preserve_sizing_margin,
        )
        if candidate.stations == 0:
            e_feasible, e_ratio, e_power, e_margin = (
                True,
                1.0,
                0.0,
                0.0,
            )
        else:
            e_feasible, e_ratio, e_power, e_margin = (
                _fixed_compressor_duty(
                    suction_bar=q_bar,
                    discharge_bar=draft_inlet,
                    hardware=candidate.enroute,
                    unit_flows=unit_flows,
                    physical=physical,
                    compressor=compressor,
                    preserve_sizing_margin=preserve_sizing_margin,
                )
            )
        full_year_energy = 8760.0 * compressor.N_op * (
            max(candidate.gathering.pack_motor_power_unit_kw, g_power)
            + candidate.stations
            * max(candidate.enroute.pack_motor_power_unit_kw, e_power)
        )
        return OperatingPoint(
            q_bar_a=q_bar,
            draft_inlet_bar_a=draft_inlet,
            draft_average_bar_a=draft_average,
            pressure_swing_bar=pressure_swing,
            raw_linepack_kg=max(0.0, linepack),
            gathering_ratio=g_ratio,
            gathering_stages=candidate.gathering.installed_stages,
            gathering_motor_power_unit_kw=g_power,
            gathering_installed_rating_unit_kw=(
                candidate.gathering.installed_rating_unit_kw
            ),
            enroute_ratio=e_ratio,
            enroute_stages=candidate.enroute.installed_stages,
            enroute_motor_power_unit_kw=e_power,
            enroute_installed_rating_unit_kw=(
                candidate.enroute.installed_rating_unit_kw
            ),
            compressor_capex_2018_usd=(
                candidate.compressor_capex_2018_usd
            ),
            full_year_energy_kwh=full_year_energy,
            fixed_hardware_feasible=g_feasible and e_feasible,
            fixed_rating_margin_gathering_kw=g_margin,
            fixed_rating_margin_enroute_kw=e_margin,
        )

    q_result = evaluate_one_q_candidate(
        q_bar=q_bar,
        n_stations=candidate.stations,
        scenario=candidate.scenario,
        physical=physical,
        comp=compressor,
        econ=study_economic_inputs(basis),
        pre=candidate.precompute,
        pack_state=candidate.pack_state,
        draft_bounds=bounds,
        unit_flows=unit_flows,
        pipeline_cost=candidate.pipeline_cost,
    )
    return OperatingPoint(
        q_bar_a=q_bar,
        draft_inlet_bar_a=q_result.P_in_draft_bar,
        draft_average_bar_a=q_result.P_avg_draft_bar,
        pressure_swing_bar=max(0.0, q_result.delta_P_avg_bar),
        raw_linepack_kg=max(0.0, q_result.M_lp_kg),
        gathering_ratio=q_result.gathering.draft.compression_ratio,
        gathering_stages=q_result.gathering.governing_n_stage,
        gathering_motor_power_unit_kw=(
            q_result.gathering.governing_W_unit_kW
        ),
        gathering_installed_rating_unit_kw=q_result.gathering.W_req_unit_kW,
        enroute_ratio=(
            1.0
            if candidate.stations == 0
            else q_result.enroute.draft.compression_ratio
        ),
        enroute_stages=q_result.enroute.governing_n_stage,
        enroute_motor_power_unit_kw=q_result.enroute.governing_W_unit_kW,
        enroute_installed_rating_unit_kw=q_result.enroute.W_req_unit_kW,
        compressor_capex_2018_usd=q_result.capex_comp_total_usd,
        full_year_energy_kwh=(
            q_result.gathering.annual_energy_kWh
            + q_result.enroute.annual_energy_kWh
        ),
        fixed_hardware_feasible=True,
        fixed_rating_margin_gathering_kw=math.nan,
        fixed_rating_margin_enroute_kw=math.nan,
    )


def operating_curve(
    *,
    candidate: PackCandidate,
    basis: StudyBasis,
    strict_fixed_hardware: bool,
    preserve_sizing_margin: bool = False,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> list[OperatingPoint]:
    """Build the admissible q curve for joint or strict-fixed evaluation."""

    physical = PhysicalParams() if physical is None else physical
    compressor = CompressorParams() if compressor is None else compressor
    bounds = evaluate_draft_state_bounds(
        candidate.stations,
        candidate.scenario,
        physical,
        candidate.precompute,
        candidate.pack_state,
    )
    if not bounds.feasible:
        return []
    return [
        _operating_point_at_q(
            candidate=candidate,
            basis=basis,
            q_bar=q_bar,
            strict_fixed_hardware=strict_fixed_hardware,
            preserve_sizing_margin=preserve_sizing_margin,
            physical=physical,
            compressor=compressor,
            bounds=bounds,
        )
        for q_bar in _q_values(bounds, basis.q_grid_points)
    ]


def _exact_operating_point(
    *,
    candidate: PackCandidate,
    basis: StudyBasis,
    q_bar: float,
    strict_fixed_hardware: bool,
    preserve_sizing_margin: bool,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> OperatingPoint:
    """Evaluate one arbitrary q value for exact-boundary refinement."""

    physical = PhysicalParams() if physical is None else physical
    compressor = CompressorParams() if compressor is None else compressor
    bounds = evaluate_draft_state_bounds(
        candidate.stations,
        candidate.scenario,
        physical,
        candidate.precompute,
        candidate.pack_state,
    )
    if not bounds.feasible or not (
        bounds.q_lower_bar - 1.0e-10
        <= q_bar
        <= bounds.q_upper_bar + 1.0e-10
    ):
        raise ValueError("q_bar is outside the candidate's draft interval")
    return _operating_point_at_q(
        candidate=candidate,
        basis=basis,
        q_bar=q_bar,
        strict_fixed_hardware=strict_fixed_hardware,
        preserve_sizing_margin=preserve_sizing_margin,
        physical=physical,
        compressor=compressor,
        bounds=bounds,
    )


def _requirement_boundary_point(
    *,
    candidate: PackCandidate,
    curve: Sequence[OperatingPoint],
    basis: StudyBasis,
    required_linepack_kg: float,
    strict_fixed_hardware: bool,
    preserve_sizing_margin: bool,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> OperatingPoint | None:
    """Solve for the shallowest q that supplies exactly the requirement."""

    if required_linepack_kg <= 0.0 or not curve:
        return None
    ordered = sorted(curve, key=lambda point: point.q_bar_a)
    low = ordered[0]
    high = ordered[-1]
    if not (
        high.raw_linepack_kg - 1.0e-6
        <= required_linepack_kg
        <= low.raw_linepack_kg + 1.0e-6
    ):
        return None
    q_low = low.q_bar_a
    q_high = high.q_bar_a
    point = high
    for _ in range(60):
        q_mid = 0.5 * (q_low + q_high)
        point = _exact_operating_point(
            candidate=candidate,
            basis=basis,
            q_bar=q_mid,
            strict_fixed_hardware=strict_fixed_hardware,
            preserve_sizing_margin=preserve_sizing_margin,
            physical=physical,
            compressor=compressor,
        )
        if point.raw_linepack_kg > required_linepack_kg:
            q_low = q_mid
        else:
            q_high = q_mid
        if abs(point.raw_linepack_kg - required_linepack_kg) <= 1.0e-3:
            break
    return point


def _fixed_feasibility_boundary_point(
    *,
    candidate: PackCandidate,
    basis: StudyBasis,
    preserve_sizing_margin: bool,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> OperatingPoint | None:
    """Return maximum accessible linepack with frozen hardware."""

    physical = PhysicalParams() if physical is None else physical
    compressor = CompressorParams() if compressor is None else compressor
    bounds = evaluate_draft_state_bounds(
        candidate.stations,
        candidate.scenario,
        physical,
        candidate.precompute,
        candidate.pack_state,
    )
    if not bounds.feasible:
        return None

    low = _exact_operating_point(
        candidate=candidate,
        basis=basis,
        q_bar=bounds.q_lower_bar,
        strict_fixed_hardware=True,
        preserve_sizing_margin=preserve_sizing_margin,
        physical=physical,
        compressor=compressor,
    )
    if low.fixed_hardware_feasible:
        return low

    high = _exact_operating_point(
        candidate=candidate,
        basis=basis,
        q_bar=bounds.q_upper_bar,
        strict_fixed_hardware=True,
        preserve_sizing_margin=preserve_sizing_margin,
        physical=physical,
        compressor=compressor,
    )
    if not high.fixed_hardware_feasible:
        return None

    q_infeasible = low.q_bar_a
    q_feasible = high.q_bar_a
    feasible_point = high
    for _ in range(80):
        q_mid = 0.5 * (q_infeasible + q_feasible)
        point = _exact_operating_point(
            candidate=candidate,
            basis=basis,
            q_bar=q_mid,
            strict_fixed_hardware=True,
            preserve_sizing_margin=preserve_sizing_margin,
            physical=physical,
            compressor=compressor,
        )
        if point.fixed_hardware_feasible:
            q_feasible = q_mid
            feasible_point = point
        else:
            q_infeasible = q_mid
        if q_feasible - q_infeasible <= 1.0e-11:
            break
    return feasible_point


def _response_class(
    transport: PackCandidate,
    selected_candidate: PackCandidate,
    point: OperatingPoint | None,
) -> str:
    if selected_candidate.diameter_in != transport.diameter_in:
        return "Diameter change"
    if selected_candidate.stations != transport.stations:
        return "Station-count change"
    if point is None:
        return "Transport assets retained"
    stage_change = (
        point.gathering_stages != transport.gathering.installed_stages
        or point.enroute_stages != transport.enroute.installed_stages
    )
    rating_change = (
        abs(
            point.gathering_installed_rating_unit_kw
            - transport.gathering.installed_rating_unit_kw
        )
        > max(1.0, 0.005 * transport.gathering.installed_rating_unit_kw)
        or abs(
            point.enroute_installed_rating_unit_kw
            - transport.enroute.installed_rating_unit_kw
        )
        > max(1.0, 0.005 * transport.enroute.installed_rating_unit_kw)
    )
    if stage_change or rating_change:
        return "Compressor resize"
    return "Transport assets retained"


def _selected_result(
    *,
    strategy: str,
    candidate: PackCandidate,
    transport: PackCandidate,
    point: OperatingPoint | None,
    basis: StudyBasis,
    buffer_hours: float,
    storage_cost_2023_usd_per_kg: float,
    credited_linepack_kg: float,
) -> SelectedResult:
    required = basis.buffer_mass_kg(buffer_hours)
    credited = min(required, max(0.0, credited_linepack_kg))
    external = max(0.0, required - credited)
    if point is None:
        comp_capex = candidate.compressor_capex_2018_usd
        energy = candidate.full_year_energy_kwh
        q_bar = None
        draft_inlet = None
        swing = 0.0
        raw_linepack = 0.0
        g_stages = candidate.gathering.installed_stages
        g_rating = candidate.gathering.installed_rating_unit_kw
        e_stages = candidate.enroute.installed_stages
        e_rating = candidate.enroute.installed_rating_unit_kw
    else:
        comp_capex = point.compressor_capex_2018_usd
        energy = point.full_year_energy_kwh
        q_bar = point.q_bar_a
        draft_inlet = point.draft_inlet_bar_a
        swing = point.pressure_swing_bar
        raw_linepack = point.raw_linepack_kg
        g_stages = point.gathering_stages
        g_rating = point.gathering_installed_rating_unit_kw
        e_stages = point.enroute_stages
        e_rating = point.enroute_installed_rating_unit_kw
    ledger = cost_ledger(
        basis=basis,
        pipeline_capex_2018_usd=candidate.pipeline_cost.capex_pipe_usd,
        compressor_capex_2018_usd=comp_capex,
        full_year_energy_kwh=energy,
        external_storage_kg=external,
        storage_cost_2023_usd_per_kg=storage_cost_2023_usd_per_kg,
    )
    response = (
        "Transport assets retained"
        if strategy != "Joint design"
        else _response_class(transport, candidate, point)
    )
    closure = required - credited - external
    return SelectedResult(
        strategy=strategy,
        length_km=candidate.length_km,
        buffer_hours=buffer_hours,
        storage_cost_2023_usd_per_kg=storage_cost_2023_usd_per_kg,
        annual_delivered_kg=basis.annual_delivered_kg,
        required_buffer_kg=required,
        diameter_in=candidate.diameter_in,
        stations=candidate.stations,
        segment_length_km=candidate.segment_length_km,
        q_bar_a=q_bar,
        draft_inlet_bar_a=draft_inlet,
        pressure_swing_bar=swing,
        raw_linepack_kg=raw_linepack,
        credited_linepack_kg=credited,
        external_storage_kg=external,
        gathering_stages=g_stages,
        gathering_rating_unit_kw=g_rating,
        enroute_stages=e_stages,
        enroute_rating_unit_kw=e_rating,
        compressor_capex_2018_usd=comp_capex,
        full_year_energy_kwh=energy,
        pipeline_capex_2023_usd=ledger["pipeline_capex_2023_usd"],
        compressor_capex_2023_usd=ledger["compressor_capex_2023_usd"],
        storage_capex_2023_usd=ledger["storage_capex_2023_usd"],
        pipeline_lcot_2023_usd_per_kg=ledger[
            "pipeline_lcot_2023_usd_per_kg"
        ],
        compressor_lcot_2023_usd_per_kg=ledger[
            "compressor_lcot_2023_usd_per_kg"
        ],
        electricity_lcot_2023_usd_per_kg=ledger[
            "electricity_lcot_2023_usd_per_kg"
        ],
        storage_lcot_2023_usd_per_kg=ledger[
            "storage_lcot_2023_usd_per_kg"
        ],
        lcot_2023_usd_per_kg=ledger["lcot_2023_usd_per_kg"],
        annual_cost_2023_usd=ledger["annual_cost_2023_usd"],
        service_closure_kg=closure,
        infrastructure_response=response,
        uses_linepack=credited > 1.0e-6,
    )


def external_storage_only_result(
    *,
    transport: PackCandidate,
    basis: StudyBasis,
    buffer_hours: float,
    storage_cost_2023_usd_per_kg: float,
) -> SelectedResult:
    """Evaluate the transport-then-external-storage strategy."""

    return _selected_result(
        strategy="External storage only",
        candidate=transport,
        transport=transport,
        point=None,
        basis=basis,
        buffer_hours=buffer_hours,
        storage_cost_2023_usd_per_kg=storage_cost_2023_usd_per_kg,
        credited_linepack_kg=0.0,
    )


def _minimum_result(
    candidates: Iterable[SelectedResult],
) -> SelectedResult:
    """Select cost first and shallowest pressure swing within a tight tie."""

    return min(
        candidates,
        key=lambda result: (
            round(result.lcot_2023_usd_per_kg, 10),
            0 if result.q_bar_a is None else 1,
            -math.inf if result.q_bar_a is None else -result.q_bar_a,
            result.diameter_in,
            result.stations,
        ),
    )


def linepack_without_redesign_result(
    *,
    transport: PackCandidate,
    fixed_curve: Sequence[OperatingPoint],
    basis: StudyBasis,
    buffer_hours: float,
    storage_cost_2023_usd_per_kg: float,
    preserve_sizing_margin: bool = True,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> SelectedResult:
    """Evaluate linepack credit while freezing all transport hardware."""

    options = [
        _selected_result(
            strategy="Linepack without redesign",
            candidate=transport,
            transport=transport,
            point=None,
            basis=basis,
            buffer_hours=buffer_hours,
            storage_cost_2023_usd_per_kg=storage_cost_2023_usd_per_kg,
            credited_linepack_kg=0.0,
        )
    ]
    for point in fixed_curve:
        if not point.fixed_hardware_feasible:
            continue
        options.append(
            _selected_result(
                strategy="Linepack without redesign",
                candidate=transport,
                transport=transport,
                point=point,
                basis=basis,
                buffer_hours=buffer_hours,
                storage_cost_2023_usd_per_kg=(
                    storage_cost_2023_usd_per_kg
                ),
                credited_linepack_kg=point.raw_linepack_kg,
            )
        )
    boundary = _requirement_boundary_point(
        candidate=transport,
        curve=fixed_curve,
        basis=basis,
        required_linepack_kg=basis.buffer_mass_kg(buffer_hours),
        strict_fixed_hardware=True,
        preserve_sizing_margin=preserve_sizing_margin,
        physical=physical,
        compressor=compressor,
    )
    if boundary is not None and boundary.fixed_hardware_feasible:
        options.append(
            _selected_result(
                strategy="Linepack without redesign",
                candidate=transport,
                transport=transport,
                point=boundary,
                basis=basis,
                buffer_hours=buffer_hours,
                storage_cost_2023_usd_per_kg=(
                    storage_cost_2023_usd_per_kg
                ),
                credited_linepack_kg=boundary.raw_linepack_kg,
            )
        )
    hardware_boundary = _fixed_feasibility_boundary_point(
        candidate=transport,
        basis=basis,
        preserve_sizing_margin=preserve_sizing_margin,
        physical=physical,
        compressor=compressor,
    )
    if hardware_boundary is not None:
        options.append(
            _selected_result(
                strategy="Linepack without redesign",
                candidate=transport,
                transport=transport,
                point=hardware_boundary,
                basis=basis,
                buffer_hours=buffer_hours,
                storage_cost_2023_usd_per_kg=(
                    storage_cost_2023_usd_per_kg
                ),
                credited_linepack_kg=hardware_boundary.raw_linepack_kg,
            )
        )
    return _minimum_result(options)


def joint_design_result(
    *,
    catalog: Sequence[PackCandidate],
    joint_curves: dict[tuple[float, int], Sequence[OperatingPoint]],
    transport: PackCandidate,
    basis: StudyBasis,
    buffer_hours: float,
    storage_cost_2023_usd_per_kg: float,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> tuple[SelectedResult, list[SelectedResult]]:
    """Select joint design and return its complete ranked candidate set."""

    options: list[SelectedResult] = []
    required = basis.buffer_mass_kg(buffer_hours)
    for candidate in catalog:
        options.append(
            _selected_result(
                strategy="Joint design",
                candidate=candidate,
                transport=transport,
                point=None,
                basis=basis,
                buffer_hours=buffer_hours,
                storage_cost_2023_usd_per_kg=(
                    storage_cost_2023_usd_per_kg
                ),
                credited_linepack_kg=0.0,
            )
        )
        key = (candidate.diameter_in, candidate.stations)
        curve = joint_curves.get(key, [])
        for point in curve:
            options.append(
                _selected_result(
                    strategy="Joint design",
                    candidate=candidate,
                    transport=transport,
                    point=point,
                    basis=basis,
                    buffer_hours=buffer_hours,
                    storage_cost_2023_usd_per_kg=(
                        storage_cost_2023_usd_per_kg
                    ),
                    credited_linepack_kg=point.raw_linepack_kg,
                )
            )
        boundary = _requirement_boundary_point(
            candidate=candidate,
            curve=curve,
            basis=basis,
            required_linepack_kg=required,
            strict_fixed_hardware=False,
            preserve_sizing_margin=True,
            physical=physical,
            compressor=compressor,
        )
        if boundary is not None:
            options.append(
                _selected_result(
                    strategy="Joint design",
                    candidate=candidate,
                    transport=transport,
                    point=boundary,
                    basis=basis,
                    buffer_hours=buffer_hours,
                    storage_cost_2023_usd_per_kg=(
                        storage_cost_2023_usd_per_kg
                    ),
                    credited_linepack_kg=boundary.raw_linepack_kg,
                )
            )
    selected = _minimum_result(options)
    ranked = sorted(
        options,
        key=lambda result: (
            result.lcot_2023_usd_per_kg,
            result.diameter_in,
            result.stations,
            -math.inf if result.q_bar_a is None else -result.q_bar_a,
        ),
    )
    return selected, ranked


def build_curves(
    *,
    catalog: Sequence[PackCandidate],
    basis: StudyBasis,
    strict_fixed_candidate: PackCandidate | None = None,
    preserve_sizing_margin: bool = False,
    physical: PhysicalParams | None = None,
    compressor: CompressorParams | None = None,
) -> tuple[
    dict[tuple[float, int], list[OperatingPoint]],
    list[OperatingPoint] | None,
]:
    """Precompute joint curves and, optionally, one strict fixed curve."""

    joint = {
        (candidate.diameter_in, candidate.stations): operating_curve(
            candidate=candidate,
            basis=basis,
            strict_fixed_hardware=False,
            physical=physical,
            compressor=compressor,
        )
        for candidate in catalog
    }
    fixed = None
    if strict_fixed_candidate is not None:
        fixed = operating_curve(
            candidate=strict_fixed_candidate,
            basis=basis,
            strict_fixed_hardware=True,
            preserve_sizing_margin=preserve_sizing_margin,
            physical=physical,
            compressor=compressor,
        )
    return joint, fixed
