# XRD Phase Finder

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**XRD Phase Finder** is an open-source desktop program for powder X-ray diffraction phase identification. It loads experimental XRD patterns, searches user and open crystallographic sources, calculates reference diffraction locally with CRiStMa, compares observed and calculated peaks, ranks candidates with Match and Gain scores, and saves the interpretation state in portable `.xpff` project files.

This repository contains the standalone Finder application. Structure viewing and other crystallographic tools are developed separately and are not bundled with the Finder installers.

## Download

- [Windows installer: XRD_Phase_Finder_Setup_v1_6_1.exe](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.6.1/XRD_Phase_Finder_Setup_v1_6_1.exe)
- macOS package: build from this repository with `scripts/build_macos_pkg.command` until the 1.6.1 macOS package is attached to the release.

All release files are listed on the [XRD Phase Finder 1.6.1 release page](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/tag/v1.6.1).

## Main features

- import one or many XRD patterns and CIF files;
- manage instrument profiles, radiation wavelength and profile broadening;
- search user CIF libraries, COD, Materials Project, AFLOW, OQMD, RRUFF and PDF-style line databases when configured;
- calculate CIF diffraction lines through CRiStMa for the active instrument profile;
- rank candidates by Match and Gain scores and inspect residual signal;
- show calculated profiles, phase ticks, coverage markers, unknown peaks and selected phases;
- save `.xpff` projects with imported data, selected phases and calculation state;
- keep personal appearance settings, instrument profiles and local database caches in user AppData/Application Support;
- export and import settings and cached user/COD/Materials Project phase libraries between computers.

## Quick start

### Windows

Download and run `XRD_Phase_Finder_Setup_v1_6_1.exe` from the release page. The installer creates Start Menu and Desktop shortcuts and registers `.xpff` project files.

On first launch, XRD Phase Finder checks the per-user scientific Python runtime. If required packages are missing, the launcher offers to install or repair them under the user profile. Project files and personal data are not stored in the installation directory.

### macOS

From the repository root on macOS:

```bash
scripts/build_macos_pkg.command
```

The package builder creates a Finder-only `.pkg` under `dist/` and installs `XRD Phase Finder.app` into `/Applications`.

For development or direct source runs:

```bash
./run_finder.command
```

### Ubuntu / Linux from source

Ubuntu packages commonly needed by Qt/PySide:

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip libxcb-cursor0 libegl1 libgl1 libxkbcommon-x11-0
```

Create and run a local environment:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
python -m xrd_finder.apps.finder_gui
```

If Qt fails under Wayland, try starting from an X11 session or run:

```bash
QT_QPA_PLATFORM=xcb python -m xrd_finder.apps.finder_gui
```

## Example project

Use **Help -> Open example project** inside the application. The bundled example opens read-only so that new users can inspect the workflow without overwriting their own projects. It contains an experimental pattern and selected phases configured for the wavelength stored in the project, so it can be used as a compact demonstration of import, processing, search-match and plot inspection.

## Database search and cache behavior

XRD Phase Finder does not calculate the complete COD or Materials Project on every search. It combines several layers:

- **User phase library**: CIF files imported by the user are copied into the local user cache, indexed once and reused.
- **COD online**: formula/name/element queries ask the COD service for a limited candidate set. Downloaded CIF files are cached locally.
- **COD local/bulk**: downloaded COD CIF folders or ZIP archives can be indexed for offline use.
- **Materials Project, AFLOW and OQMD**: online queries are optional and depend on the configured service and network access. Retrieved structures are cached locally.
- **RRUFF and PDF-style line sources**: used as reference-line sources when configured.

The local phase cache stores CIF paths, cell metadata, atoms, calculated peak lists, strongest-peak summaries and a SQL peak index. Repeated searches use this index instead of recalculating every structure. The peak preselection index compares observed peaks by d-spacing using the active wavelength, so non-Cu radiation sources can use the same cached structures.

Typical search time depends on the number of enabled sources, local cache size, network access and the number of selected elements. Narrow element filters are faster and more specific. If COD is unavailable, the program continues with local results and shows a warning; VPN or institutional network filtering can block COD access.

## Materials Project access

Materials Project search uses the official `mp-api` Python client. The Windows runtime installs `mp-api` during first launch so that the connector is available without manual package installation. A Materials Project API key is still required for online queries; configure it in the database/settings tools before searching Materials Project. If no key is configured, Finder continues to work with user libraries, COD, local caches and other enabled sources.

## Match and Gain scores

Finder uses the scores as practical ranking aids rather than as crystallographic proof of phase presence.

- **Match** estimates how well the candidate reference peaks are covered by the observed pattern at the current wavelength, tolerance and processing settings.
- **Gain** estimates how much the candidate improves the current interpretation by explaining residual signal that is not already covered by selected phases.

High scores identify candidates worth inspecting. Final phase selection should still consider chemistry, instrument profile, peak positions, relative intensities, residuals and whether the strongest unexplained peaks are accounted for.
## Moving settings and local caches between computers

Use **Tools -> Export settings...** and **Tools -> Import settings...** to transfer appearance settings, layout settings and instrument profiles.

Use **Database -> User phase library...** or the **Database settings** window to export/import cached user, COD and Materials Project phase libraries. These transfers include the SQL peak index, so imported caches do not need to be recalculated immediately.

## Repository layout

```text
xrd_finder/              application package
launcher/                startup, update and runtime helper scripts
installer/finder_setup/  Windows installer definition
scripts/                 release/package scripts
requirements.txt         runtime Python dependencies
pyproject.toml           package metadata
```

Release packages intentionally exclude development-only folders such as `tests/`, `docs/`, `build/`, `dist/`, local logs, local caches and database downloads.

## Development checks

```bash
python -m compileall xrd_finder
python -m pytest tests
```

## License

MIT. See `LICENSE`.
