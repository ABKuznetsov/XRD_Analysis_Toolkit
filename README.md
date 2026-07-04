# XRD Analysis Toolkit

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Beta-orange.svg)

**XRD Analysis Toolkit** is an open-source, cross-platform application for **phase identification from powder X-ray diffraction (XRD) patterns** using open crystallographic databases and CIF-based diffraction simulation.

The project is designed as a lightweight alternative to commercial search-match software and focuses on helping researchers interpret diffraction patterns by combining experimental data with theoretical diffraction profiles calculated directly from crystal structures.

---

# Screenshot

<img width="3254" height="1747" alt="image" src="https://github.com/user-attachments/assets/ddbe0121-46c0-4555-9a4c-24e9d0673093" />



**Main window of the XRD Phase Finder.**
The application displays the experimental diffraction pattern, calculated profile, theoretical peak positions of selected phases, and highlights diffraction peaks that remain unexplained by the current phase set.

---

# Features

- Powder XRD pattern viewer
- Multi-pattern XRD series display with vertical offsets
- Drag-and-drop import for XRD and CIF files
- Automatic peak detection
- Search using the Crystallography Open Database (COD)
- Local CIF database support
- CIF-based diffraction pattern simulation
- Multi-phase profile calculation
- Automatic profile scaling
- Peak assignment framework
- Identification of unexplained diffraction peaks
- Compound cards with cell parameters, atom positions and publication links
- High-resolution plot export
- Cross-platform support (Windows, macOS and Linux)

---

# Typical Workflow

```text
Load experimental XRD
        │
        ▼
Peak detection
        │
        ▼
Search candidate phases
(COD / Local Database)
        │
        ▼
Load crystal structures (CIF)
        │
        ▼
Calculate theoretical diffraction patterns
        │
        ▼
Compare experimental and calculated profiles
        │
        ▼
Assign diffraction peaks
        │
        ▼
Identify unexplained peaks
```

---

# Installation

## Requirements

Python **3.11** or newer.

Download Python from the official website:

https://www.python.org/downloads/

---

## Windows

Run

```text
setup_env.bat
```

The script automatically

- creates a virtual environment (`.venv`)
- installs all required Python packages

Launch the graphical interface

```text
run_finder.bat
```

Command line interface

```text
run_finder_cli.bat
```

---

## macOS

Run

```text
setup_env.command
```

Launch the application

```text
run_finder.command
```

Command line interface

```text
run_finder_cli.command
```

If macOS blocks the scripts after copying or syncing the folder, run this once
from Terminal inside the project directory:

```bash
chmod +x *.command
xattr -dr com.apple.quarantine .
```

---

## Linux

Run

```bash
chmod +x *.sh
./setup_env.sh
```

Launch the application

```bash
./run_finder.sh
```

Command line interface

```bash
./run_finder_cli.sh
```

On a minimal Linux installation you may also need Python venv/pip and Qt desktop
libraries:

```bash
sudo apt install python3 python3-venv python3-pip libxcb-cursor0 libegl1
```

For Fedora:

```bash
sudo dnf install python3 python3-pip xcb-util-cursor mesa-libEGL
```

---

# Opening Files from the Command Line

GUI

```text
run_finder.bat --pattern "path\to\pattern.xy" --cif "path\to\phase.cif"
./run_finder.command --pattern "path/to/pattern.xy" --cif "path/to/phase.cif"
./run_finder.sh --pattern "path/to/pattern.xy" --cif "path/to/phase.cif"
```

CLI

```text
run_finder_cli.bat "path\to\pattern.xy" --cif "path\to\phase.cif"
./run_finder_cli.command "path/to/pattern.xy" --cif "path/to/phase.cif"
./run_finder_cli.sh "path/to/pattern.xy" --cif "path/to/phase.cif"
```

---

# Optional Materials Project Support

Materials Project support is optional and is **not installed by default**.

Install the optional dependencies

```bash
pip install -r requirements-optional.txt
```

or

```bash
.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
```

Then enter your Materials Project API key in the application settings.

---

# Optional Reference Databases

The **Databases** tab controls which sources participate in phase search.
Use the checkboxes to enable only the databases you want:

- User library
- COD local
- COD online
- RRUFF
- Materials Project

Large databases are never downloaded automatically. Use the buttons in
**Databases** to download or index them explicitly:

- `Index COD CIF folder` for an unpacked local COD CIF collection
- `Index COD ZIP archive` for a downloaded COD archive
- `Download COD archive URL` when you have a direct COD ZIP URL
- `Download RRUFF` and `Index RRUFF` for RRUFF measured powder patterns

RRUFF entries are measured reference patterns. They can be overlaid on the
experimental pattern, but they are not calculated CIF phase profiles.

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
xrd_manager/
    Main application source code

requirements.txt
    Required Python packages

requirements-optional.txt
    Optional online database support

CHANGELOG.md
    Release notes

setup_env.bat
setup_env.command
setup_env.sh
    Create Python virtual environment

run_finder.bat
run_finder.command
run_finder.sh
    Launch graphical interface

run_finder_cli.bat
run_finder_cli.command
run_finder_cli.sh
    Command line interface

pyproject.toml
    Package metadata
```

Downloaded databases, user libraries and local caches are intentionally excluded from the repository.

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

Current development stage:

**Beta**

Implemented

- ✔ Experimental XRD viewer
- ✔ Phase Finder
- ✔ COD search
- ✔ CIF parser
- ✔ Structure-based diffraction simulation
- ✔ Multi-phase profile calculation
- ✔ Peak assignment framework


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
