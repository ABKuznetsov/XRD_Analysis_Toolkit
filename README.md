# XRD Phase Finder

![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**XRD Phase Finder** is an open-source desktop program for powder X-ray diffraction phase identification. It loads experimental XRD patterns, searches user and open crystallographic sources, calculates reference diffraction locally with CRiStMa, compares observed and calculated peaks, ranks candidates with Match and Gain scores, and saves the interpretation state in portable `.xpff` project files.

This repository contains the standalone Finder application. Structure viewing and other crystallographic tools are developed separately and are not bundled with the Finder installers.

## Download

- [Windows installer: XRD_Phase_Finder_Setup_v1_6_1.exe](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.6.1/XRD_Phase_Finder_Setup_v1_6_1.exe)
- [macOS package: XRD_Phase_Finder_macOS_1.6.2.pkg](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.6.2/XRD_Phase_Finder_macOS_1.6.2.pkg)
- Linux: install from source with the commands below.

All release files are listed on the [XRD Phase Finder 1.6.2 release page](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/tag/v1.6.2).

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

## Libraries and data sources

Core runtime libraries:

- **PySide6** for the desktop interface;
- **pyqtgraph** for interactive diffraction plots;
- **NumPy** and **SciPy** for numerical processing, peak operations, fitting and optimization;
- **pybaselines** for baseline/background-processing methods;
- **CRiStMa** for CIF-backed crystallographic and powder-diffraction calculations;
- **SQLite** through the Python standard library for local phase, search and peak indexes;
- the Python standard-library HTTP stack plus **certifi** for optional Materials Project REST access;
- **rfc8785**, **certifi** and **packaging** for project serialization, HTTPS certificate handling and version/runtime checks.

Supported phase and reference sources:

- **User CIF library**: direct CIF import and local user phase collections;
- **COD**: online search, downloaded CIF cache and optional local/bulk COD indexing;
- **Materials Project**: optional online search with a user API key;
- **AFLOW** and **OQMD**: optional online computational-structure searches;
- **RRUFF**: optional local powder-reference index from RRUFF data;
- **PDF-style line databases**: local line-list databases when configured by the user;
- **CCDC/CSD**: optional DOI/refcode lookup when the CCDC Python API or public CCDC download route is available; CSD itself is not bundled.

## Quick start

### Windows

Download and run `XRD_Phase_Finder_Setup_v1_6_1.exe` from the release page. The installer creates Start Menu and Desktop shortcuts and registers `.xpff` project files.

On first launch, XRD Phase Finder checks the per-user scientific Python runtime. If required packages are missing, the launcher offers to install or repair them under the user profile. Project files and personal data are not stored in the installation directory.

### macOS

Download and run `XRD_Phase_Finder_macOS_1.6.2.pkg` from the release page. The package installs `XRD Phase Finder.app` into `/Applications`.

On first launch, XRD Phase Finder checks the per-user scientific Python runtime under `~/Library/Application Support/Sci`. If required packages are missing, the launcher offers to install or repair them. Project files, settings, caches and local databases are stored in the user Application Support directory, not inside the application bundle.

For local packaging from source on macOS:

```bash
scripts/build_macos_pkg.command
```

The package builder creates a Finder-only `.pkg` under `dist/`.

For a locked-down workstation, prepare the runtime and local caches on an approved Mac first, then build a local secure/offline installer:

```bash
scripts/build_secure_macos_pkg.command
```

This creates `XRD_Phase_Finder_Secure_macOS_<version>.pkg` under `dist/` for local deployment. The secure installer installs the application, copies the prepared Sci runtime and local Finder data/cache snapshot to the target user profile, and enables offline/secure mode automatically.

For development or direct source runs:

```bash
./run_finder.command
```

### Ubuntu / Linux from source

Linux is supported from source. A dedicated `.deb`/AppImage package is not bundled in the 1.6.2 release yet, because Qt/PySide binary compatibility depends on the target distribution, desktop session and system libraries.

The commands below were written for recent Ubuntu/Debian systems. Python 3.11 or 3.12 is recommended.

Install Python, Git and the Qt/PySide system libraries commonly required by the desktop interface:

```bash
sudo apt update
sudo apt install -y \
  git \
  python3.12 \
  python3.12-venv \
  python3-pip \
  libegl1 \
  libgl1 \
  libxcb-cursor0 \
  libxkbcommon-x11-0 \
  libxcb-xinerama0 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-render-util0
```

Clone the repository and create an isolated Python environment:

```bash
git clone https://github.com/ABKuznetsov/XRD_Analysis_Toolkit.git
cd XRD_Analysis_Toolkit

python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
```

Start the graphical application:

```bash
python -m xrd_finder.apps.finder_gui
```

If `python3.12` is not available on the distribution, use Python 3.11 instead:

```bash
python3.11 -m venv .venv
```

If Qt fails under Wayland, try an X11 desktop session or force the Qt XCB backend:

```bash
QT_QPA_PLATFORM=xcb python -m xrd_finder.apps.finder_gui
```

User settings and caches are created in the user profile. On Linux this includes local Finder data, imported CIF libraries and downloaded database caches; the repository directory can remain read-only after installation.

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

Materials Project search uses a lightweight built-in REST connector and does not require the heavy `mp-api`/`pymatgen` stack for normal Finder operation. A Materials Project API key is still required for online queries; configure it in the database/settings tools before searching Materials Project. If no key is configured, Finder continues to work with user libraries, COD, local caches and other enabled sources.

## Offline and controlled-network use

XRD Phase Finder has no telemetry. It can work without an internet connection when the required user CIF libraries, local COD/PDF-style indexes, RRUFF data or other local caches have already been prepared.

For closed or government/institutional networks, use **Tools -> Network mode** and select **Offline / secure**. The setting is stored in the user data directory and is read by both the launcher and the main application. The launcher then shows that secure/offline mode is enabled and skips network-dependent checks.

On macOS, **Tools -> Create secure macOS installer...** can build a separate secure/offline `.pkg` from the current application, prepared Sci runtime and local cache state. The same builder is available from the terminal as `scripts/build_secure_macos_pkg.command`.

For scripted deployments, the same mode can be forced with:

```bash
XRD_FINDER_OFFLINE=1
```

In this mode online database requests, launcher update checks and automatic runtime repair/downloads are skipped immediately. Local project files, user CIF libraries, local SQL indexes and cached phase libraries remain available.

Diagnostic runtime logs are local-only and capped/rotated. They redact full home-directory paths and are intended for troubleshooting startup or runtime failures. To disable Finder diagnostic logs for a locked-down workstation, start with:

```bash
XRD_FINDER_DIAGNOSTICS=0
```

Operational installer or repair scripts can still create setup logs while building the scientific runtime. For a fully offline deployment, prepare the Sci runtime and local database caches on a connected machine, then distribute the application package and cache/settings exports through the institution's approved software channel.

See [SECURITY.md](SECURITY.md) for the controlled-network deployment checklist.

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
