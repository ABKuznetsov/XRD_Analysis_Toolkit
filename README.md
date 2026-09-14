# XRD Phase Finder

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**XRD Phase Finder** is an open-source desktop application for powder X-ray diffraction phase identification. It is focused on practical interpretation of mixtures: loading experimental XRD patterns, selecting expected elements, searching open or local phase sources, comparing calculated/reference peaks with the experiment, and saving the full interpretation state in a portable project file.

This repository is the standalone Finder application. Structure viewing and other crystallographic tools are developed separately.

## Main Features

- import one or many XRD patterns and CIF files;
- search local/user libraries, COD, RRUFF, PDF-style line databases and optional online sources;
- rank candidates by Match and Gain scores;
- show candidate peak markers, calculated overlays, residuals and selected phases;
- estimate smoothing and background, including separate background and amorphous/halo handling;
- save `.xpff` projects with imported data, processing state, selected phases, instrument profile and view settings;
- use CRiStMa for crystallographic radiation/profile definitions used by Finder calculations.

## Quick Start

macOS:

```bash
./run_finder.command
```

Windows:

```text
run_finder.bat
```

The launchers create or reuse a per-user scientific Python runtime and then start the graphical application. Installed builds use the same runtime logic through the preview launcher.

## Installation Assets

The macOS package builder creates:

```text
dist/XRD_Phase_Finder_macOS_1.6.0.pkg
```

Build it from the repository root:

```bash
scripts/build_macos_pkg.command
```

The package installs `XRD Phase Finder.app` into `/Applications`.

Windows installer scripts live in:

```text
installer/finder_setup/
```

## Repository Layout

```text
xrd_finder/              application package
launcher/                startup, update and runtime helper scripts
installer/finder_setup/  Windows installer definition
scripts/                 release/package scripts
tests/                   development tests
requirements.txt         runtime Python dependencies
pyproject.toml           package metadata
```

Release packages intentionally exclude development-only folders such as `tests/`, `docs/`, `build/`, `dist/`, local caches and database downloads.

## Data Sources

XRD Phase Finder can use open crystallographic databases and user-provided files. User CIF files can be added directly, while larger external databases are indexed locally when configured by the user. Database terms and licenses remain the responsibility of the data provider and user.

## Development

Create a local environment:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements.txt
```

Run the application:

```bash
.venv/bin/python -m xrd_finder.apps.finder_gui
```

Run focused checks:

```bash
python3 -m compileall xrd_finder
python3 -m pytest tests
```

## License

MIT. See `LICENSE`.
