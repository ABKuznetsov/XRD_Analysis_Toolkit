# Crystal Mechanics

Desktop analyzer of crystal mechanics with a hierarchy-first model:

```text
atoms → coordination polyhedra → structural units
      → rigid blocks → structure skeleton → topology
```

This is not merely another structure viewer. The application should explain which
parts of a structure behave as rigid units, how those units are connected, and
how their rotations, translations and distortions evolve across temperature,
pressure or composition series.

## Why this architecture

The nearby `structure_bulder` project already contains useful chemistry,
topology and PyVista/VTK foundations, but its polyhedron renderer is currently a
placeholder and its topology dimensionality is only a graph-degree heuristic.
This project keeps the proven desktop stack while giving hierarchy objects their
own stable data model.

Comparison of the main Python options:

| Project / stack | Strength | Limitation for this product |
|---|---|---|
| [ASE GUI](https://ase-lib.org/ase/visualize/visualize.html) | Broad structure/trajectory I/O and atomistic workflow | Atom-oriented; no rigid-block hierarchy |
| [pymatgen StructureVis](https://pymatgen.org/pymatgen.vis.html) | VTK viewer, bonds and polyhedra | Viewer primitives, not a block-analysis product |
| [Crystal Toolkit](https://docs.crystaltoolkit.org/) | Excellent interactive materials components | Dash/web application rather than a native XRD/RAMAN-style desktop tool |
| [PyVistaQt](https://qt.pyvista.org/) | Modern Qt-embedded VTK rendering and mesh support | Rendering backend only; crystallographic semantics must be built |
| `structure_bulder` | Chemistry rules, local environments, topology, builder workflows | Viewer does not yet implement real polyhedra or hierarchical blocks |

Decision: use **PySide6 + PyVistaQt/VTK** for the desktop application, Gemmi for
CIF, and explicit analysis models for polyhedra, blocks and hinges. This matches
the existing scientific application family and leaves room for volume data,
isosurfaces, picking and diagnostic overlays.

## Implemented prototype

- CIF load with Gemmi, the XRD environment's pymatgen reader, and a basic fallback parser;
- symmetry expansion;
- atoms, bonds and real coordination-polyhedron surfaces;
- six user-facing mechanics levels following the reference concept;
- first-pass rigid-block detection;
- flexible shared-ligand hinge detection;
- object tree with polyhedron distortion and block rigidity prior;
- supercell controls, axis views, screenshot and CIF drag-and-drop;
- Kabsch decomposition for block rotation, translation and residual distortion;
- multi-CIF series analysis with block motion and connector-angle changes;
- modern light scientific UI consistent with the XRD/RAMAN family;
- material-batched VTK rendering for repeated atoms, bonds, polyhedra and
  mechanical blocks; stable scientific source indices remain attached to mesh
  cells for selection while actor count no longer grows with every object;
- bundled published average gehlenite Ca₂Al₂SiO₇ structure (`P -4 21 m`)
  with mixed Al/Si T2 tetrahedral units, T1 AlO₄ linkers and separate
  interlayer CaO₈ coordination units;
- a dedicated **Analysis workspace** (`Analysis → Open Analysis Workspace`)
  with Standard, Inorganic/Mineral, CRAFT Mechanics, Full, and Custom
  report presets;
- ESD-aware source-CIF values: original numeric tokens, standard uncertainties,
  missing/unknown states, units, and provenance are retained separately from
  the floating-point geometry used by the viewer;
- Stage A publication tables for crystal/refinement data, asymmetric atomic
  sites, ADPs, bond lengths, and bond angles; reported `_geom_*` records take
  precedence over calculated geometry and calculated values never receive
  invented uncertainties;
- CSV export for the current selected table and JSON export for the selected
  report catalogue, including provenance, ESDs, calculation settings, warnings,
  publication flags, and stable links to structural objects;

Unavailable catalogue sections remain visible with their planned delivery
stage. In particular, coordination/polyhedral descriptors and bond-valence
analysis belong to Stage B, while hierarchy/DOF publication tables and linked
table-to-3D selection belong to Stage C.

The current block detector deliberately uses an explainable prior:

- edge/face sharing → same rigid-block candidate;
- corner sharing → potentially flexible hinge.

This is a starting hypothesis, not a crystallographic verdict. A later
temperature-series analysis can override it using measured bond/angle
covariances.

## Comparison descriptor definitions

The comparison backend uses explicit, versioned definitions rather than a
single opaque “structure similarity” percentage:

- **Mo–O distortion index (DI):** mean absolute deviation of all Mo–O bond
  lengths from their mean, divided by that mean;
- **Mo off-centering:** Cartesian distance between Mo and the centroid of all
  ligand vertices in its MoO₆ coordination environment;
- **d₆−d₅:** difference between the sixth and fifth distances after sorting all
  six Mo–O distances; the sixth ligand is never discarded;
- **strong [5+1]:** the reported fraction with d₆−d₅ above the selected
  threshold (default 0.25 Å), while the continuous d₆−d₅ distribution remains
  available;
- **periodic rank:** matrix rank of lattice-translation closure vectors around
  graph cycles (0D/1D/2D/3D), so a single translated tree edge is not
  mislabelled as a chain;
- **comparison colours:** descriptor-specific absolute tolerances; absent
  values are shown as unavailable and never replaced with zero.

## Compare two structures

1. Open or drag one or several CIF files directly into the main window. They
   remain available as separate collapsed roots in the Hierarchy Explorer.
2. Check exactly two structures using the checkbox to the left of each root.
   The tree has one column, no A/B columns, and a third check is not accepted.
3. Press **Compare structures** below the tree. The central view splits into
   equal A/B 3D panes.
4. Move the pointer over a pane to make it active. With **Linked rotation** on,
   rotating the active pane rotates both; turn it off to adjust one projection.
5. Open **Comparison table** for descriptor-specific similarities,
   differences, methods, warnings and 3D focus.
6. Export the table as CSV/JSON or save synchronized A/B PNG images.

## Editable BFDH morphology

1. Open a CIF and select the **Morphology** tab. The hierarchy tree and right
   inspector remain visible.
2. The application uses the full space-group operations: rotational parts
   form symmetry-equivalent `{hkl}` families, while centring translations,
   screw axes and glide planes determine systematic absences.
3. The table reports `d(hkl)`, first allowed reflection order, effective
   spacing, the original BFDH distance, current editable distance, area and
   surface fraction. `rho` is relative and dimensionless; it is not an
   absolute particle size.
4. Edit **Current rho** to rebuild the shape, disable a family with its
   checkbox, or add a signed `(hkl)` family. Complementary polar faces remain
   separate unless an actual symmetry operation relates them.
5. Save manual work to a separate `.morphology.json` sidecar or export CSV and
   PNG. The source CIF is never changed.

BFDH is a geometric morphology prediction, not a thermodynamic equilibrium
shape. DSC measurements do not provide the orientation-dependent surface
energies required for a Wulff construction. A future Wulff mode can reuse this
editor when calculated `gamma(hkl)` values become available.

## macOS installer

Build the Raman-style installer on macOS with:

```bash
zsh scripts/build_macos_pkg.command
```

It produces `dist/CRAFT_macOS_<version>.pkg`, installs
`CRAFT.app` in `/Applications`, and reuses the shared Python 3.11/3.12
environment at `~/Library/Application Support/Sci/env`.

## Run

The launcher automatically selects the compatible XRD Python environment:

```bash
cd "/Users/artem/Yandex.Disk.localized/Python/XRD/вивер"
./run_viewer.command
```

Without a file argument the application opens an empty session and waits for
Open or drag-and-drop. The bundled gehlenite remains available from the
Examples menu. An explicit CIF can be passed:

```bash
./run_viewer.command examples/hinged_silicate.cif
```

Opening CIF and XPFF files is progressive: the atom model becomes interactive
as soon as parsing finishes, while bonds, coordination polyhedra, structural
units and topology are calculated in a background worker and installed stage by
stage. Reopening an unchanged structure reuses the persistent structural cache.

## Product roadmap

1. **VESTA parity:** selection/picking, labels, editable bond rules,
   occupancy/ADP, polyhedra by center and ligand, POSCAR/RES/CIF export.
2. **Periodic topology:** quotient graph with lattice translation labels,
   rigorous 0D/1D/2D/3D rank, chain/ribbon/layer/framework/cage recognition.
3. **Block workbench:** merge/split/pin block commands, confidence and evidence,
   saved user corrections, block fingerprints.
4. **ThermoXRD:** match blocks across refinements, unwrap periodic coordinates,
   calculate rotation axes, translations, internal strain and connector angles,
   then animate the physically meaningful degrees of freedom.
5. **Series learning:** use covariance across temperature/pressure to infer which
   distances are rigid and which angles are flexible, with deterministic
   chemistry rules as priors.
