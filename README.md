# XRD Analysis Toolkit

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Status](https://img.shields.io/badge/Status-Beta-orange.svg)

**XRD Analysis Toolkit** is an open-source, cross-platform application for **phase identification from powder X-ray diffraction (XRD) patterns** using open crystallographic databases and CIF-based diffraction simulation.

The project is designed as a lightweight alternative to commercial search-match software and focuses on helping researchers interpret diffraction patterns by combining experimental data with theoretical diffraction profiles calculated directly from crystal structures.

---

# Screenshot

<img width="2048" height="1113" alt="image" src="https://github.com/user-attachments/assets/dc644ac3-2613-4110-9e08-4c8cf70d8dd4" />


**Main window of the XRD Phase Finder.**  
The application displays the experimental diffraction pattern, calculated profile, theoretical peak positions of selected phases, and highlights diffraction peaks that remain unexplained by the current phase set.

---

# Features

- Powder XRD pattern viewer
- Automatic peak detection
- Search using the Crystallography Open Database (COD)
- Local CIF database support
- CIF-based diffraction pattern simulation
- Multi-phase profile calculation
- Automatic profile scaling
- Peak assignment framework
- Identification of unexplained diffraction peaks
- Cross-platform support (Windows and macOS)

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

Scientific interface

```text
run_finder_sci.bat
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

---

# Opening Files from the Command Line

GUI

```text
run_finder.bat --pattern "path\to\pattern.xy" --cif "path\to\phase.cif"
```

CLI

```text
run_finder_cli.bat "path\to\pattern.xy" "path\to\phase.cif"
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

# Repository Structure

```text
xrd_manager/
    Main application source code

requirements.txt
    Required Python packages

requirements-optional.txt
    Optional online database support

setup_env.bat
setup_env.command
    Create Python virtual environment

run_finder.bat
run_finder.command
    Launch graphical interface

run_finder_sci.bat
    Scientific interface

run_finder_cli.bat
run_finder_cli.command
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

Planned

- Structure Viewer
- Le Bail refinement
- Thermal expansion analysis
- Full XRD Manager ecosystem

---

# Roadmap

The XRD Analysis Toolkit is being developed as a collection of independent open-source tools for crystallography and powder diffraction.

Current module:

- XRD Phase Finder

Future standalone applications:

- Structure Viewer
- Le Bail Refinement
- Thermal Expansion Analyzer

These applications will also become components of the future XRD Manager ecosystem.

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
