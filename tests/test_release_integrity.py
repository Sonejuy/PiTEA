"""Fast package-level checks for inputs, provenance, and paper anchors."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipeline_model as model  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class ReleaseIntegrityTests(unittest.TestCase):
    def test_transport_ledgers_match_manifest(self) -> None:
        data = ROOT / "data" / "transport_validation"
        manifest = json.loads(
            (data / "candidate_ledger_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        for key in ("pitea", "h2p_reconstructed"):
            record = manifest[key]
            path = data / record["output"]
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), record["rows"])
            self.assertEqual(list(rows[0]), record["fields"])
            self.assertEqual(sha256(path), record["output_sha256"])

    def test_reference_metric_anchors_match_the_article(self) -> None:
        transport = json.loads(
            (
                ROOT
                / "reference_results"
                / "transport_results"
                / "metrics.json"
            ).read_text()
        )
        buffer_design = json.loads(
            (
                ROOT
                / "reference_results"
                / "buffer_design"
                / "metrics.json"
            ).read_text()
        )
        self.assertEqual(transport["grid"]["common_feasible_case_count"], 38)
        self.assertAlmostEqual(
            transport["grid"]["mean_absolute_relative_difference_pct"],
            4.750164138378167,
            places=12,
        )
        self.assertEqual(transport["grid"]["nominal_diameter_match_count"], 31)
        self.assertEqual(transport["grid"]["diameter_station_match_count"], 23)
        focal = buffer_design["focal_case"]
        self.assertEqual(focal["joint_design"], [42.0, 4])
        self.assertAlmostEqual(
            focal["joint_design_lcot_2023_usd_per_kg"],
            0.4734335831003731,
            places=12,
        )
        self.assertAlmostEqual(
            focal["joint_saving_vs_external_storage_only_percent"],
            43.129994643832106,
            places=10,
        )

    def test_regional_weights_represent_nine_evaluated_costs(self) -> None:
        shares = model.BROWN_US_AVERAGE_ROUTE_SHARES
        self.assertAlmostEqual(sum(shares.values()), 1.0)
        self.assertEqual(shares["NE"], 1.0 / 9.0)
        self.assertEqual(shares["MA"], 1.0 / 9.0)
        self.assertEqual(shares["GL"], 1.0 / 9.0)
        self.assertEqual(shares["RMGP"], 2.0 / 9.0)
        self.assertEqual(shares["SEPN"], 2.0 / 9.0)
        self.assertEqual(shares["SWCA"], 2.0 / 9.0)

    def test_brown_regression_table_is_preserved(self) -> None:
        expected = {
            "mat": {
                "NE": (10409.0, 0.296847, -0.07257),
                "MA": (9113.0, 0.279875, -0.00840),
                "GL": (8971.0, 0.255012, -0.03138),
                "RMGP": (5813.0, 0.31599, -0.00376),
                "SEPN": (6207.0, 0.38224, -0.05211),
                "SWCA": (5605.0, 0.41642, -0.06441),
            },
            "labor": {
                "NE": (249131.0, -0.33162, -0.17892),
                "MA": (43692.0, 0.05683, -0.10108),
                "GL": (58154.0, -0.14821, -0.10596),
                "RMGP": (10406.0, 0.20953, -0.08419),
                "SEPN": (32094.0, 0.06110, -0.14828),
                "SWCA": (95295.0, -0.53848, 0.03070),
            },
            "misc": {
                "NE": (65990.0, -0.29673, -0.06856),
                "MA": (14616.0, 0.16354, -0.16186),
                "GL": (41238.0, -0.34751, -0.11104),
                "RMGP": (4944.0, 0.17351, -0.07621),
                "SEPN": (11270.0, 0.19077, -0.13669),
                "SWCA": (19211.0, -0.14178, -0.04697),
            },
            "row": {
                "NE": (83124.0, -0.66357, -0.07544),
                "MA": (1942.0, 0.17394, -0.01555),
                "GL": (14259.0, -0.65318, 0.06865),
                "RMGP": (2751.0, -0.28294, 0.00731),
                "SEPN": (9531.0, -0.37284, 0.02616),
                "SWCA": (72634.0, -1.07566, 0.05284),
            },
        }
        data = model.build_default_pipeline_cost_data()
        observed = {
            category: {
                region: (coefficient.a, coefficient.b, coefficient.c)
                for region, coefficient in regional.items()
            }
            for category, regional in data.brown_coeffs.items()
        }
        self.assertEqual(observed, expected)
        self.assertEqual(
            sorted({diameter for diameter, _ in data.mu_mat}),
            list(model.BROWN_NOMINAL_DIAMETERS_IN),
        )

    def test_density_surrogate_matches_documented_pressure_range(self) -> None:
        physical = model.PhysicalParams()
        values = []
        for pressure_bar_a in range(20, 71, 10):
            compressibility = model.compute_state_Z_from_nominal_pressure(
                float(pressure_bar_a), physical
            )
            density = (
                pressure_bar_a
                * 1.0e5
                * (physical.MW_H2_g_per_mol / 1000.0)
                / (
                    compressibility
                    * physical.R_J_per_molK
                    * physical.T_pipe_K
                )
            )
            values.append((compressibility, density))
        self.assertTrue(math.isclose(values[0][0], 1.01168, abs_tol=1.0e-12))
        self.assertTrue(math.isclose(values[-1][0], 1.04088, abs_tol=1.0e-12))
        self.assertTrue(math.isclose(values[0][1], 1.60755, abs_tol=1.0e-5))
        self.assertTrue(math.isclose(values[-1][1], 5.46860, abs_tol=1.0e-5))
        self.assertEqual(physical.beta_slope_kg_per_m3_per_bar, 0.08)

    def test_compressor_cost_provenance_limitation_is_documented(self) -> None:
        text = (ROOT / "docs" / "LIMITATIONS.md").read_text(encoding="utf-8")
        self.assertIn("2253.7", text)
        self.assertIn("provenance", text.lower())


if __name__ == "__main__":
    unittest.main()
