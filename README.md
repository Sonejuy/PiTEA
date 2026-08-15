# PiTEA reproducibility package

This repository provides the model code, input data, verification tests, and
reference results for **“PiTEA: Physics-Informed Techno-Economic Analysis of
Hydrogen Pipeline Transmission and Buffer Provision.”**

PiTEA jointly represents pipeline hydraulics, compression, pressure-swing
linepack, external buffer storage, infrastructure selection, and levelized
cost of transport (LCOT). The source package follows these methodology domains,
while the experiment scripts reproduce the computational results reported in
the article.

## Analyses reproduced

- **Transport design and cost results:** the 48-case PiTEA/H2P-derived LCOT
  comparison, the 30-case published diameter comparison, representative-case
  costs, and the fixed-design cost attribution. Every PiTEA candidate used in
  the 48-case comparison is recomputed from the included model. The candidate
  ledger also preserves the BEP-selection flag used for the objective-switch
  audit.
- **Joint pipeline and buffer design:** all 105 service points evaluated under
  external storage only, linepack without redesign, and joint design, together
  with the focal counterfactual, mechanism slice, throughput robustness,
  pressure-grid refinement, and fixed-rating audit.

The focal buffer-design case is 0.50 Mt/yr, 1200 km, 72 h, and 600
constant-2023 USD/kg-capacity. The joint design uses a 42 in. pipeline and four
enroute stations, produces an LCOT of 0.4734335831 USD/kg, and reduces LCOT by
43.13% relative to external storage only.

## Quick start

The complete workflow was verified with Python 3.14.0 and independently audited
with Python 3.13.9. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Reproduce each experiment separately:

```bash
python experiments/reproduce_transport_results.py
python experiments/reproduce_buffer_design.py
```

Or run and verify the complete workflow:

```bash
python experiments/reproduce_all.py
python tools/verify_outputs.py
```

Expected wall time on the reference workstation is under one second for the
transport analysis and approximately two minutes for the buffer-design sweep.
Generated files are written beneath `outputs/`, which is excluded from version
control.

## Repository guide

```text
src/pipeline_model/             PiTEA methodology
experiments/                    article reproduction scripts
data/transport_validation/      candidate ledgers and published targets
data/literature/                curated literature-comparison ledger
reference_results/              verified numerical and display references
tests/                          physical, accounting, and regression checks
tools/                          output-verification utility
docs/                           result, data, environment, and scope ledgers
```

The [result map](docs/RESULTS_MAP.md) connects every computational display to
its script, generated file, and verified reference. The
[reproducibility protocol](docs/REPRODUCIBILITY.md) records the verified
software environment and acceptance criteria.

## Reproducibility standard

CSV values and the result anchors checked by `tools/verify_outputs.py` are the
authoritative reproducibility targets. PDF and PNG files can contain renderer
metadata and are not required to be byte-identical. Matplotlib 3.10.9 is pinned
because version 3.10.6 produced clipped layouts even though its numerical data
were correct. Figures should be inspected visually after any dependency change.

The H2P comparison is explicitly labeled **H2P-derived LCOT**. H2P does not
publish this metric; the analysis applies the common accounting convention to
a reconstructed H2P component ledger. See
[`docs/DATA_PROVENANCE.md`](docs/DATA_PROVENANCE.md) before reusing these data.

The three buffer strategies appear directly in the machine-readable results as
`External storage only`, `Linepack without redesign`, and `Joint design`.
Savings are labeled by their denominator: 43.1% is joint design relative to
external storage only, while 38.5% is joint design relative to linepack without
redesign.

## Scope and limitations

This repository supports the analyses reported in the associated article. It
preserves the stated assumptions and finite design catalogs. PiTEA is a
steady-state corridor-screening model and does not represent transient
compressor control, elevation, material-integrity qualification, route
permitting, upstream production, or downstream distribution. Additional
qualifications are listed in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Citation and license

Citation metadata are provided in [`CITATION.cff`](CITATION.cff). The code is
released under the [`MIT License`](LICENSE).

Authors: **Pengfei Chen** and **Valerie M. Thomas**, Georgia Institute of
Technology.
