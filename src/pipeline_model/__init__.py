"""PiTEA hydrogen pipeline design and cost model.

The package is organized by methodology domain and exposes the API used by the
transport-validation and joint pipeline-and-buffer-design experiments. All
model code and fixed lookup data are self-contained in this package.
"""

from .compressor import (
    CompressorEnvelopeResult,
    CompressorHardware,
    CompressorStateResult,
    UnitFlowRates,
    compute_compression_ratio,
    compute_required_stage_count,
    compute_shaft_power_kW,
    compute_station_compressor_capex_usd,
    compute_unit_flow_rates,
    evaluate_compressor_envelope,
    evaluate_compressor_state,
    motor_efficiency_hdsam,
)
from .design import (
    OperatingPoint,
    PackCandidate,
    SelectedResult,
    build_curves,
    build_transport_catalog,
    external_storage_only_result,
    joint_design_result,
    linepack_without_redesign_result,
    make_scenario,
    operating_curve,
    select_transport,
)
from .economics import cost_ledger, study_economic_inputs
from .hydraulics import (
    DiameterHydraulicPrecompute,
    DraftStateBoundsResult,
    PackStateResult,
    PressureInputsAbsolute,
    average_pressure_bar,
    build_absolute_pressures,
    build_q_grid,
    compute_haaland_friction_factor,
    compute_k_phys,
    compute_m_station,
    compute_pipe_volume_m3,
    compute_reynolds_number,
    compute_segment_length_km,
    compute_state_Z_from_nominal_pressure,
    compute_state_pressure_drop_bar2,
    evaluate_draft_state_bounds,
    evaluate_pack_state,
    precompute_diameter_hydraulics,
    safe_sqrt_nonnegative,
)
from .linepack import DraftStateEvaluationResult, evaluate_one_q_candidate
from .parameters import (
    BROWN_NOMINAL_DIAMETERS_IN,
    BROWN_US_AVERAGE_ROUTE_SHARES,
    BrownCoeff,
    CompressorParams,
    EconomicParams,
    MotorEfficiencyCoeffs,
    PhysicalParams,
    PipelineCostData,
    ScenarioInputs,
    StudyBasis,
)
from .pipeline_costs import (
    PipelineCostResult,
    build_default_pipeline_cost_data,
    compute_brown_natural_gas_cost_2018_usd_per_mile,
    compute_brown_unit_cost_usd_per_inch_mile,
    evaluate_pipeline_cost,
)
from .provenance import (
    MODEL_SOURCE_DIRECTORY,
    model_source_files,
    model_source_sha256,
)


__all__ = [name for name in globals() if not name.startswith("_")]
