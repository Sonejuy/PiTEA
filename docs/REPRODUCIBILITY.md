# Reproducibility protocol and environment ledger

## Verified environment

| Component | Version | Purpose |
|---|---:|---|
| CPython | 3.14.0 | complete reproduction workflow and tests |
| CPython | 3.13.9 | independent numerical audit |
| NumPy | 2.4.6 | numerical and figure environment |
| Matplotlib | 3.10.9 | article figure rendering |
| `unittest` | Python standard library | test runner |

LaTeX is not required to execute the model or verify its numerical outputs.

## Verification record

The reproducibility checks establish the following:

- the physical, accounting, provenance, and regression tests pass on the
  verified Python environment;
- all 10,088 PiTEA candidates used in the transport comparison are recomputed
  from `pipeline_model`, including 2,751 feasible candidates;
- the 48-case LCOT comparison and 30-case diameter surface reproduce the
  verified numerical references;
- the complete buffer-design sweep reproduces 105 service points, 315 strategy
  selections, and a 658-candidate transport catalog;
- all authoritative CSVs and generated LaTeX tables match their verified
  references;
- the focal joint design is 42 in. with four enroute stations and an LCOT of
  0.4734335831003731 USD/kg;
- both generated PNG figures match the verified images in the pinned plotting
  environment.

Typical execution time on the reference workstation is under one second for
the transport analysis and approximately two minutes for the complete
buffer-design sweep.

## Recommended workflow

1. Create a fresh virtual environment and install `requirements.txt`.
2. Run `python -m unittest discover -s tests -v`.
3. Run `python experiments/reproduce_all.py`.
4. Run `python tools/verify_outputs.py`.
5. Inspect the two generated buffer-design PNG figures visually.

The verifier compares numerical fields using absolute tolerance `1e-9` and
relative tolerance `1e-10`. Text fields and row/column order are compared
exactly. Numerical CSVs and result anchors are the authoritative scientific
acceptance criteria.

## Figure note

PDF files can embed timestamps and other metadata, so binary equality is not a
scientific requirement. Matplotlib 3.10.6 yielded correct numerical data but
visibly clipped figure layouts during testing. Version 3.10.9 is therefore
pinned, and any dependency update requires renewed visual quality assurance.
