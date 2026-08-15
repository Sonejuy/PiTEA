"""Regression tests for transport and buffer-design calculations."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipeline_model as model  # noqa: E402


class BufferDesignModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.basis = model.StudyBasis(
            annual_delivered_kg=0.50e9,
            q_grid_points=81,
        )
        cls.catalog = model.build_transport_catalog(
            basis=cls.basis,
            length_km=800.0,
            diameters_in=[20.0, 24.0, 30.0, 36.0, 42.0],
        )
        cls.transport = model.select_transport(cls.catalog)
        cls.joint_curves, cls.fixed_curve = model.build_curves(
            catalog=cls.catalog,
            basis=cls.basis,
            strict_fixed_candidate=cls.transport,
            preserve_sizing_margin=True,
        )

    def test_design_flow_and_buffer_use_actual_annual_mass(self) -> None:
        self.assertAlmostEqual(
            self.basis.design_flow_kg_per_day,
            0.50e9 / (365.0 * 0.90),
            places=8,
        )
        self.assertAlmostEqual(
            self.basis.buffer_mass_kg(24.0),
            0.50e9 / 365.0,
            places=6,
        )

    def test_regional_weights_are_the_nine_case_arithmetic_mean(self) -> None:
        shares = model.BROWN_US_AVERAGE_ROUTE_SHARES
        self.assertAlmostEqual(sum(shares.values()), 1.0)
        self.assertEqual(shares["NE"], 1.0 / 9.0)
        self.assertEqual(shares["MA"], 1.0 / 9.0)
        self.assertEqual(shares["GL"], 1.0 / 9.0)
        self.assertEqual(shares["RMGP"], 2.0 / 9.0)
        self.assertEqual(shares["SEPN"], 2.0 / 9.0)
        self.assertEqual(shares["SWCA"], 2.0 / 9.0)

    def test_zero_buffer_reproduces_transport_lcot(self) -> None:
        external_storage_only = model.external_storage_only_result(
            transport=self.transport,
            basis=self.basis,
            buffer_hours=0.0,
            storage_cost_2023_usd_per_kg=600.0,
        )
        joint, _ = model.joint_design_result(
            catalog=self.catalog,
            joint_curves=self.joint_curves,
            transport=self.transport,
            basis=self.basis,
            buffer_hours=0.0,
            storage_cost_2023_usd_per_kg=600.0,
        )
        self.assertAlmostEqual(
            external_storage_only.lcot_2023_usd_per_kg,
            self.transport.transport_lcot_2023_usd_per_kg,
            places=10,
        )
        self.assertAlmostEqual(
            joint.lcot_2023_usd_per_kg,
            external_storage_only.lcot_2023_usd_per_kg,
            places=10,
        )

    def test_every_strategy_closes_the_same_buffer_service(self) -> None:
        external_storage_only = model.external_storage_only_result(
            transport=self.transport,
            basis=self.basis,
            buffer_hours=36.0,
            storage_cost_2023_usd_per_kg=600.0,
        )
        fixed = model.linepack_without_redesign_result(
            transport=self.transport,
            fixed_curve=self.fixed_curve or [],
            basis=self.basis,
            buffer_hours=36.0,
            storage_cost_2023_usd_per_kg=600.0,
            preserve_sizing_margin=True,
        )
        joint, _ = model.joint_design_result(
            catalog=self.catalog,
            joint_curves=self.joint_curves,
            transport=self.transport,
            basis=self.basis,
            buffer_hours=36.0,
            storage_cost_2023_usd_per_kg=600.0,
        )
        for result in (external_storage_only, fixed, joint):
            self.assertLess(abs(result.service_closure_kg), 1.0e-6)
            self.assertAlmostEqual(
                result.credited_linepack_kg + result.external_storage_kg,
                result.required_buffer_kg,
                places=6,
            )

    def test_fixed_case_really_freezes_transport_hardware(self) -> None:
        fixed = model.linepack_without_redesign_result(
            transport=self.transport,
            fixed_curve=self.fixed_curve or [],
            basis=self.basis,
            buffer_hours=36.0,
            storage_cost_2023_usd_per_kg=600.0,
            preserve_sizing_margin=True,
        )
        self.assertEqual(fixed.diameter_in, self.transport.diameter_in)
        self.assertEqual(fixed.stations, self.transport.stations)
        self.assertEqual(
            fixed.gathering_stages,
            self.transport.gathering.installed_stages,
        )
        self.assertEqual(
            fixed.enroute_stages,
            self.transport.enroute.installed_stages,
        )
        self.assertAlmostEqual(
            fixed.gathering_rating_unit_kw,
            self.transport.gathering.installed_rating_unit_kw,
        )
        self.assertAlmostEqual(
            fixed.enroute_rating_unit_kw,
            self.transport.enroute.installed_rating_unit_kw,
        )
        self.assertAlmostEqual(
            fixed.compressor_capex_2018_usd,
            self.transport.compressor_capex_2018_usd,
        )

    def test_linepack_strategy_can_choose_external_storage_only(self) -> None:
        external_storage_only = model.external_storage_only_result(
            transport=self.transport,
            basis=self.basis,
            buffer_hours=36.0,
            storage_cost_2023_usd_per_kg=100.0,
        )
        fixed = model.linepack_without_redesign_result(
            transport=self.transport,
            fixed_curve=self.fixed_curve or [],
            basis=self.basis,
            buffer_hours=36.0,
            storage_cost_2023_usd_per_kg=100.0,
            preserve_sizing_margin=True,
        )
        self.assertLessEqual(
            fixed.lcot_2023_usd_per_kg,
            external_storage_only.lcot_2023_usd_per_kg + 1.0e-12,
        )

    def test_external_storage_lcot_uses_uniform_charge_and_two_percent_om(
        self,
    ) -> None:
        external_storage_only = model.external_storage_only_result(
            transport=self.transport,
            basis=self.basis,
            buffer_hours=24.0,
            storage_cost_2023_usd_per_kg=600.0,
        )
        expected = (
            (0.08 + 0.02)
            * 600.0
            * external_storage_only.required_buffer_kg
            / self.basis.annual_delivered_kg
        )
        self.assertTrue(math.isfinite(expected))
        self.assertAlmostEqual(
            external_storage_only.storage_lcot_2023_usd_per_kg,
            expected,
            places=12,
        )

    def test_fixed_rating_frontier_is_independent_of_pressure_grid(
        self,
    ) -> None:
        catalog = model.build_transport_catalog(
            basis=self.basis,
            length_km=2000.0,
            diameters_in=[
                4.0,
                6.0,
                8.0,
                10.0,
                12.0,
                14.0,
                16.0,
                18.0,
                20.0,
                24.0,
                30.0,
                36.0,
                42.0,
            ],
        )
        transport = model.select_transport(catalog)
        results = []
        for points in (41, 481):
            basis = model.StudyBasis(
                annual_delivered_kg=0.50e9,
                q_grid_points=points,
            )
            curve = model.operating_curve(
                candidate=transport,
                basis=basis,
                strict_fixed_hardware=True,
                preserve_sizing_margin=True,
            )
            results.append(
                model.linepack_without_redesign_result(
                    transport=transport,
                    fixed_curve=curve,
                    basis=basis,
                    buffer_hours=36.0,
                    storage_cost_2023_usd_per_kg=600.0,
                    preserve_sizing_margin=True,
                )
            )
        coarse, fine = results
        self.assertAlmostEqual(coarse.q_bar_a or 0.0, fine.q_bar_a or 0.0, 8)
        self.assertAlmostEqual(
            coarse.lcot_2023_usd_per_kg,
            fine.lcot_2023_usd_per_kg,
            10,
        )


if __name__ == "__main__":
    unittest.main()
