"""Annualization and levelized-cost-of-transport accounting."""

from __future__ import annotations

from .parameters import EconomicParams, StudyBasis


def study_economic_inputs(basis: StudyBasis) -> EconomicParams:
    """Translate the study basis into compressor-envelope inputs."""

    return EconomicParams(
        CRF=basis.annual_capital_charge,
        C_elec_usd_per_kWh=basis.electricity_2018_usd_per_kwh,
        f_om_pipe=basis.pipeline_fixed_om_fraction,
        f_om_comp=0.04,
        f_ins=0.01,
        f_tax=0.01,
        f_permit=0.001,
        C_ext_usd_per_kg=0.0,
        f_om_store=basis.storage_fixed_om_fraction,
    )


def cost_ledger(
    *,
    basis: StudyBasis,
    pipeline_capex_2018_usd: float,
    compressor_capex_2018_usd: float,
    full_year_energy_kwh: float,
    external_storage_kg: float,
    storage_cost_2023_usd_per_kg: float,
) -> dict[str, float]:
    """Return additive LCOT contributions in constant 2023 USD.

    Electricity is first represented as full-year duty and then multiplied by
    capacity factor.  Annual delivered mass is the paper service denominator.
    """

    esc = basis.escalation_2018_to_2023
    annual_mass = basis.annual_delivered_kg
    pipeline_capex_2023 = pipeline_capex_2018_usd * esc
    compressor_capex_2023 = compressor_capex_2018_usd * esc
    storage_capex_2023 = external_storage_kg * storage_cost_2023_usd_per_kg

    pipeline_annual = (
        basis.annual_capital_charge + basis.pipeline_fixed_om_fraction
    ) * pipeline_capex_2023
    compressor_annual = (
        basis.annual_capital_charge + basis.compressor_fixed_om_fraction
    ) * compressor_capex_2023
    electricity_annual = (
        basis.capacity_factor
        * full_year_energy_kwh
        * basis.electricity_2018_usd_per_kwh
        * esc
    )
    storage_annual = (
        basis.annual_capital_charge + basis.storage_fixed_om_fraction
    ) * storage_capex_2023
    total_annual = (
        pipeline_annual
        + compressor_annual
        + electricity_annual
        + storage_annual
    )
    return {
        "pipeline_capex_2023_usd": pipeline_capex_2023,
        "compressor_capex_2023_usd": compressor_capex_2023,
        "storage_capex_2023_usd": storage_capex_2023,
        "pipeline_lcot_2023_usd_per_kg": pipeline_annual / annual_mass,
        "compressor_lcot_2023_usd_per_kg": compressor_annual / annual_mass,
        "electricity_lcot_2023_usd_per_kg": electricity_annual / annual_mass,
        "storage_lcot_2023_usd_per_kg": storage_annual / annual_mass,
        "lcot_2023_usd_per_kg": total_annual / annual_mass,
        "annual_cost_2023_usd": total_annual,
    }
