# Computational result map

This ledger connects each computational display in the article to its
reproduction output and verified reference.

| Article evidence | Reproduction output | Verified reference |
|---|---|---|
| LCOT matrix over 48 distance–capacity cases | `outputs/transport_results/data/lcot_comparison.csv`; `outputs/transport_results/tables/lcot_matrix.tex` | `reference_results/transport_results/lcot_comparison.csv`; `reference_results/transport_results/tables/lcot_matrix.tex` |
| Published diameter grid over 30 cases | `outputs/transport_results/data/diameter_comparison.csv`; `outputs/transport_results/tables/diameter_comparison.tex` | corresponding paths under `reference_results/transport_results/` |
| Representative transport designs and costs | `outputs/transport_results/tables/representative_costs.tex` | `reference_results/transport_results/tables/representative_costs.tex` |
| Mean fixed-design cost attribution | `outputs/transport_results/data/fixed_design_attribution.csv`; `outputs/transport_results/figures/lcot_cost_components.tex` | corresponding transport-result references |
| Buffer-design regime map over 105 service points | `outputs/buffer_design/data/selected_results.csv`; `outputs/buffer_design/figures/regime_map.{png,pdf}` | `reference_results/buffer_design/selected_results.csv`; `reference_results/buffer_design/figures/regime_map.png` |
| Three-strategy focal comparison | `outputs/buffer_design/data/focal_counterfactuals.csv`; `outputs/buffer_design/tables/counterfactuals.tex` | corresponding buffer-design references |
| Focal mechanism figure | `outputs/buffer_design/data/mechanism_slice.csv`; `outputs/buffer_design/figures/mechanism.{png,pdf}` | `reference_results/buffer_design/mechanism_slice.csv`; `reference_results/buffer_design/figures/mechanism.png` |
| Supporting-information input ledger | `outputs/buffer_design/tables/inputs.tex` | `reference_results/buffer_design/tables/inputs.tex` |
| Supporting-information robustness table | `outputs/buffer_design/data/throughput_robustness.csv`; `outputs/buffer_design/tables/robustness.tex` | corresponding buffer-design references |
| Supporting-information numerical audit | `outputs/buffer_design/data/q_grid_refinement.csv`; `outputs/buffer_design/data/fixed_rating_audit.csv`; `outputs/buffer_design/tables/numerical_audit.tex` | corresponding buffer-design references |
| Supporting-information literature ledger | `outputs/buffer_design/data/literature_ledger.csv`; `outputs/buffer_design/tables/literature.tex` | curated input in `data/literature/`; table under `reference_results/buffer_design/tables/` |

## Transport validation anchors

- 48 paired transport cases, including 38 feasible in both catalogs;
- mean absolute relative LCOT difference: 4.7501641384%;
- 34 of 38 common cases within 10%, and all 38 within 15%;
- 31 nominal-diameter matches and 23 diameter–station matches;
- 22 nominal-diameter matches on the separate 30-case published grid.

## Joint pipeline and buffer design anchors

- 105 service points and 315 strategy selections;
- 658 feasible zero-buffer transport candidates across the five corridor
  lengths;
- focal LCOTs: 0.8324838026, 0.7695886980, and 0.4734335831 USD/kg for
  external storage only, linepack without redesign, and joint design;
- focal designs: 30 in./0 stations, 30 in./0 stations, and 42 in./4 stations;
- linepack without redesign: 524.125871 t; joint-design linepack:
  4109.589040 t;
- joint-design saving relative to external storage only: 43.12999464%.

`tools/verify_outputs.py` checks these result ledgers and anchors with tight
floating-point tolerances.
