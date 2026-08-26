# Architecture: Crystal Mechanics / Structural DOF analysis

## Core principle

Rendering is a consumer, not the owner, of crystal-chemistry decisions.

The product question is not only “what does the crystal contain?” but “how does
the crystal function as a mechanical system?”

```text
CIF / pymatgen Structure
        │
        ▼
periodic atomic model
        │
        ▼
shared bond/local-environment graph
        │
        ├── atoms and bonds
        ▼
coordination polyhedra
        │
        ▼
polyhedron quotient graph
        │
        ├── edge/face components ──► rigid-block candidates
        │
        └── corner links ──────────► hinge candidates
        ▼
periodic block graph
        │
        ├── 0D cluster / cage
        ├── 1D chain / ribbon
        ├── 2D layer
        └── 3D framework
```

The same object IDs must feed the tree, selection, rendering, reports, saved
projects and ThermoXRD comparison. A renderer must never silently recompute its
own bonds or polyhedra with different cutoffs.

## Current domain objects

- `CrystalStructure`: lattice, asymmetric sites, expanded sites and metadata.
- `CoordinationPolyhedron`: center, periodic ligand references, bond lengths,
  vertices and distortion.
- `PolyhedronConnection`: corner/edge/face sharing and flexibility prior.
- `StructuralBlock`: member polyhedra/atoms, morphology and rigidity prior.
- `FlexibleConnector`: pair of blocks, shared ligand and pivot coordinate.
- `BlockMotion`: rotation, translation, RMSD and non-rigid distortion.

## Required next algorithm: periodic dimensionality

Classifying a periodic net from average graph degree is incorrect. The next
implementation should use a quotient graph whose edges carry integer lattice
translations. For every connected component:

1. traverse the quotient graph and accumulate image translations;
2. collect independent translation cycles;
3. compute the rank of their integer span;
4. map rank 0/1/2/3 to finite/chain/layer/framework;
5. refine morphology using node degree, rings and component thickness.

This distinguishes a 2D layer from a topologically similar finite sheet and
remains valid when the conventional cell changes.

## Rigid-unit inference

There should be three evidence layers:

1. **Chemical prior:** oxidation, coordination, bond-valence, polyhedron
   distortion and sharing mode.
2. **User model:** explicit merge/split/pin corrections with provenance.
3. **Series evidence:** covariance of internal distances and angles across
   temperature, pressure or composition.

The series evidence is decisive. A candidate fragment is rigid when its
intra-block distance matrix is stable while its pose relative to neighbors
changes. This makes the result measurable instead of merely visual.

## ThermoXRD integration

ThermoXRD should pass refined `pymatgen.Structure` objects through
`crystal_viewer.adapters.from_pymatgen`. The comparison pipeline then:

1. normalizes cells and unwraps periodic coordinates;
2. matches blocks using composition + topology + local geometry fingerprints;
3. aligns matched atom coordinates with Kabsch;
4. reports rigid rotation, translation and residual internal distortion;
5. measures connector angles and hinge-axis changes;
6. animates block transforms while keeping internal geometry fixed on demand.

The output is a compact physical narrative such as:

```text
RB3 rotation       +0.82°
RB3 translation    0.021 Å
RB3 distortion     0.28 %
H2 connector angle +4.91°
```

## Confidence and explainability

Every inferred object needs:

- confidence;
- rule/evidence list;
- warnings;
- manual override;
- stable fingerprint;
- source/refinement provenance.

An automatic block detector should suggest a model, never hide uncertainty.
