# Model and provenance limitations

This repository preserves the scope and qualifications stated in the
associated article.

- PiTEA is a steady-state corridor-screening framework. It does not simulate
  transient compressor control, elevation, pipe material integrity, route
  permitting, upstream production, or downstream distribution.
- The linepack representation estimates usable inventory from the difference
  between balanced pack and draft pressure states while continuing the
  prescribed delivery service. It is not a dynamic deliverability simulation.
- Candidate diameters and compressor-station counts are explicitly enumerated
  over the finite paper catalog. Results should not be interpreted as a
  continuous global optimum outside that catalog.
- The uniform annual capital charge `0.08 yr^-1` is an exogenous levelization
  parameter. It is not presented as a discount rate or as a capital-recovery
  factor derived from a specified asset life.
- External-storage cost is a scenario parameter in constant 2023
  USD/kg-capacity; the package does not choose among storage technologies.
- H2P-derived LCOT is a common-boundary reconstruction made for this paper.
  It is not an LCOT value published by H2P.
- The HDSAM diameter values are secondary values reported in the H2P manual,
  not independent HDSAM simulations made by this project.
- The compressor equipment-cost coefficient
  `a_comp_2018_usd = 2253.7` is preserved from the verified implementation.
  As noted in the Supporting Information, its exact upstream installation-
  factor provenance could not be fully resolved. This limitation is retained
  explicitly rather than silently changing the coefficient during cleanup.
- Literature metrics are converted only when their dimensions and service
  boundaries permit an auditable conversion. Otherwise the source-reported
  metric is retained.
