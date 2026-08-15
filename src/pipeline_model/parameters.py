"""Model inputs and fixed parameter data used by PiTEA.

Keeping the analysis defaults in one module makes the physical and economic
assumptions directly auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


BROWN_REQUIRED_CATEGORIES = ("mat", "labor", "misc", "row")
BROWN_NOMINAL_DIAMETERS_IN = (
    4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 30.0, 36.0, 42.0,
)

# Arithmetic mean of the nine H2P regional cases.  RMGP, SEPN, and SWCA each
# occur twice; NE, MA, and GL each occur once.
BROWN_US_AVERAGE_ROUTE_SHARES = {
    "NE": 1.0 / 9.0,
    "MA": 1.0 / 9.0,
    "GL": 1.0 / 9.0,
    "RMGP": 2.0 / 9.0,
    "SEPN": 2.0 / 9.0,
    "SWCA": 2.0 / 9.0,
}


@dataclass(frozen=True)
class ScenarioInputs:
    """Hydrogen pipeline scenario used by the PiTEA model."""

    Q_mass_kg_per_day: float
    L_total_km: float
    d_in: float
    P_source_g_bar: float
    P_contract_g_bar: float
    P_rate_g_bar: float
    route_shares: Mapping[str, float]
    location_class: str
    F_fluct: float = 0.15
    buffer_hours: float = 24.0
    q_grid_points: int = 101


@dataclass(frozen=True)
class PhysicalParams:
    """Physical and hydraulic parameters."""

    P_amb_bar: float = 1.01325
    T_pipe_K: float = 298.15
    R_J_per_molK: float = 8.314462618
    MW_H2_g_per_mol: float = 2.0158
    gamma: float = 1.41
    mu_Pa_s: float = 8.6e-6
    epsilon_mm: float = 0.0457
    L_min_seg_km: float = 50.0
    beta_Z_per_bar: float = 5.84e-4
    beta_slope_kg_per_m3_per_bar: float = 0.08
    use_exact_average_pressure: bool = True


@dataclass(frozen=True)
class MotorEfficiencyCoeffs:
    """HDSAM polynomial coefficients for motor efficiency."""

    a: float = 0.00008
    b: float = 0.0015
    c: float = 0.0061
    d: float = 0.0311
    e: float = 0.7617


@dataclass(frozen=True)
class CompressorParams:
    """Compressor thermodynamic, redundancy, and cost parameters."""

    eta_poly: float = 0.88
    r_max: float = 2.1
    N_op: int = 2
    N_spare: int = 1
    SF: float = 1.15
    a_comp_2018_usd: float = 2253.7
    b_comp: float = 0.8225
    mu_tech: float = 0.613
    motor_efficiency: MotorEfficiencyCoeffs = field(
        default_factory=MotorEfficiencyCoeffs
    )


@dataclass(frozen=True)
class EconomicParams:
    """Economic inputs used inside compressor envelopes."""

    CRF: float = 0.08
    C_elec_usd_per_kWh: float = 0.0804
    f_om_pipe: float = 0.015
    f_om_comp: float = 0.04
    f_ins: float = 0.01
    f_tax: float = 0.01
    f_permit: float = 0.001
    C_ext_usd_per_kg: float = 600.0
    f_om_store: float = 0.02


@dataclass(frozen=True)
class BrownCoeff:
    """One Brown et al. regional pipeline-cost coefficient triplet."""

    a: float
    b: float
    c: float


@dataclass(frozen=True)
class PipelineCostData:
    """Pipeline cost regressions and hydrogen adjustment lookup tables."""

    brown_coeffs: Mapping[str, Mapping[str, BrownCoeff]]
    mu_mat: Mapping[tuple[float, str], float]
    delta_uc_weld: Mapping[tuple[float, str], float]


@dataclass(frozen=True)
class StudyBasis:
    """Physical and economic basis for the buffer-design analysis."""

    annual_delivered_kg: float = 1.0e9
    capacity_factor: float = 0.90
    source_pressure_g_bar: float = 20.0
    contract_pressure_g_bar: float = 20.0
    rated_pressure_g_bar: float = 70.0
    location_class: str = "Class1"
    annual_capital_charge: float = 0.08
    pipeline_fixed_om_fraction: float = 0.025
    compressor_fixed_om_fraction: float = 0.061
    storage_fixed_om_fraction: float = 0.02
    electricity_2018_usd_per_kwh: float = 0.0804
    escalation_2018_to_2023: float = (544.0 / 660.0) * (1.048**12)
    q_grid_points: int = 241

    @property
    def design_flow_kg_per_day(self) -> float:
        """Rated daily flow that delivers the annual mass at capacity factor."""

        return self.annual_delivered_kg / (365.0 * self.capacity_factor)

    @property
    def average_delivery_kg_per_day(self) -> float:
        """Calendar-average delivered mass."""

        return self.annual_delivered_kg / 365.0

    def buffer_mass_kg(self, equivalent_hours: float) -> float:
        """Storage service corresponding to equivalent delivery hours."""

        if equivalent_hours < 0.0:
            raise ValueError("equivalent_hours must be nonnegative")
        return self.average_delivery_kg_per_day * equivalent_hours / 24.0
