# Data provenance

## Transport-validation candidate ledgers

The transport analysis uses two candidate-level engineering ledgers:

- `data/transport_validation/pitea_candidates.csv` contains 10,088 PiTEA
  candidates over the article's distance–capacity matrix.
- `data/transport_validation/h2p_reconstructed_candidates.csv` contains 576
  candidates from the reconstructed H2P configuration.

The files are exact configuration filters and lossless column projections of
the verified engineering datasets. No numeric value was transformed during
data preparation. `candidate_ledger_manifest.json` records the source-dataset
hashes, output hashes, row counts, and retained fields.

During reproduction, PiTEA independently recomputes physical feasibility and
every capital and operating-cost field used for LCOT for all 10,088 PiTEA
candidates. The candidate ledger also retains the BEP-selected design flag
needed to count objective switches. The resulting audit is written to
`outputs/transport_results/data/pitea_recomputation_audit.json`.

The reconstructed H2P ledger was built from the public **FECM/NETL Hydrogen
Pipeline Cost Model (2024): Description and User's Manual**,
DOE/NETL-2024/4841, DOI 10.2172/2339568. Published H2P break-even prices serve
as reconstruction checks. For the article comparison, the 15% project
contingency is removed to match PiTEA's pre-contingency capital boundary, and
every candidate is ranked using the same 0.08/yr annual capital charge and
actual annual delivered mass. The resulting quantity is therefore called
**H2P-derived LCOT**; it is not an H2P-published metric.

`data/transport_validation/h2p_bep_targets.csv` contains the public Exhibit 4-4
targets used to validate the reconstruction.
`exhibit45_published_diameters.csv` records the H2P and HDSAM diameters reported
in H2P Exhibit 4-5. The HDSAM entries are secondary values reported by H2P, not
independent HDSAM runs performed for this analysis.

## Pipeline cost relations

PiTEA's regional pipeline-cost coefficients and hydrogen adjustments are
encoded in `src/pipeline_model/pipeline_costs.py`. Their source is Brown,
Reddi, and Elgowainy (2022), “The development of natural gas and hydrogen
pipeline capital cost estimating equations,” *International Journal of
Hydrogen Energy* 47(79), 33813–33826,
DOI 10.1016/j.ijhydene.2022.07.270.

For every candidate, PiTEA evaluates the nine H2P regional cases and takes
their arithmetic mean. The grouped weights `(1,1,1,2,2,2)/9` are weights on
evaluated regional costs; the regression coefficients themselves are not
averaged.

## Literature ledger

`data/literature/buffer_design_literature_ledger.csv` is a manually curated
reporting ledger. It is not an input to the PiTEA optimization. Source-reported
metrics are retained when a service-equivalent LCOT conversion is not
auditable. This distinction prevents quantities with different physical or
financial boundaries from being relabeled as directly comparable LCOT values.

## Licensing boundary

The MIT license covers the code in this repository. Source publications and
external models retain their own terms. The included CSVs contain the numerical
records required to audit the reported analyses and preserve the source
attribution above.
