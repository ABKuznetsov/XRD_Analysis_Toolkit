# XRD Analysis Toolkit

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Stable-green.svg)

# Download XRD Phase Finder

**Windows 10/11:** [Download `XRD_Phase_Finder_Setup_1.1.0.exe`](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.1.0/XRD_Phase_Finder_Setup_1.1.0.exe) and run the installer.

**macOS:** [Download `XRD_Phase_Finder_macOS_1.1.0.zip`](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.1.0/XRD_Phase_Finder_macOS_1.1.0.zip), extract it and run `install_macos.command`.

More detailed installation notes are below in [Installation](#installation).

# XRD Phase Finder 1.1.0

Feature release focused on Phase Finder maintainability, background correction and cross-platform setup improvements.

# Introduction

Welcome to the **XRD Analysis Toolkit** project. Its first application, **XRD Phase Finder**, is an open-source Python tool for phase identification from powder X-ray diffraction (XRD) data. It combines experimental pattern handling, element-constrained database search, reference-pattern preview, CIF-based diffraction simulation and practical candidate ranking in one desktop workflow.

XRD Phase Finder is designed for everyday search-match work: import one or many experimental XRD patterns, restrict the chemistry with required or optional elements, search local and online phase sources, compare candidates against the observed pattern, inspect compound cards and build an interpretable set of selected phases.

The project is possible because of the scientific software and crystallographic-data ecosystem around powder diffraction.

Open or publicly accessible data sources and services that XRD Phase Finder can work with include:

- COD (Crystallography Open Database)
- Materials Project (MP), when the user provides their own API key
- AFLOW Database
- OQMD (Open Quantum Materials Database)
- RRUFF Project measured powder patterns
- user-provided CIF folders and local phase libraries

Support for restricted, proprietary or license-controlled sources is under active development. These sources will be available only when the user already has the legal right to access them:

- PDF-2 reference-card data from a user-provided local PDF-2 installation or folder
- CCDC/CSD data through the user's own CCDC Python API installation and valid license/access rights
- any other local commercial, institutional or private crystallographic database supplied by the user

The developers of XRD Phase Finder **do not distribute closed, proprietary or license-controlled databases**. The project may provide optional connectors, import/indexing tools and local search workflows, but access to restricted data remains entirely the user's responsibility. Users must ensure that they have the right to access and process any restricted database, and must follow the license terms, attribution rules and citation requirements of each data source.

XRD Phase Finder also builds on the open-source Python scientific stack, including:

- NumPy and SciPy
- pybaselines
- pyqtgraph
- PySide6 / Qt
- gemmi
- pymatgen, when optional Materials Project workflows are installed

Large third-party databases are **not bundled** with this repository or installer. XRD Phase Finder uses official online access, user-provided local folders, user API keys or optional local imports where available.

The main mechanism behind XRD Phase Finder is intentionally pragmatic: it first helps the user find chemically plausible candidates, then compares each candidate's own strongest calculated or measured peaks against the active experimental pattern. This is meant for phase identification and pre-refinement screening, not as a replacement for full Rietveld refinement.

---
# Interface Overview

The screenshots below show representative parts of the XRD Phase Finder workflow. The interface is under active development, so exact button placement and labels may change between releases.

## Phase Search Workspace

![Phase search overview](XRD_Finder/docs/screenshots/phase-search-overview.png)

The main workspace combines the active experimental pattern, candidate search results, selected phase overlays and element-based filters. The goal is to keep search, preview and interpretation in one window.

## Candidate Preview and Matching

![Candidate preview](XRD_Finder/docs/screenshots/candidate-preview.png)

Candidate rows can be browsed to preview calculated or measured reference peaks against the active XRD pattern. Structural candidates can be added to the selected phase set for profile comparison.

## Multi-pattern Comparison

![Multi-pattern stack](XRD_Finder/docs/screenshots/multi-pattern-stack.png)

Multiple checked XRD patterns can be displayed together with a controlled vertical offset. The highlighted pattern remains the active pattern for search and candidate preview.

## Compound Card

![Compound card](XRD_Finder/docs/screenshots/compound-card.png)

The compound card is intended to collect available phase metadata: formula, source, links, cell parameters, atom positions and diffraction lines when the source provides them.

## Database Management

![Database panel](XRD_Finder/docs/screenshots/database-panel.png)

The Databases tab manages local user libraries, indexed reference data, external source settings and cache/update/clear actions. Restricted databases are used only when the user provides data and has the right to access it.

# Features

## Search and Identification

- Powder XRD pattern viewer
- Automatic peak detection
- Element filters with required and optional elements
- COD online search and local COD/CIF indexing
- User CIF library indexing
- CCDC/CSD DOI/refcode lookup when the user has the CCDC Python API and valid access rights
- Materials Project search with user API key
- RRUFF measured powder-pattern overlays
- PDF-2 reference-card support from user-provided local data
- Candidate ranking by estimated peak-match probability for locally available structures

## Visualization

- Single-pattern and multi-pattern XRD display
- Vertical offset control for stacked XRD patterns
- Stable zoom while browsing candidates
- Candidate preview peaks shown directly over the active XRD pattern
- Persistent selected-phase overlays with editable colors
- Project files preserve processed XRD curves, selected phases, element filters and Finder view state
- Optional HKL labels
- High-resolution plot export

## Structure and Phase Data

- Drag-and-drop import for XRD and CIF files
- CIF-based diffraction pattern simulation
- Multi-phase profile calculation
- Automatic profile scaling
- Peak assignment framework
- Identification of unexplained diffraction peaks
- Compound cards with cell parameters, atom positions and publication links
- Diffraction-line tables in compound cards
- Cross-platform support (Windows, macOS and Linux)

---

# Typical Workflow

```text
Load experimental XRD
        |
        |
Peak detection
        |
        |
Search candidate phases
(COD / local CIF / RRUFF / PDF-2 / CCDC / Materials Project)
        |
        |
Load crystal structures (CIF)
        |
        |
Calculate theoretical diffraction patterns
        |
        |
Compare experimental and calculated profiles
        |
        |
Assign diffraction peaks
        |
        |
Identify unexplained peaks
```

---

# Interaction Guide

- **Element table**
  - Left click marks an element as required.
  - Right click marks an element as optional.
  - Clicking again removes that element from the gate.
- **Candidate list**
  - Single click previews the candidate and opens its card.
  - Double click adds a structural candidate to the selected phase set.
  - Right click opens actions such as add, calculate overlay and export CIF.
- **Selected candidates**
  - Single click shows that phase in the plot and card.
  - Right click changes color, exports CIF, removes the phase or clears the list.
- **Project tree**
  - The highlighted XRD row is the active pattern for search and preview.
  - Checkboxes control what is visible in the plot.
  - Order arrows change plot and legend order.
- **Projects**
  - Save project stores imported XRD/CIF order, processed curves, selected phase assignments and Finder UI state.
- **Plot**
  - Use mouse zoom/pan normally.
  - `Reset view` or right click -> `Show full pattern` returns to the full range.

The `?` button in the application opens a compact in-app helper with the same core controls.

---

# Installation

## Download

Latest release assets:

- Windows 10/11: [XRD_Phase_Finder_Setup_1.1.0.exe](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.1.0/XRD_Phase_Finder_Setup_1.1.0.exe)
- macOS: [XRD_Phase_Finder_macOS_1.1.0.zip](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.1.0/XRD_Phase_Finder_macOS_1.1.0.zip)
- All releases: [GitHub Releases](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases)

Large crystallographic databases are user-managed. COD, RRUFF, PDF-2, Materials Project and CCDC/CSD data are not redistributed with the installer.

## Requirements

Windows installer:

- Windows 10 or Windows 11, 64-bit recommended.
- Administrator rights for installation into the selected application folder.
- Internet access during first setup, because Python or Python packages may need to be downloaded.
- About 1 GB of free disk space for the shared scientific Python environment.

Source checkout / macOS / Linux:

- Python 3.11 or newer.
- `pip` and Python virtual environment support.
- Internet access for installing Python packages.

XRD Phase Finder uses a shared per-user environment named `XRD_Toolkit`. Future XRD applications from the same toolkit can reuse it.

## Windows

Download and run:

```text
XRD_Phase_Finder_Setup_1.1.0.exe
```

The installer:

- installs XRD Phase Finder into the selected application folder
- creates Start Menu and optional Desktop shortcuts
- creates or reuses the shared `XRD_Toolkit` Python environment in user AppData
- installs required Python packages
- adds an uninstall entry to Windows
- checks for updates when XRD Phase Finder starts

If Python 3.11 is not already available, the setup script first tries `winget` and then falls back to the official Python 3.11.9 installer from python.org.

## macOS

Download and extract:

```text
XRD_Phase_Finder_macOS_1.1.0.zip
```

Then run:

```text
install_macos.command
```

The installer creates or reuses:

```text
~/Library/Application Support/XRD_Toolkit
```

and installs the application bundle to `/Applications/XRD Phase Finder.app` when possible, otherwise to `~/Applications/XRD Phase Finder.app`.

If macOS blocks the scripts after download or sync, run this once from Terminal inside the extracted folder:

```bash
chmod +x install_macos.command update_macos.command setup_env.command toolkit/*.command XRD_Finder/*.command
xattr -dr com.apple.quarantine .
```

Manual update from a source checkout:

```text
update_macos.command
```

Optional maintainer-only DMG build on macOS:

```text
scripts/build_macos_dmg.command
```

## Linux

Linux is currently source-checkout based:

```bash
chmod +x setup_env.sh XRD_Finder/*.sh
./setup_env.sh
./XRD_Finder/run_finder.sh
```

Command line interface:

```bash
./XRD_Finder/run_finder_cli.sh
```

On a minimal Linux installation you may also need Python venv/pip and Qt desktop libraries:

```bash
sudo apt install python3 python3-venv python3-pip libxcb-cursor0 libegl1
```

For Fedora:

```bash
sudo dnf install python3 python3-pip xcb-util-cursor mesa-libEGL
```

## Source Checkout Commands

These commands are mainly for developers or users running directly from a source checkout.

Setup:

```text
setup_env.bat          # Windows
setup_env.command      # macOS
./setup_env.sh         # Linux
```

Graphical launchers:

```text
XRD_Finder\run_finder.bat
./XRD_Finder/run_finder.command
./XRD_Finder/run_finder.sh
```

Command-line launchers:

```text
XRD_Finder\run_finder_cli.bat
./XRD_Finder/run_finder_cli.command
./XRD_Finder/run_finder_cli.sh
```

The graphical launcher can receive initial files:

```text
XRD_Finder\run_finder.bat --pattern "path\to\pattern.xy" --cif "path\to\phase.cif"
./XRD_Finder/run_finder.sh --pattern "path/to/pattern.xy" --cif "path/to/phase.cif"
```

For normal interactive work, importing XRD/CIF files from the application window is preferred.

---

# Reference Data Sources

The **Databases** tab controls which data sources participate in phase search. The user decides which sources are active for a particular search and which local libraries should be indexed or cleared.

Open or publicly accessible sources:

- User phase library from imported CIF files
- COD online search
- COD local folder/archive indexed by the user
- RRUFF measured powder-pattern data
- Materials Project search with the user's own API key
- AFLOW and OQMD structure services when enabled in the application workflow

Restricted or license-controlled sources, available only when the user has the right to use them:

- PDF-2 reference-card data from a local user-provided installation or folder
- CCDC/CSD data through the user's own CCDC Python API installation and valid license/access rights
- other local commercial, institutional or private databases supplied by the user

Large databases are never bundled with the application and are not downloaded automatically. Use the controls in **Databases** to download, index, update or clear local data explicitly.

Common database actions include:

- `Index COD CIF folder` for an unpacked local COD CIF collection
- `Index COD ZIP archive` for a downloaded COD archive
- `Download COD archive URL` when you have a direct COD ZIP URL
- `Download RRUFF` and `Index RRUFF` for RRUFF measured powder patterns

RRUFF entries are measured reference patterns. They can be overlaid on the
experimental pattern, but they are not calculated CIF phase profiles.

PDF-2 entries are local reference cards. The software can read a local
PDF-2 folder when available, but the PDF-2 database itself is not bundled
or redistributed.

See [Third-party Data Sources](THIRD_PARTY_DATA_SOURCES.md) for notes on COD,
Materials Project, RRUFF and restricted CCDC/CSD data usage and attribution.

---

# Multi-pattern Figures

Use `Show -> All selected` to display all checked XRD patterns from the project
tree. The `Offset` slider controls vertical separation between patterns as a
percentage of the previous pattern height.

The active XRD pattern is the row highlighted in the project tree. Search,
candidate preview and phase calculations always use the active pattern only.
Use the `Order` arrow buttons above the project tree to change the display order
of XRD patterns and CIF phases.

Zoom is intentionally stable while browsing candidates or changing the active
pattern. Use `Reset view` or right-click the plot and choose `Show full pattern`
to return to the full view.

---

# Repository Structure

```text
XRD_Analysis_Toolkit/
    README.md
    CHANGELOG.md
    PROJECT_HEALTH.md
    THIRD_PARTY_DATA_SOURCES.md
        Project documentation, release history and data-source notes

    pyproject.toml
        Python package metadata

    setup_env.bat
    setup_env.command
    setup_env.sh
        Manual source-checkout setup scripts for Windows, macOS and Linux

    toolkit/
        manifest.json
            Toolkit and application version metadata
        updates/xrd_finder.json
            Machine-readable update metadata for release checks
        setup_xrd_toolkit_env.bat
        setup_xrd_toolkit_env.command
        launch_xrd_finder_preview.ps1
        launch_xrd_finder_preview.command
            Shared runtime setup and startup/update preview support

    XRD_Finder/
        app.json
            XRD Phase Finder application metadata
        xrd_finder/
            XRD Phase Finder application source code
        docs/screenshots/
            Screenshots used by the README
        requirements.txt
            Required Python packages for XRD Phase Finder
        requirements-optional.txt
            Reserved for integrations that may require extra user-installed packages
        run_finder.bat
        run_finder.command
        run_finder.sh
            Source-checkout graphical launchers
        run_finder_cli.bat
        run_finder_cli.command
        run_finder_cli.sh
            Source-checkout command-line launchers
```

The repository contains source code, documentation, runtime setup scripts and update metadata. Generated installer files such as `XRD_Phase_Finder_Setup_1.1.0.exe` and `XRD_Phase_Finder_macOS_1.1.0.zip` are **not committed to the repository**; they are published separately as GitHub Release assets.

The root `XRD_Analysis_Toolkit` layout keeps shared toolkit files separate from the `XRD_Finder` application folder. This leaves room for additional XRD-related applications later while preserving a clear application boundary.

Downloaded databases, user libraries, temporary files and local caches are intentionally kept outside Git. The installed Windows application uses the per-user `XRD_Toolkit` location in AppData. Source-checkout users can set `XRD_FINDER_DATA_DIR` to use a custom data/cache location.

Release source archives should be built from a clean Git tree so `.gitattributes` exclusions are applied:

```bash
python scripts/build_release_archive.py
```

The script creates `dist/XRD_Phase_Finder_Source_<version>.zip` with Git metadata, bytecode, OS junk, local database caches and legacy XRD Manager scaffolding excluded.

## Profiling Finder performance

Use the standalone profiler before making further hot-path optimizations:

```bash
python scripts/profile_finder.py --pattern path/to/pattern.xy --cif path/to/cif_folder --limit 100 --repeat 2
```

The first run captures `cProfile` statistics for `FinderService`; repeat runs reuse the same service instance so CIF-to-HKL cache effects are visible.

---

# Scientific Background

The software combines several standard crystallographic approaches:

- Bragg diffraction
- Structure-factor based diffraction simulation
- CIF crystallographic models
- Multi-phase profile fitting
- Peak assignment
- Open crystallographic databases

The current implementation is intended for **initial phase identification** and **visual interpretation** of powder diffraction patterns. It is **not** intended to replace full-profile refinement packages such as GSAS-II, FullProf or TOPAS.

---

# Current Status

Current development stage: **1.0 stable release**.

The application is ready for practical search-match and visual phase-identification workflows. Quantification, I/Ic and probability values should be treated as interpretive aids rather than a substitute for full-profile refinement.

Planned next steps include batch processing, stronger separation of fitting services from the UI layer and expanded automated tests.

---

# License

MIT License

---

# Citation

If you use this software in scientific research, please cite this GitHub repository.

A dedicated software publication describing the Phase Finder algorithm is currently in preparation.

---

# Author

**Artem B. Kuznetsov**

Institute geology and mineralogy SB RAS

GitHub:
https://github.com/ABKuznetsov
